---
name: tex-ledger
description: Make a LaTeX project compile and keep it maintainable and repeatable (pdfLaTeX / XeLaTeX / LuaLaTeX, BibTeX / Biber, multi-file, English and Chinese). Compiles a copy of the project as a reproducible build would (all errors in one run, bibliography, passes until the cross-references converge), reads the log into root causes (an unclosed brace in an included file is reported once, with the dozen errors it caused folded under it, not as "first error"), runs static checks that need no TeX (braces, environments, $, underscores, undefined labels / citations / graphics, .bib keys, table column counts, float captions and labels, package order and conflicts, engine mismatches), applies deterministic fixes one at a time and keeps each only if the compile does not get worse, compares a manuscript with a journal / conference template and moves it into the template, and hands over sources + PDF + a build report (engine, package versions, passes, commands, PDF hash on two clean builds) + change diffs + repeat-build files + result.json. Use for "fix this LaTeX compile error", "make it compile", "编译报错", "adapt my paper to the template", "table overflows", "undefined references", "make the build reproducible". Python 3.9+ standard library; compiling needs TeX Live / MiKTeX / TinyTeX when available (without it, static checks only and an honest "not compiled").
---

# tex-ledger

The usual failures with LaTeX in an agent: stopping at the first error message (which is often a consequence), "fixing" by deleting content or silencing the log, delivering a PDF or a snippet instead of sources, and a build nobody else can repeat. This skill compiles a *copy*, tells you the root causes with file and line, verifies every edit by recompiling, and records everything needed to repeat the build.

Not for: writing the paper's prose, drawing figures, installing a TeX distribution.

```bash
S=/skills/weekly-skill/scripts/tx.py      # or the scripts/ folder next to this SKILL.md
```
Budget (64 requests, 900 s): `run` (1), a few edit / `check` rounds, `build` (1). One compile of a normal paper takes seconds.

## Procedure

1. **Read the task** (`/input/task.md`, `/input/case.json`): which file / folder / zip is the project, which template or venue, engine named, what must change (compile errors, formulas, tables, references, template). Task wording beats these defaults.
2. **Compile and diagnose in one call:**
   ```bash
   python3 $S run --case /input/case.json --out /app/output
   ```
   (or `run --src DIR|main.tex|project.zip --out /app/output [--engine xelatex] [--main sub/main.tex]`). The project is **copied** to `/app/output/.work/src` (the pristine copy is `.work/orig`); `brief.md` prints: project graph, engine (from `%!TEX program`, packages such as fontspec / ctex, or the task), TeX versions found, the baseline build pass by pass, **root causes** (undefined commands grouped, cascades folded, `likely starts at: file:line` for runaway-argument errors), warnings (undefined references and citations, big overfull boxes), and the static checks. Read it all.
3. **Fix the root causes, smallest edit first.** Edit files in `/app/output/.work/src` only. After each edit (or a few), `python3 $S check /app/output/.work`: it recompiles and prints errors fixed / new / remaining and the passes. `python3 $S diag /app/output/.work [--all]` shows source lines around each cause; `lint` lists static findings. `python3 $S fix /app/output/.work --safe` applies the deterministic fixes (missing `\usepackage` for an undefined command, `$$..$$` → `\[..\]`, `{\bf x}` → `\textbf{x}`, `\label` after `\caption`, `[h]` → `[htbp]`, duplicate `\usepackage`, `hyperref` last, `inputenc` removed for XeLaTeX) one rule at a time and **reverts any rule that makes the compile worse**.
4. **Template adaptation** (when the task names a template and you have its files): `python3 $S template W --template TEMPLATE_DIR` compares front matter (title, authors, abstract, keywords, packages, layout-changing packages); `python3 $S adapt W --template TEMPLATE_DIR` writes the manuscript's body, title, abstract and keywords into the template's main file (authors are **not** mapped: say so); `python3 $S use W` makes it the working copy; `check`, then fix. Layout packages (geometry, setspace, titlesec, fancyhdr, times ...) of the manuscript are not carried over: the template decides the layout.
5. **Build the hand-over:** `python3 $S build /app/output/.work --out /app/output [--case /input/case.json --answers answers.json]` — clean double build (the PDF hash of two clean builds is compared), then `src/` (clean sources), `<main>.pdf`, `build_report.md/json`, `changes.md` (unified diff original → delivered, plus every verified fix), `diagnostics.json`, `repro/build.sh`, `repro/Makefile`, `repro/latexmkrc`, `review_checklist.md`, `result.json`.
6. **Fill the contract.** `result.json` takes its fields from the case's `output_contract`; derivable ones are filled, others are `null` and listed in `_meta.unfilled_fields` and printed as `UNFILLED`. Put your own content in `answers.json` (`{"field": value}`) and re-run `build --answers`. Never leave a field out, never invent content for it.
7. **Before you stop:** `status` is `success` only when a PDF exists, there are no errors, the passes converged, and no reference / citation is undefined; otherwise `partial` (or `not_compiled` without TeX) and your final message lists what is open (the `OPEN ...` lines). Say what you verified by compiling and what you only changed.

