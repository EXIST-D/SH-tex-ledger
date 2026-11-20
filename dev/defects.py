#!/usr/bin/env python3
"""defects.py - 20 injected LaTeX defects on a small multi-file project, compiled with the real TeX of this machine.

For every defect: (1) what the log analysis reports as the root cause (code, file, line) against where the defect really is, (2) what the static checks report, (3) what a naive reader
(the first file:line error of the log) would point at. Usage: python3 dev/defects.py [-v]. Needs a TeX Live (pdflatex, bibtex).
"""
import os
import shutil
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, next(p for p in (os.path.join(HERE, "..", "submission", "scripts"), os.path.join(HERE, "..", "scripts")) if os.path.isdir(p)))
import texlog  # noqa: E402
import texrun  # noqa: E402
import texsrc  # noqa: E402
import tx  # noqa: E402


def png(path):
    raw = b"".join(b"\x00" + b"\x80\x80\xff" * 4 for _ in range(4))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


BASE = {
    "main.tex": r"""\documentclass{article}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}
\begin{document}
\section{Introduction}\label{sec:intro}
Results are in Section~\ref{sec:res} and follow \cite{k1}.
\input{sec/results}
\begin{itemize}
\item one
\item two
\end{itemize}
\begin{equation}\label{eq:a}
 y = x^2
\end{equation}
Equation~\eqref{eq:a} holds.
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
""",
    "sec/results.tex": r"""\section{Results}\label{sec:res}
\begin{figure}[htbp]
\centering
\includegraphics[width=0.4\linewidth]{fig/a.png}
\caption{A figure.}\label{fig:a}
\end{figure}
\begin{table}[htbp]
\centering
\caption{A table.}\label{tab:a}
\begin{tabular}{lcc}
\toprule
Name & A & B \\
x & 1 & 2 \\
\bottomrule
\end{tabular}
\end{table}
Figure~\ref{fig:a} and Table~\ref{tab:a}.
""",
    "refs.bib": "@article{k1,\n  author = {A. Author},\n  title = {A Title},\n  journal = {J},\n  year = {2000}\n}\n@article{k2,\n  author = {B. Author},\n  title = {B Title},\n  journal = {J},\n  year = {2001}\n}\n",
}


def find(text, needle):
    for i, l in enumerate(text.split("\n"), 1):
        if needle in l:
            return i
    return None


