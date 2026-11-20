# Diagnostic codes

Two independent sources: the **log reader** (`texlog.py`, needs a compile) and the **static checks** (`texsrc.py`, read the sources only). The brief shows both; a problem seen by both is the most reliable.

## 1. Log reader (kind = error | warning)

The log is read with `-file-line-error`, `max_print_line=10000` (no wrapped lines). The file stack is rebuilt from the parentheses, `l.N` gives the line and the context TeX printed.

| code | what TeX said | usual cause | what to do |
|---|---|---|---|
| `undefined_cs` | Undefined control sequence | package not loaded / typo / macro defined later | the brief groups them by command and names the package (`CMD_PACKAGES`); add the package or fix the typo |
| `undefined_env` | Environment X undefined | package missing | same, for environments |
| `missing_file` | File `x.sty` / `x.cls` / `x.png` not found | package not installed, wrong path, graphic missing | keep the content; report; `\graphicspath`, `tlmgr install` on the user's machine |
| `missing_dollar` | Missing $ inserted | `_`, `^` or a math command in text, unbalanced `$` | escape `\_`, put math in `$..$` |
| `runaway` | Runaway argument? | an argument was never closed | look at `likely starts at` (static unclosed brace) |
| `file_ended` | File ended while scanning use of ... | `{` never closed, often in an included file | same |
| `env_mismatch` | `\begin{a}` ended by `\end{b}` | wrong or missing `\end` | fix the pair at the reported lines |
| `extra_brace` / `missing_brace` | Too many }'s / Missing } inserted | brace imbalance | find the unmatched brace in the static list |
| `paragraph_ended` | Paragraph ended before ... was complete | empty line inside an argument | remove the blank line |
| `float_in_box` | Not in outer par mode | float inside a box, or a consequence of an earlier error | fix the earlier error first |
| `dimension_error` | Missing number, treated as zero | broken optional argument / consequence | usually a cascade |
| `extra_alignment` / `alignment_tab` | Extra alignment tab / Misplaced alignment tab character & | too many columns in a row; `&` in text | check the column spec, escape `\&` |
| `lonely_item`, `missing_item` | \item outside a list | list environment missing | |
| `bad_math_env`, `double_script`, `parameter_error`, `misplaced_noalign`, `preamble_only`, `option_clash`, `already_defined`, `package_error`, `unicode`, `fatal` | the matching TeX / package messages | | the message text is kept verbatim |
| `float_overflow`, `float_too_large`, `float_specifier`, `overfull_like` | layout warnings | figure / table too large, bad placement letters | fix the layout, do not scale text |
| `undefined_ref`, `undefined_cite` (+ `_summary`) | reference / citation undefined | typo, missing `.bib` entry, bibliography not run | see static `undefined_ref` / `undefined_cite` |
| `multiply_defined`, `empty_bibliography`, `rerun`, `missing_glyph`, `pdf_string`, `pdf_reference`, `font_shape`, `unused_option` | package warnings | | `missing_glyph` = the font lacks a character (XeLaTeX / LuaLaTeX) |

Bad boxes are listed with line ranges and the size in points; only large overfull boxes appear in the brief.

### Cascades

`GLOBAL_CORRUPTING` = {runaway, file_ended, env_mismatch, extra_brace, missing_brace, paragraph_ended}: after one of them, later errors that are not independent are folded under it (`+N consequences`). `INDEPENDENT` = {undefined_cs, missing_file, undefined_env, bibtex errors, option_clash, already_defined, package_error, preamble_only, unicode, fatal} stay separate roots. A local error (missing `$`) folds only same-file follow-ups. Core commands reported "undefined" (`\begin`, `\caption`, `\label` ...) are consequences of a broken state and are not root causes. If the static check found the unclosed brace, the runaway error says `likely starts at: file:line`, and errors TeX printed between that place and the point where it gave up are folded under it.

Folding is a heuristic: when a "consequence" looks independent, run `diag --all`.

## 2. Static checks (`lint`; no TeX needed)

| group | codes |
|---|---|
| structure | `unclosed_brace`, `extra_brace`, `env_mismatch`, `env_unclosed`, `odd_dollar`, `display_dollars` |
| text mode | `underscore_in_text`, `hash_in_text`, `ampersand_in_text`, `percent_after_number` |
| references | `undefined_ref`, `duplicate_label`, `unused_label`, `undefined_cite`, `bib_duplicate_key`, `bib_missing_field` |
| files | `missing_graphic`, `missing_input`, `absolute_path` |
| tables / floats | `table_columns` (counts `&` per row incl. `\multicolumn`), `float_no_caption`, `label_before_caption`, `float_h_only`, scaling hacks |
| packages | `package_twice`, `hyperref_not_last`, `package_conflict`, `engine_package`, `command_needs_package`, `env_needs_package`, `obsolete_*` (`eqnarray`, `\bf`, `\it`, `subfigure`, ...) |

Comments and verbatim-like environments are blanked before checking. `underscore_in_text` ignores `\verb`, `\url`, `\texttt` arguments, labels, citations, file names inside `\input` / `\includegraphics`. Findings are warnings unless TeX would certainly fail (`unclosed_brace`, `env_mismatch`, `undefined_ref` ...).

## 3. Safe fixes (`fix --safe`)

| rule | edit |
|---|---|
| `display_dollars` | `$$..$$` → `\[..\]` |
| `old_font_switches` | `{\bf x}` → `\textbf{x}` (also `\it`, `\tt`, `\sc`, `\sl`, `\rm`, `\sf`) |
| `label_after_caption` | `\label` moved after `\caption` in the same float |
| `float_placement` | `[h]` → `[htbp]` |
| `duplicate_package` | repeated `\usepackage` removed |
| `engine_packages` | `inputenc` / `fontenc` removed for XeLaTeX / LuaLaTeX |
| `hyperref_last` | `hyperref` moved after the other packages |
| `missing_package_<pkg>` | `\usepackage{pkg}` added when a command or environment needs it and the package is not loaded |

Every rule is applied alone, the project is recompiled, and the rule is **kept only if** `(errors, undefined refs/citations, bibliography errors)` is not worse. A rule that fails while a structural error dominates the log may pass after that error is fixed: run `fix --safe` again after the manual edits.

## 4. Measured behaviour (real TeX Live 2026, `dev/defects.py`)

20 defects injected one at a time into a clean project: log reader names the right problem 19/19 (the one defect that produces no log error is excluded), at the right file:line 17/19; static checks find 17/17 (the three that only the compiler can see are excluded) and place 17/17; reading only the first error points at the defect's own line 10/19; either route finds all 20. The rules were tuned on this corpus: these numbers are an upper bound, not a forecast.