## Rules that decide quality

- **Fix causes, not symptoms.** Use the root-cause list: the first structural error (runaway argument, `\begin` ended by the wrong `\end`, extra `}`) explains the errors after it; an undefined command is usually a missing package; "File ended while scanning" starts where an argument was left open, often in another file (the brief says where). Never stop at the first message, never delete the offending text to make the log quiet.
- **Never hide errors.** Do not add `\batchmode`, `\scrollmode`, `\nonstopmode` or `-halt-on-error` games to the source, do not comment out content, do not redefine commands to swallow errors, do not replace figures with placeholders. If a package or class is not installed and cannot be installed, say so (`missing_file ... not installed`) and keep the content; use a documented equivalent only if it gives the same result and say that you did.
- **Deliver sources.** The product is the edited project (`src/`) that compiles, with the multi-file structure and the author's macros kept; a PDF alone, a screenshot or a snippet is not a result. Keep the author's wording and numbers untouched: edit markup, not meaning, and list any edit that could change meaning in your final message.
- **Formulas.** `align` / `align*` with `&` at the relation, `\label` once per numbered line, `\eqref`, `\text{}` for words (amsmath), `\mathrm{}` / siunitx for units, `\operatorname` or `\sin` for functions, no `$$`, no `eqnarray`; symbols and numbering must agree with the text that cites them.
- **Tables and floats.** booktabs rules, column specification matching the rows (`table_columns`), `tabularx` / `p{}` widths or `\small` instead of `\resizebox`, `longtable` for tables that cross pages, `\caption` before `\label`, `[htbp]`, one caption per float. An overfull box of more than a few points is fixed in the layout, not by scaling the text.
- **References.** `\cite` keys exist in the `.bib` (the static check suggests near misses), no duplicate keys or labels, BibTeX / Biber really run (the passes show it; `biblatex` needs Biber, `natbib` / plain BibTeX needs bibtex), the build repeats until `\ref` and `\cite` stop changing.
- **Template.** Use the template's class and options; fill every front-matter field it uses (the `template` table says which ones the manuscript lacks: ask, never invent affiliations or e-mails); keep its bibliography style; do not carry over layout packages.
- **Repeatable build.** `build` records the engine and its version, package versions as the log prints them, the commands and passes, `SOURCE_DATE_EPOCH` / `FORCE_SOURCE_DATE`, and compares two clean builds; `repro/build.sh` replays them. Absolute paths (`/Users/...`, `C:\...`) and missing files are reported (`absolute_path`, `missing_graphic`).

## Exceptions

| Situation | Do |
|---|---|
| No TeX engine on the machine | `run` still reads the project and runs the static checks; `fix` refuses to apply unverified edits (use `--unverified` only if you must); `build` reports `not_compiled` and writes sources and `repro/`; say that nothing was compiled |
| Class / package not installed | the brief says `missing_file ... package|class`; keep the content, report it, `tlmgr install <name>` is for the user's machine |
| Biber missing / backend mismatch | the build report says which tool was missing; switch to `backend=bibtex` only if the task allows, else report |
| Chinese / Unicode text | XeLaTeX or LuaLaTeX with ctex / fontspec (detected from the packages; named in the task wins); fonts missing → the `missing_glyph` warning is listed |
| Several `\documentclass` files | the one nobody `\input`s is the main; override with `--main` |
| Endless loop / very slow package | each pass has a timeout (120 s); the pass is reported as timed out |
| Project arrives as a zip | unpacked safely (paths outside the folder are refused) |
| The compile is fine but the PDF looks wrong | the log cannot see layout: open the PDF; the `overfull` list and `float_too_large` warnings are the hints |

More: `references/diagnostics.md` (every code of the log reader and the static checks, with the measured behaviour), `references/workflow.md` (edit loop, template adaptation, repeat build), `examples/` (an invented project with ten defects: run, safe fixes, manual edits, final build). Example outputs are examples, not results of any evaluation case.
