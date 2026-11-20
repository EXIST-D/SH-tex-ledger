# make -C src (needs latexmk)
MAIN=main
ENGINE=-pdf
all:
	SOURCE_DATE_EPOCH=1795152336 FORCE_SOURCE_DATE=1 latexmk $(ENGINE) -interaction=nonstopmode -file-line-error $(MAIN).tex
clean:
	latexmk -C $(MAIN).tex
