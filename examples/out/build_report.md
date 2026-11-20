# Build report

- status: success
- main: main.tex | engine: pdflatex
- PDF: main.pdf (sha256 808876d31b368168)
- reproducible: {"checked": true, "same_pdf_bytes": true, "hash_1": "808876d31b368168c6ced720ccbe3cfa1df9d23cbadc6826eeaefd257c9ad5f2", "hash_2": "808876d31b368168c6ced720ccbe3cfa1df9d23cbadc6826eeaefd257c9ad5f2", "note": "two clean builds with SOURCE_DATE_EPOCH / FORCE_SOURCE_DATE"}

## Environment
```
{
 "engine": "pdflatex",
 "tex_versions": {
  "pdflatex": "pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026)",
  "xelatex": "XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026)",
  "lualatex": "This is LuaHBTeX, Version 1.24.0 (TeX Live 2026)",
  "bibtex": "BibTeX 0.99e (TeX Live 2026)"
 },
 "packages": {
  "article": "2025/01/22 1.4n",
  "size10.clo": "2025/01/22 1.4n",
  "inputenc": "2024/02/08 1.3d",
  "amsmath": "2026/05/19 2.18d",
  "amstext": "2024/11/17 2.01",
  "amsgen.sty": "1999/11/30 2.0",
  "amsbsy": "1999/11/29 1.2d",
  "amsopn": "2022/04/08 2.04",
  "booktabs": "2020/01/12 1.61803398",
  "hyperref": "2026-06-17 7.01r",
  "iftex": "2024/12/12 1.0g",
  "keyval": "2026-05-17 1.15",
  "kvsetkeys": "2022-10-05 1.19",
  "kvdefinekeys": "2019-12-19 1.6",
  "pdfescape": "2019/12/09 1.15",
  "ltxcmds": "2023-12-04 1.26",
  "pdftexcmds": "2020-06-27 0.33",
  "infwarerr": "2019/12/03 1.5",
  "hycolor": "2020-01-27 1.10",
  "nameref": "2026-01-29 2.58",
  "refcount": "2019/12/15 3.6",
  "gettitlestring": "2019/12/15 1.6",
  "kvoptions": "2022-06-15 3.15",
  "etoolbox": "2025/10/02 2.5m",
  "stringenc": "2019/11/29 1.12",
  "pd1enc.def": "2026-06-17 7.01r",
  "intcalc": "2019/12/15 1.3",
  "puenc.def": "2026-06-17 7.01r",
  "url": "2013/09/16 er",
  "bitset": "2019/12/09 1.3",
  "bigintcalc": "2019/12/15 1.5",
  "hpdftex.def": "2026-06-17 7.01r",
  "rerunfilecheck": "2025-06-21 1.11",
  "uniquecounter": "2019/12/15 1.4",
  "l3backend-pdftex.def": "2026-09-09 L3"
 },
 "source_date_epoch": 1795152336,
 "bib_tool": "bibtex",
 "os": "darwin"
}
```

## Passes
- pass 1 `pdflatex -interaction=nonstopmode -file-line-error -synctex=0 main.tex` 0.2s errors 0 warnings 8 undefined 5 (changed: .aux,.out)
- pass 1 `bibtex main` 0.0s errors 0 warnings 1 undefined 0 (changed: .bbl)
- pass 2 `pdflatex -interaction=nonstopmode -file-line-error -synctex=0 main.tex` 0.2s errors 0 warnings 4 undefined 2 (changed: .aux,.bbl,.out)
- pass 3 `pdflatex -interaction=nonstopmode -file-line-error -synctex=0 main.tex` 0.2s errors 0 warnings 0 undefined 0

## Repeat the build
`sh repro/build.sh` (same commands and environment), or `make -C src -f ../repro/Makefile`, or latexmk with `repro/latexmkrc`.
