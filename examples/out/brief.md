# Build brief (generated)

## Task
- engine named in the task: none | template named: none
- no task text

## Project
- main: main.tex | files: main.tex, sec/intro.tex, sec/method.tex | bibliographies: refs.bib
- engine: pdflatex (default)
- missing inputs: none
- TeX on this machine: pdflatex (pdfTeX 3.141592653-2.6-1.40.29), xelatex (XeTeX 3.141592653-2.6-0.999998), lualatex (This is LuaHBTeX, Version 1.24.0), bibtex (BibTeX 0.99e)

## Baseline build
- {"status": "failed", "engine": "pdflatex", "errors": 10, "warnings": 4, "badboxes": 0, "undefined": 3, "passes": 3, "converged": true, "bib_tool": "bibtex", "bib_errors": 0, "pdf": false}
  - pass 1: `pdflatex -interaction=nonstopmode -file-line-error -synctex=` 0.2s errors 10 warnings 6 undefined 4 rerun requested changed .aux,.out
  - pass 1: `bibtex main` 0.0s errors 0 warnings 0 undefined 0 changed .bbl
  - pass 2: `pdflatex -interaction=nonstopmode -file-line-error -synctex=` 0.1s errors 10 warnings 6 undefined 4 rerun requested changed .aux,.bbl,.out
  - pass 3: `pdflatex -interaction=nonstopmode -file-line-error -synctex=` 0.1s errors 10 warnings 4 undefined 3

## Root causes (4; errors that only follow another are folded under it)
1. [missing_dollar] Missing $ inserted. at sec/method.tex:2 - 4 later error(s) are consequences
   likely starts at: sec/method.tex:2 (an underscore outside math mode ("Data are stored in results_final.csv)
   fix: math mode needed: a math symbol (_, ^, \alpha ...) outside $...$, or an unescaped underscore in text (write \_ ), or $ unbalanced
      1| \section{Method}\label{sec:method}
      2| Data are stored in results_final.csv. Table~\ref{tab:main} lists the houses.
      3| \begin{table}[h]
2. [float_in_box] LaTeX Error: Not in outer par mode. at sec/method.tex:3
      2| Data are stored in results_final.csv. Table~\ref{tab:main} lists the houses.
      3| \begin{table}[h]
      4| \centering
3. [dimension_error] Missing number, treated as zero. at sec/method.tex:3
      2| Data are stored in results_final.csv. Table~\ref{tab:main} lists the houses.
      3| \begin{table}[h]
      4| \centering
4. [file_ended] File ended while scanning use of \@xdblarg. at main.tex:10
   likely starts at: sec/method.tex:6 (a { is never closed (near "\caption{Cooling energy saving by"))
   fix: an argument or brace was never closed: find the last \command{ whose } is missing before this point (the static check lists unbalanced braces per file)
      9| \input{sec/intro}
     10| \input{sec/method}
     11| \bibliographystyle{plain}

## Warnings: {'undefined_ref': 3, 'undefined_refs_summary': 1}
- sec/intro.tex:3 LaTeX Warning: Reference `sec:methods' on page 1 undefined on input line 3.
- sec/intro.tex:5 LaTeX Warning: Reference `eq:loss' on page 1 undefined on input line 5.
- sec/method.tex:2 LaTeX Warning: Reference `tab:main' on page 1 undefined on input line 2.

## Static checks (no TeX needed): 5 errors, 4 warnings, 5 notes
- error sec/intro.tex:3 [undefined_ref] \ref to label "sec:methods" which no \label defines -> did you mean "sec:method"?
- error sec/method.tex:2 [underscore_in_text] an underscore outside math mode ("Data are stored in results_final.csv. Table~  lists the hous") -> write \_ (or put the name in \texttt{...\_...}, or use \url / \path for names an
- error sec/method.tex:5 [label_before_caption] \label comes before \caption: \ref will show the section number instead of the figure / table number -> move \label after \caption
- error sec/method.tex:6 [unclosed_brace] a { is never closed (near "\caption{Cooling energy saving by") -> add the missing }: TeX will report this far from here ("File ended while scannin
- error sec/method.tex:9 [table_columns] this row has 4 column(s) but the column specification {lcc} defines 3 -> add / remove & or fix the specification (\multicolumn counts as its span)
- warn main.tex:None [command_needs_package] \toprule is used but booktabs is not loaded (the compile log decides whether the class provides it) -> \usepackage{booktabs}
- warn main.tex:None [command_needs_package] \bottomrule is used but booktabs is not loaded (the compile log decides whether the class provides it) -> \usepackage{booktabs}
- warn main.tex:4 [hyperref_not_last] package amsmath is loaded after hyperref: hyperref should come last (except cleveref, bookmark ...) to avoid broken link -> move \usepackage{hyperref} below the other packages
- warn sec/intro.tex:4 [display_dollars] $$ ... $$ is a TeX primitive: it breaks spacing and amsmath numbering -> use \[ ... \] or an equation environment
