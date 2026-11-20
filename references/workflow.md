# Workflow details

## Layout of the output folder

```
/app/output/
  .work/src      the working copy you edit      .work/orig   the pristine copy
  .work/state.json, baseline_diag.json
  brief.md       what `run` printed
  (after build)
  src/           delivered sources (clean: no aux/log/pdf)
  main.pdf       the PDF of the last clean build
  build_report.md/json   engine, package versions, passes, commands, hashes
  changes.md     unified diff original -> delivered, with the verified fixes
  diagnostics.json  root causes before and after
  repro/build.sh, Makefile, latexmkrc
  review_checklist.md
  result.json
```

## Edit loop

1. `run` → read `brief.md` (root causes first, warnings, static findings).
2. Fix one root cause at a time in `.work/src`; `check .work` after each (fixed / new / remaining are matched by `(code, file, message)`, line numbers are ignored so a shifted line is not "new").
3. When only mechanical issues remain: `fix .work --safe`.
4. When `check` shows 0 errors, 0 undefined references: `build`.

If the number of errors goes up after an edit, undo it: the new error is almost always a consequence of your change, not a new problem.

## Engines and bibliography

- Engine detection order: task wording, `%!TEX program = xelatex`, `fontspec` / `ctex` / `xeCJK` / `unicode-math` → xelatex, otherwise pdflatex. `--engine` overrides.
- BibTeX runs when the `.aux` has `\bibdata` and `\citation`; Biber when a `.bcf` exists (`biblatex`). A missing tool is an error in the build report, not a silent skip.
- Passes repeat (max 6) until the hashes of aux / toc / out / bbl stop changing and the log no longer asks for a rerun. `converged: false` means the document does not stabilise (an oscillating reference, usually page numbers in a label).

## Template adaptation

`template W --template DIR` prints a table (title, authors, abstract, keywords, class, packages, layout packages) for the manuscript and the template and lists what the manuscript lacks. `adapt` writes the manuscript's body, title, abstract and keywords into the template's main file; **authors and affiliations are not mapped** (formats differ: `\IEEEauthorblockN`, `\author{}\affil{}`, ...); fill them from the manuscript by hand and never invent missing ones. Then `use W` and `check`. Only the template's files are used, never downloaded.

## Repeat build

`build` cleans the folder, compiles twice from scratch with the same `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE=1`, and compares PDF bytes. `same_pdf_bytes: false` appears when a package embeds the time or a random id; the note says which hash differed. `repro/build.sh` replays the exact commands; `latexmkrc` and `Makefile` give the same for latexmk users.

## No TeX installed

`TX_NO_TEX=1` (or no engine found) → `run` prints only static findings, `fix --safe` refuses (nothing can verify an edit; `--unverified` overrides and the change log says so), `build` writes `status: not_compiled`, sources and `repro/`. Never describe such output as compiled.

## Contract fields

`result.json` is derived from `output_contract` in `case.json`. Filled automatically: status, main file, PDF name, files, change list (with diffs), diagnostics counts, environment, reproducibility. Anything else (a free-text summary, a list of what the author must decide) is `null` until you pass it in `answers.json`; `_meta.unfilled_fields` and the `UNFILLED` console lines say which.
