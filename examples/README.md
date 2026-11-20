# Examples (invented project; not results of any evaluation case)

| path | what |
|---|---|
| `paper/` | an INVENTED small LaTeX project (main.tex, sec/intro.tex, sec/method.tex, refs.bib) with ten problems: a mistyped `\ref`, `$$..$$`, `{\bf ..}`, an unescaped `_`, `[h]`, `\label` before `\caption`, an unclosed `\caption{`, booktabs commands without the package, a table row with an extra column, `hyperref` loaded before `amsmath` |
| `run.txt` | the real transcript of `tx.py` on it: `run` (root causes: one unclosed brace in `sec/method.tex` is reported at `main.tex` and linked back to its source line), `fix --safe` (kept / reverted rules), `check`, the manual edits, `fix --safe` again, `check`, `build` |
| `manual_edits.txt` | the four edits made by hand between the two `fix` rounds (tab-separated: file, old, new) |
| `out/` | what `build` delivered: `result.json`, `build_report.md`, `changes.md` (diffs), `review_checklist.md`, `brief.md`, `repro/` (the PDF and the clean sources are left out here to keep the folder text-only) |

Regenerate with `python3 dev/make_examples.py` (needs TeX; paths are scrubbed to `<dir>`). Note the order the transcript shows: while the unclosed brace dominates the log, a rule that depends on a clean compile (`label_after_caption`) is reverted; after the structural edits it is kept.
