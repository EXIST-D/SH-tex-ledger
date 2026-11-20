#!/bin/sh
# Rebuild main.tex with the same engine, passes and environment as the recorded build.
set -e
cd "$(dirname "$0")/src"
export SOURCE_DATE_EPOCH=1795152336 FORCE_SOURCE_DATE=1 TZ=UTC LC_ALL=C max_print_line=10000
pdflatex -interaction=nonstopmode -file-line-error -synctex=0 main.tex
bibtex main
pdflatex -interaction=nonstopmode -file-line-error -synctex=0 main.tex
pdflatex -interaction=nonstopmode -file-line-error -synctex=0 main.tex
