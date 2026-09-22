all: wapp_dam_clearing.pdf
wapp_dam_clearing.pdf: wapp_dam_clearing.tex references.bib
	pdflatex -interaction=nonstopmode wapp_dam_clearing.tex >/dev/null
	bibtex wapp_dam_clearing >/dev/null || true
	pdflatex -interaction=nonstopmode wapp_dam_clearing.tex >/dev/null
	pdflatex -interaction=nonstopmode wapp_dam_clearing.tex >/dev/null
clean:
	rm -f *.aux *.bbl *.blg *.log *.out *.toc