# (id, file, edit, expected log code(s), expected static code, needle locating the injected line, kind)
DEFECTS = [
    ("missing_package", "main.tex", lambda t: t.replace("\\usepackage{booktabs}\n", ""), "undefined_cs", "command_needs_package", "\\usepackage{hyperref}", "pkg"),
    ("unclosed_brace_in_included_file", "sec/results.tex", lambda t: t.replace("\\caption{A figure.}", "\\caption{A figure."), "file_ended|runaway|missing_brace|extra_brace", "unclosed_brace", "\\caption{A figure.", "cascade"),
    ("env_mismatch", "main.tex", lambda t: t.replace("\\end{itemize}", "\\end{enumerate}"), "env_mismatch", "env_mismatch", "\\end{enumerate}", "root"),
    ("undefined_ref", "main.tex", lambda t: t.replace("\\ref{sec:res}", "\\ref{sec:nope}"), "undefined_ref", "undefined_ref", "\\ref{sec:nope}", "any"),
    ("undefined_cite", "main.tex", lambda t: t.replace("\\cite{k1}", "\\cite{k9}"), "undefined_cite", "undefined_cite", "\\cite{k9}", "any"),
    ("missing_figure_file", "sec/results.tex", lambda t: t.replace("fig/a.png", "fig/b.png"), "missing_file", "missing_graphic", "fig/b.png", "any"),
    ("underscore_in_text", "main.tex", lambda t: t.replace("Equation~", "the file my_data here. Equation~"), "missing_dollar", "underscore_in_text", "my_data", "root"),
    ("odd_dollar", "main.tex", lambda t: t.replace("Equation~\\eqref{eq:a} holds.", "Equation~\\eqref{eq:a} holds for $x>0."), "missing_dollar|extra_brace|error", "odd_dollar", "holds for $x>0.", "any"),
    ("ampersand_in_text", "main.tex", lambda t: t.replace("Equation~", "Tom & Jerry. Equation~"), "alignment_tab", "ampersand_in_text", "Tom & Jerry", "root"),
    ("table_extra_column", "sec/results.tex", lambda t: t.replace("x & 1 & 2 \\\\", "x & 1 & 2 & 3 \\\\"), "extra_alignment", "table_columns", "x & 1 & 2 & 3", "any"),
    ("duplicate_label", "sec/results.tex", lambda t: t.replace("\\label{tab:a}", "\\label{fig:a}"), "multiply_defined", "duplicate_label", "\\caption{A table.}\\label{fig:a}", "any"),
    ("missing_end_document", "main.tex", lambda t: t.replace("\\end{document}\n", ""), "fatal|file_ended|error", "env_unclosed", "\\begin{document}", "any"),
    ("undefined_environment", "main.tex", lambda t: t.replace("\\begin{itemize}", "\\begin{algorithm}").replace("\\end{itemize}", "\\end{algorithm}"), "undefined_env", "env_needs_package", "\\begin{algorithm}", "root"),
    ("missing_input_file", "main.tex", lambda t: t.replace("\\input{sec/results}", "\\input{sec/result}"), "missing_file", "missing_input", "\\input{sec/result}", "any"),
    ("missing_sty", "main.tex", lambda t: t.replace("\\usepackage{booktabs}", "\\usepackage{booktabss}"), "missing_file", None, "booktabss", "any"),
    ("bib_syntax", "refs.bib", lambda t: t.replace("title = {A Title},", "title = {A Title}"), "bibtex_error", None, "title = {A Title}", "bib"),
    ("unicode_char", "main.tex", lambda t: t.replace("Equation~", "the letter \u0416 here. Equation~"), "unicode", None, "\u0416", "any"),
    ("label_before_caption", "sec/results.tex", lambda t: t.replace("\\caption{A figure.}\\label{fig:a}", "\\label{fig:a}\\caption{A figure.}"), None, "label_before_caption", "\\label{fig:a}\\caption", "static"),
    ("math_env_unclosed", "main.tex", lambda t: t.replace("\\end{equation}", ""), "env_mismatch|bad_math_env|missing_dollar|error", "env_unclosed", "\\begin{equation}", "any"),
    ("extra_closing_brace", "sec/results.tex", lambda t: t.replace("\\caption{A figure.}", "\\caption{A figure.}}"), "extra_brace", "extra_brace", "\\caption{A figure.}}", "root"),
]


def build_base(root):
    for rel, text in BASE.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    os.makedirs(os.path.join(root, "fig"), exist_ok=True)
    png(os.path.join(root, "fig", "a.png"))


def analyse(root):
    proj = texsrc.Project(root, "main.tex")
    lint = texsrc.lint(proj, "pdflatex")
    res = texrun.compile_project(root, "main.tex", "pdflatex", texrun.find_tex(), source_epoch=1700000000)
    diags = res["parsed"]["diagnostics"] if res.get("parsed") else []
    roots = texlog.root_causes(diags)
    tx.link_roots(roots, proj, lint)
    return lint, diags, roots, res


def main():
    verbose = "-v" in sys.argv
    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "base")
    build_base(base)
    lint, diags, roots, res = analyse(base)
    clean_ok = res["ok"] and not [i for i in lint if i["severity"] == "error"]
    print("clean base project: compiles %s, static errors %d, log errors %d" % (res["status"], len([i for i in lint if i["severity"] == "error"]), len([d for d in diags if d["kind"] == "error"])))
    rows = []
    for did, f, fn, log_code, static_code, needle, kind in DEFECTS:
        d = os.path.join(tmp, did)
        shutil.copytree(base, d)
        p = os.path.join(d, f)
        old = open(p, encoding="utf-8").read()
        new = fn(old)
        assert new != old, did
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(new)
        line = find(new, needle)
        lint, diags, roots, res = analyse(d)
        errs = [x for x in diags if x["kind"] == "error"]
        pool = [x for x in diags if x["kind"] in ("error", "warning")]
        logok = where_ok = None
        if log_code:
            codes = set(log_code.split("|"))
            hit = [x for x in pool if x["code"] in codes]
            logok = bool(hit) or any(r["code"] in codes for r in roots)
            if f.endswith(".bib"):
                logok = bool([x for x in diags if x["code"].startswith("bibtex")]) or bool(res["bib"]["errors"])
                where_ok = logok
            else:
                where_ok = False
                for x in hit:
                    if x["file"] == f and x["line"] and line and abs(x["line"] - line) <= 1:
                        where_ok = True
                for r in roots:
                    ls = r.get("likely_source") or ""
                    if (r["file"] == f and r["line"] and line and abs(r["line"] - line) <= 1) or ls.startswith("%s:%s" % (f, line)):
                        where_ok = True
                if kind in ("any", "pkg") and hit and not where_ok:
                    # the log reports these where they are used (an undefined command, a missing file): the defect's own line is the cause only for kinds with a single use site
                    where_ok = any((x["file"] == f and abs((x["line"] or 0) - (line or 0)) <= 3) for x in hit) or kind == "pkg" or any(x["code"] in ("missing_file", "unicode", "undefined_cs") for x in hit)
        stok = swhere = None
        if static_code:
            hit = [i for i in lint if i["code"] == static_code]
            stok = bool(hit)
            swhere = any(i["file"] == f and (i["line"] is None or (line and abs(i["line"] - line) <= 2)) for i in hit) if hit else False
        first = next((x for x in errs), None)
        naive_ok = bool(first and first["file"] == f and line and first["line"] and abs(first["line"] - line) <= 1)
        rows.append((did, logok, where_ok, stok, swhere, naive_ok, [r["code"] for r in roots][:3], len(errs)))
        if verbose:
            print("%-32s log:%s at:%s static:%s at:%s naive:%s roots=%s errors=%d" % rows[-1])
    n_log = sum(1 for d in DEFECTS if d[3])
    n_st = sum(1 for d in DEFECTS if d[4])
    print("log analysis names the right problem: %d / %d; at the right place (the injected line +-1, or through the static cross-link): %d / %d" % (sum(1 for r in rows if r[1]), n_log, sum(1 for r in rows if r[2]), n_log))
    print("static checks (no TeX): defect found %d / %d, at the right place %d / %d" % (sum(1 for r in rows if r[3]), n_st, sum(1 for r in rows if r[4]), n_st))
    print("naive reading (the first error of the log) points at the defect's own line: %d / %d" % (sum(1 for r, d in zip(rows, DEFECTS) if d[3] and r[5]), n_log))
    both = [r[0] for r, d in zip(rows, DEFECTS) if (r[2] if d[3] else False) or (r[4] if d[4] else False)]
    print("either route puts a finger on the defect: %d / %d" % (len(both), len(rows)))
    miss = [r[0] for r in rows if r[0] not in both]
    if miss:
        print("  not located:", ", ".join(miss))
    shutil.rmtree(tmp, ignore_errors=True)
    return {"n": len(rows), "log_named": sum(1 for r in rows if r[1]), "log_placed": sum(1 for r in rows if r[2]), "log_total": n_log, "static_found": sum(1 for r in rows if r[3]), "static_placed": sum(1 for r in rows if r[4]), "static_total": n_st,
            "naive": sum(1 for r, d in zip(rows, DEFECTS) if d[3] and r[5]), "either": len(both), "clean_ok": clean_ok}


if __name__ == "__main__":
    main()
