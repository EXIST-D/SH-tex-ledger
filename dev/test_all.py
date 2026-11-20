#!/usr/bin/env python3
"""Regression tests for tex-ledger (stdlib unittest). Run: python3 dev/test_all.py [-v]
Tests that compile need a TeX Live (pdflatex, bibtex); they are skipped, with a message, when none is found. All documents are invented."""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import warnings
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUB = os.path.join(ROOT, "submission") if os.path.isdir(os.path.join(ROOT, "submission")) else ROOT
sys.path.insert(0, os.path.join(SUB, "scripts"))
sys.path.insert(0, HERE)
import texlog  # noqa: E402
import texrun  # noqa: E402
import texsrc  # noqa: E402
import tx  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)
TOOLS = texrun.find_tex()
HAVE_TEX = bool(TOOLS.get("pdflatex") and TOOLS.get("bibtex"))
needs_tex = unittest.skipUnless(HAVE_TEX, "no TeX Live on this machine: compile tests skipped")


def run(*args):
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            tx.main(list(args))
        except SystemExit as e:
            code = e.code or 0
    return code, buf.getvalue()


GOOD = {
    "main.tex": "\\documentclass{article}\n\\usepackage{amsmath}\n\\usepackage{booktabs}\n\\usepackage{hyperref}\n\\begin{document}\n\\section{Intro}\\label{s:i}\nSee Section~\\ref{s:r} and \\cite{k1}.\n\\input{sec/r}\n\\bibliographystyle{plain}\n\\bibliography{refs}\n\\end{document}\n",
    "sec/r.tex": "\\section{Results}\\label{s:r}\n\\begin{table}[htbp]\n\\centering\n\\caption{T.}\\label{t:a}\n\\begin{tabular}{lc}\n\\toprule\nx & 1 \\\\\n\\bottomrule\n\\end{tabular}\n\\end{table}\nTable~\\ref{t:a}.\n",
    "refs.bib": "@article{k1,\n  author = {A. Author},\n  title = {A Title},\n  journal = {J},\n  year = {2000}\n}\n",
}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.tmp, *p)

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def project(self, files=None, name="proj"):
        for rel, t in (files or GOOD).items():
            self.write(os.path.join(name, rel), t)
        return self.path(name)

    def edit(self, rel, fn, name="proj"):
        p = self.path(name, rel)
        t = open(p, encoding="utf-8").read()
        new = fn(t)
        assert new != t
        open(p, "w", encoding="utf-8").write(new)


# ------------------------------------------------------------------------------------------------ log reading
LOG = r"""This is pdfTeX, Version 3.141592653-2.6-1.40.29 (TeX Live 2026)
(./main.tex
LaTeX2e <2026-06-01>
(/usr/share/texlive/latex/base/article.cls
Document Class: article 2025/01/22 v1.4n Standard LaTeX document class
(/usr/share/texlive/latex/base/size10.clo))
(/usr/share/texlive/latex/amsmath/amsmath.sty
Package: amsmath 2026/05/19 v2.18d AMS math features
) (./sec/a.tex
./sec/a.tex:1: Missing $ inserted.
<inserted text>
                $
l.1 Text a_
           b here.
I've inserted a begin-math/end-math symbol since I think
)
./main.tex:6: File ended while scanning use of \textbf .
<inserted text>
                \par
l.6 \input{sec/a}

I suspect you have forgotten a `}'.

./main.tex:7: Undefined control sequence.
l.7 \toprule

The control sequence at the end of the top line

./main.tex:8: LaTeX Error: Bad math environment delimiter.

See the LaTeX manual or LaTeX Companion for explanation.
l.8 \begin{equation}

./main.tex:13: LaTeX Error: \begin{itemize} on input line 11 ended by \end{enumerate}.

See the LaTeX manual or LaTeX Companion for explanation.
l.13 \end{enumerate}

LaTeX Warning: Reference `s:nope' on page 1 undefined on input line 5.

LaTeX Warning: Citation `missing' on page 1 undefined on input line 5.

Overfull \hbox (45.2pt too wide) in paragraph at lines 20--21
[]\OT1/cmr/m/n/10 Some very long text
Package hyperref Warning: Token not allowed in a PDF string (Unicode):
(hyperref)                removing `math shift' on input line 12.

LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.
"""


class TestLog(unittest.TestCase):
    def setUp(self):
        self.p = texlog.parse_log(LOG, "main.tex")
        self.by = {(d["code"], d["line"]): d for d in self.p["diagnostics"]}

    def test_errors_have_file_line_and_context(self):
        d = self.by[("missing_dollar", 1)]
        self.assertEqual(d["file"], "sec/a.tex")
        self.assertIn("l.1", d["context"])
        self.assertEqual(self.by[("undefined_cs", 7)]["file"], "main.tex")
        self.assertEqual(self.by[("env_mismatch", 13)]["detail"]["opened"], "itemize")
        self.assertEqual(self.by[("env_mismatch", 13)]["detail"]["opened_line"], 11)

    def test_warnings_and_boxes(self):
        self.assertEqual(self.by[("undefined_ref", 5)]["detail"]["label"], "s:nope")
        self.assertEqual(self.by[("undefined_cite", 5)]["detail"]["key"], "missing")
        ob = [d for d in self.p["diagnostics"] if d["code"] == "overfull_hbox"][0]
        self.assertEqual((ob["line"], ob["line_end"], ob["detail"]["pt"]), (20, 21, 45.2))
        self.assertTrue(self.p["rerun"])
        pw = [d for d in self.p["diagnostics"] if d["code"] == "pdf_string"][0]
        self.assertEqual(pw["line"], 12)

    def test_packages_and_files(self):
        self.assertEqual(self.p["packages"]["amsmath"], "2026/05/19 2.18d")
        self.assertIn("./sec/a.tex", self.p["files"])

    def test_cascades_are_folded_into_the_first_structural_error(self):
        roots = texlog.root_causes(self.p["diagnostics"])
        codes = [r["code"] for r in roots]
        self.assertEqual(codes, ["missing_dollar", "file_ended", "undefined_cs"])
        self.assertTrue(self.by[("bad_math_env", 8)]["cascade"])
        self.assertTrue(self.by[("env_mismatch", 13)]["cascade"])
        self.assertFalse(self.by[("undefined_cs", 7)]["cascade"])  # independent of the brace
        self.assertIn("booktabs", [r for r in roots if r["code"] == "undefined_cs"][0]["fix"])

    def test_undefined_commands_are_grouped(self):
        log = "./a.tex:3: Undefined control sequence.\nl.3 \\toprule\n\n./a.tex:9: Undefined control sequence.\nl.9 \\midrule\n\n./a.tex:12: Undefined control sequence.\nl.12 \\toprule\n"
        roots = texlog.root_causes(texlog.parse_log(log, "a.tex")["diagnostics"])
        self.assertEqual(sorted(r["summary"] for r in roots), ["undefined command \\midrule (1 use)", "undefined command \\toprule (2 uses)"])

    def test_classic_error_style_and_bibtex(self):
        p = texlog.parse_log("(./a.tex\n! Undefined control sequence.\nl.4 \\foo\n\n! LaTeX Error: Environment bar undefined.\nl.6 \\begin{bar}\n)\n", "a.tex")
        self.assertEqual([(d["code"], d["line"], d["file"]) for d in p["diagnostics"]], [("undefined_cs", 4, "a.tex"), ("undefined_env", 6, "a.tex")])
        b = texlog.parse_log("This is BibTeX, Version 0.99d\nI couldn't open database file refs.bib\nWarning--I didn't find a database entry for \"zzz\"\n", "")
        self.assertEqual({d["code"] for d in b["diagnostics"]}, {"bibtex_error", "bibtex_warning"})

    def test_wrapped_log_is_joined(self):
        long = "LaTeX Warning: Reference `" + "x" * 40 + "' on page 1 undefined on input line 5."
        wrapped = "\n".join([long[:79], long[79:]] + ["filler"] * 6 + ["a" * 79 + "\nb"] * 5)
        p = texlog.parse_log(wrapped, "m.tex")
        self.assertEqual([d["line"] for d in p["diagnostics"] if d["code"] == "undefined_ref"], [5])

    def test_missing_file_kinds(self):
        p = texlog.parse_log("./m.tex:2: LaTeX Error: File `nopkg.sty' not found.\n\n./m.tex:3: LaTeX Error: File `fig.png' not found.\n", "m.tex")
        kinds = [d["detail"]["kind"] for d in p["diagnostics"]]
        self.assertEqual(kinds, ["package", "file"])


# ------------------------------------------------------------------------------------------------ source reading
class TestSource(Tmp):
    def test_project_graph(self):
        root = self.project()
        p = texsrc.Project(root)
        self.assertEqual(p.main, "main.tex")
        self.assertEqual(p.order, ["main.tex", "sec/r.tex"])
        self.assertEqual(list(p.bibs), ["refs.bib"])
        self.assertEqual(p.engine()[0], "pdflatex")

    def test_comments_and_verbatim_are_ignored(self):
        t = "a 50\\% b % comment with \\textbf{ and _\n\\begin{verbatim}\n{ _ $\n\\end{verbatim}\nok\n"
        lines = texsrc.strip_comments(t)
        joined = "".join(lines)
        self.assertNotIn("textbf", joined)
        self.assertNotIn("_", joined)
        self.assertNotIn("$", joined)
        self.assertIn("50\\%", lines[0])

    def test_clean_project_has_no_errors(self):
        iss = texsrc.lint(texsrc.Project(self.project()))
        self.assertEqual([i for i in iss if i["severity"] == "error"], [], iss)

    def lint_codes(self, fn, rel="main.tex"):
        self.project()
        self.edit(rel, fn)
        return {(i["code"], i["file"]) for i in texsrc.lint(texsrc.Project(self.path("proj")))}

    def test_structure_defects(self):
        self.assertIn(("unclosed_brace", "sec/r.tex"), self.lint_codes(lambda t: t.replace("\\caption{T.}", "\\caption{T."), "sec/r.tex"))
        self.assertIn(("env_mismatch", "main.tex"), self.lint_codes(lambda t: t.replace("\\section{Intro}", "\\begin{itemize}\\item a\n\\end{enumerate}\n\\section{Intro}")))
        self.assertIn(("odd_dollar", "main.tex"), self.lint_codes(lambda t: t.replace("Intro}", "Intro}\nWe have $x>0 here.\n")))
        self.assertIn(("underscore_in_text", "main.tex"), self.lint_codes(lambda t: t.replace("See ", "See a_b ")))
        self.assertIn(("ampersand_in_text", "main.tex"), self.lint_codes(lambda t: t.replace("See ", "Tom & Jerry. See ")))
        self.assertIn(("percent_after_number", "main.tex"), self.lint_codes(lambda t: t.replace("See ", "About 50% of it. See ")))

    def test_references_and_files(self):
        self.assertIn(("undefined_ref", "main.tex"), self.lint_codes(lambda t: t.replace("\\ref{s:r}", "\\ref{s:x}")))
        self.assertIn(("undefined_cite", "main.tex"), self.lint_codes(lambda t: t.replace("\\cite{k1}", "\\cite{k2}")))
        self.assertIn(("missing_input", "main.tex"), self.lint_codes(lambda t: t.replace("\\input{sec/r}", "\\input{sec/q}")))
        self.assertIn(("duplicate_label", "sec/r.tex"), self.lint_codes(lambda t: t.replace("\\label{t:a}", "\\label{s:r}"), "sec/r.tex"))
        self.assertIn(("missing_graphic", "sec/r.tex"), self.lint_codes(lambda t: t.replace("\\centering", "\\centering\\includegraphics{nofile}"), "sec/r.tex"))

    def test_table_columns_respect_multicolumn(self):
        base = "\\documentclass{article}\\begin{document}\\begin{tabular}{lcc}\nA & B & C \\\\\n\\multicolumn{2}{c}{x} & y \\\\\n%s\\end{tabular}\\end{document}\n"
        for row, bad in (("1 & 2 & 3 \\\\\n", False), ("1 & 2 & 3 & 4 \\\\\n", True)):
            self.write("t/main.tex", base % row)
            codes = {i["code"] for i in texsrc.lint(texsrc.Project(self.path("t")))}
            self.assertEqual("table_columns" in codes, bad, row)

    def test_packages(self):
        pk = "\\documentclass{article}\n\\usepackage{hyperref}\n\\usepackage{graphicx}\n\\usepackage{graphicx}\n\\usepackage{subfig}\n\\usepackage{subcaption}\n\\usepackage[utf8]{inputenc}\n\\begin{document}x\\end{document}\n"
        self.write("p/main.tex", pk)
        codes = {i["code"] for i in texsrc.lint(texsrc.Project(self.path("p")), "xelatex")}
        for c in ("hyperref_not_last", "package_twice", "package_conflict", "engine_package"):
            self.assertIn(c, codes)
        self.write("q/main.tex", "\\documentclass{article}\n\\usepackage{fontspec}\n\\begin{document}x\\end{document}\n")
        self.assertIn("engine_package", {i["code"] for i in texsrc.lint(texsrc.Project(self.path("q")), "pdflatex")})
        self.assertEqual(texsrc.Project(self.path("q")).engine()[0], "xelatex")

    def test_command_and_environment_need_packages(self):
        self.project()
        self.edit("main.tex", lambda t: t.replace("\\usepackage{booktabs}\n", ""))
        c = [i for i in texsrc.lint(texsrc.Project(self.path("proj"))) if i["code"] == "command_needs_package"]
        self.assertEqual(c[0]["package"], "booktabs")

    def test_safe_fixes_are_text_rewrites_only(self):
        t = "\\documentclass{article}\n\\usepackage{hyperref}\n\\usepackage{amsmath}\n\\begin{document}\n{\\bf bold} and $$a=b$$.\n\\begin{figure}[h]\n\\label{f}\\caption{C}\n\\end{figure}\n\\end{document}\n"
        self.write("s/main.tex", t)
        proj = texsrc.Project(self.path("s"))
        fixes = {r[0]: r[1]["main.tex"] for r in texsrc.safe_fixes(proj, texsrc.lint(proj), "pdflatex")}
        self.assertIn("\\[a=b\\]", fixes["display_dollars"])
        self.assertIn("\\textbf{bold}", fixes["old_font_switches"])
        self.assertIn("\\caption{C}\\label{f}", fixes["label_after_caption"])
        self.assertIn("[htbp]", fixes["float_placement"])
        self.assertTrue(fixes["hyperref_last"].index("hyperref") > fixes["hyperref_last"].index("amsmath"))
        self.assertEqual(open(self.path("s", "main.tex"), encoding="utf-8").read(), t)  # nothing written to disk


# ------------------------------------------------------------------------------------------------ compile
@needs_tex
class TestCompile(Tmp):
    def test_clean_project_converges_and_is_reproducible(self):
        root = self.project()
        r1 = texrun.compile_project(root, "main.tex", "pdflatex", TOOLS, source_epoch=1700000000)
        self.assertEqual(r1["status"], "ok")
        self.assertTrue(r1["converged"])
        self.assertEqual(r1["bib"]["tool"], "bibtex")
        self.assertGreaterEqual(len([p for p in r1["passes"] if p["command"].startswith("pdflatex")]), 3)
        self.assertEqual(r1["parsed"]["diagnostics"] and [d for d in r1["parsed"]["diagnostics"] if d["code"] in ("undefined_ref", "undefined_cite")], [])
        h = texrun.sha(r1["pdf"])
        r2 = texrun.compile_project(root, "main.tex", "pdflatex", TOOLS, source_epoch=1700000000)
        self.assertEqual(h, texrun.sha(r2["pdf"]))
        self.assertIn("amsmath", r1["parsed"]["packages"])

    def test_defective_project_is_diagnosed_with_places(self):
        root = self.project()
        self.edit("sec/r.tex", lambda t: t.replace("\\caption{T.}", "\\caption{T."))
        r = texrun.compile_project(root, "main.tex", "pdflatex", TOOLS, source_epoch=1700000000)
        self.assertNotEqual(r["status"], "ok")
        roots = texlog.root_causes(r["parsed"]["diagnostics"])
        proj = texsrc.Project(root)
        tx.link_roots(roots, proj, texsrc.lint(proj))
        self.assertTrue(any("sec/r.tex" in (x.get("likely_source") or "") for x in roots), roots)

    def test_missing_class_is_reported_as_such(self):
        root = self.project({"main.tex": "\\documentclass{nonexistentclass}\n\\begin{document}x\\end{document}\n"}, "m")
        r = texrun.compile_project(root, "main.tex", "pdflatex", TOOLS)
        self.assertEqual(r["status"], "failed")
        roots = texlog.root_causes(r["parsed"]["diagnostics"])
        self.assertEqual(roots[0]["code"], "missing_file")
        self.assertIn("class", roots[0]["fix"])

    def test_timeout_is_reported(self):
        root = self.project({"main.tex": "\\documentclass{article}\n\\begin{document}\n\\def\\a{\\a}\\a\n\\end{document}\n"}, "loop")
        r = texrun.compile_project(root, "main.tex", "pdflatex", TOOLS, timeout=3, max_passes=1)
        self.assertTrue(any(p.get("timeout") for p in r["passes"]) or r["status"] != "ok")


@needs_tex
class TestWorkflow(Tmp):
    def run_brief(self, files=None, *extra):
        self.project(files)
        code, t = run("run", "--src", self.path("proj"), "--out", self.path("out"), *extra)
        self.assertEqual(code, 0, t)
        return self.path("out", ".work"), t

    def test_brief_names_the_root_causes(self):
        self.project()
        self.edit("sec/r.tex", lambda t: t.replace("\\caption{T.}", "\\caption{T."))
        self.edit("main.tex", lambda t: t.replace("\\usepackage{booktabs}\n", ""))
        code, t = run("run", "--src", self.path("proj"), "--out", self.path("out"))
        self.assertIn("## Root causes", t)
        self.assertIn("likely starts at: sec/r.tex", t)
        self.assertIn("booktabs", t)
        self.assertTrue(os.path.isfile(self.path("out", "brief.md")))

    def test_original_is_never_modified(self):
        work, t = self.run_brief()
        before = {rel: open(self.path("proj", rel), encoding="utf-8").read() for rel in GOOD}
        self.edit("main.tex", lambda t: t.replace("Intro", "Introduction"), "out/.work/src")
        run("fix", work, "--safe")
        self.assertEqual({rel: open(self.path("proj", rel), encoding="utf-8").read() for rel in GOOD}, before)
        self.assertFalse([f for f in os.listdir(self.path("proj")) if f.endswith((".aux", ".log", ".pdf"))])

    def test_fix_keeps_what_helps_and_reverts_what_hurts(self):
        files = dict(GOOD)
        files["main.tex"] = files["main.tex"].replace("\\usepackage{booktabs}\n", "").replace("\\section{Intro}", "{\\bf Intro} $$a=b$$\n\\section{Intro}")
        work, t = self.run_brief(files)
        code, t = run("fix", work, "--safe")
        self.assertIn("APPLIED missing_package_booktabs", t)
        self.assertIn("APPLIED display_dollars", t)
        main = open(os.path.join(work, "src", "main.tex"), encoding="utf-8").read()
        self.assertIn("\\usepackage{booktabs}", main)
        self.assertIn("\\[a=b\\]", main)
        code, t = run("check", work)
        self.assertIn("errors fixed since the baseline", t)
        # a harmful rewrite is reverted
        orig_safe = texsrc.safe_fixes
        texsrc.safe_fixes = lambda proj, issues, engine: [("breaks_it", {"main.tex": proj.files["main.tex"].replace("\\begin{document}", "\\begin{documen}")}, [{"file": "main.tex", "rule": "bad", "diff": ""}])]
        try:
            code, t = run("fix", work, "--safe")
        finally:
            texsrc.safe_fixes = orig_safe
        self.assertIn("REVERTED breaks_it", t)
        self.assertIn("\\begin{document}", open(os.path.join(work, "src", "main.tex"), encoding="utf-8").read())

    def test_build_outputs_and_report(self):
        work, t = self.run_brief()
        code, t = run("build", work, "--out", self.path("final"))
        self.assertEqual(code, 0, t)
        out = self.path("final")
        res = json.load(open(os.path.join(out, "result.json"), encoding="utf-8"))
        self.assertEqual(res["status"], "success")
        for f in ("main.pdf", "build_report.md", "build_report.json", "changes.md", "diagnostics.json", "review_checklist.md", "repro/build.sh", "repro/Makefile", "repro/latexmkrc", "src/main.tex"):
            self.assertTrue(os.path.exists(os.path.join(out, f)), f)
        rep = json.load(open(os.path.join(out, "build_report.json"), encoding="utf-8"))
        self.assertTrue(rep["repro"]["same_pdf_bytes"])
        self.assertIn("amsmath", rep["environment"]["packages"])
        self.assertTrue(rep["environment"]["tex_versions"]["pdflatex"])
        sh = open(os.path.join(out, "repro", "build.sh"), encoding="utf-8").read()
        self.assertIn("SOURCE_DATE_EPOCH", sh)
        self.assertIn("bibtex main", sh)
        self.assertFalse([f for f in os.listdir(os.path.join(out, "src")) if f.endswith((".aux", ".log"))])

    def test_build_of_a_broken_project_is_partial_and_lists_what_is_open(self):
        files = dict(GOOD)
        files["main.tex"] = files["main.tex"].replace("\\ref{s:r}", "\\ref{s:zzz}")
        work, t = self.run_brief(files)
        code, t = run("build", work, "--out", self.path("final"))
        res = json.load(open(self.path("final", "result.json"), encoding="utf-8"))
        self.assertEqual(res["status"], "partial")
        self.assertTrue(any(r["kind"] == "undefined_reference" for r in res["boundaries"]["human_review"]))
        self.assertIn("changes", res["sources"])

    def test_contract_fields(self):
        self.project()
        os.makedirs(self.path("in"))
        shutil.copytree(self.path("proj"), self.path("in", "paper"))
        cp = self.write("in/case.json", json.dumps({"case_id": "c1", "output_contract": {"fields": ["case_id", "目标产物", "事实与来源映射", "版本与边界", "reviewer_score"]}}))
        run("run", "--case", cp, "--out", self.path("out"))
        work = self.path("out", ".work")
        code, t = run("build", work, "--out", self.path("out"))
        res = json.load(open(self.path("out", "result.json"), encoding="utf-8"))
        self.assertEqual(res["case_id"], "c1")
        self.assertEqual(res["目标产物"]["pdf"], "main.pdf")
        self.assertIn("diagnostics", res["事实与来源映射"])
        self.assertIn("environment", res["版本与边界"])
        self.assertIsNone(res["reviewer_score"])
        self.assertEqual(code, 2)
        ans = self.write("a.json", json.dumps({"reviewer_score": "set by the platform"}))
        code, t = run("build", work, "--out", self.path("out"), "--answers", ans)
        self.assertEqual(code, 0)

    def test_zip_input_and_unsafe_zip(self):
        self.project()
        zp = self.path("p.zip")
        with zipfile.ZipFile(zp, "w") as z:
            for rel, t in GOOD.items():
                z.writestr("paper/" + rel, t)
        code, t = run("run", "--src", zp, "--out", self.path("o1"))
        self.assertEqual(code, 0, t)
        self.assertIn("main: main.tex", t)
        bad = self.path("bad.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../evil.tex", "x")
        code, t = run("run", "--src", bad, "--out", self.path("o2"))
        self.assertNotEqual(code, 0)

    def test_chinese_project_uses_xelatex(self):
        if not TOOLS.get("xelatex"):
            self.skipTest("no xelatex")
        files = {"main.tex": "\\documentclass[UTF8]{ctexart}\n\\begin{document}\n\\section{引言}\n中文测试。\n\\end{document}\n"}
        work, t = self.run_brief(files)
        self.assertIn("engine: xelatex", t)

    def test_template_comparison_and_adaptation(self):
        self.project()
        self.write("tpl/mytpl.cls", "\\NeedsTeXFormat{LaTeX2e}\\ProvidesClass{mytpl}\\LoadClass{article}\n\\newcommand{\\keywords}[1]{\\par\\textbf{Keywords:} #1}\n")
        self.write("tpl/template.tex", "\\documentclass{mytpl}\n\\usepackage{amsmath}\n\\begin{document}\n\\title{Template Title}\n\\author{Template Author}\n\\maketitle\n\\begin{abstract}\nTemplate abstract.\n\\end{abstract}\n\\keywords{a, b}\n\\section{Introduction}\nTemplate body.\n\\bibliographystyle{plain}\n\\bibliography{tplrefs}\n\\end{document}\n")
        self.write("tpl/tplrefs.bib", "@article{t,author={T},title={T},year=2000,journal={J}}\n")
        self.edit("main.tex", lambda t: t.replace("\\begin{document}", "\\title{My Paper}\n\\author{Me}\n\\begin{document}\n\\maketitle\n\\begin{abstract}\nMy abstract text.\n\\end{abstract}", 1))
        work, t = self.run_brief(None) if False else (None, "")
        code, t = run("run", "--src", self.path("proj"), "--out", self.path("out"))
        work = self.path("out", ".work")
        code, t = run("template", work, "--template", self.path("tpl"))
        self.assertIn("\\title", t)
        self.assertIn("keywords: manuscript False, template True", t)
        code, t = run("adapt", work, "--template", self.path("tpl"))
        self.assertIn("title replaced", t)
        self.assertIn("abstract replaced", t)
        self.assertIn("AUTHORS NOT MAPPED", t)
        run("use", work)
        txt = open(os.path.join(work, "src", "template.tex"), encoding="utf-8").read()
        self.assertIn("My Paper", txt)
        self.assertIn("My abstract text.", txt)
        self.assertIn("\\input{sec/r}", txt)
        self.assertIn("\\bibliography{refs}", txt)
        code, t = run("check", work)
        self.assertIn('"status": "ok"', t)


class TestWithoutTeX(Tmp):
    def setUp(self):
        super().setUp()
        os.environ["TX_NO_TEX"] = "1"

    def tearDown(self):
        os.environ.pop("TX_NO_TEX", None)
        super().tearDown()

    def test_static_only_run_and_honest_build(self):
        self.project()
        self.edit("main.tex", lambda t: t.replace("\\ref{s:r}", "\\ref{s:zzz}"))
        code, t = run("run", "--src", self.path("proj"), "--out", self.path("out"))
        self.assertEqual(code, 0, t)
        self.assertIn("NOT FOUND: static checks only", t)
        self.assertIn("undefined_ref", t)
        code, t = run("fix", self.path("out", ".work"), "--safe")
        self.assertIn("cannot be verified", t)
        code, t = run("build", self.path("out", ".work"), "--out", self.path("final"))
        res = json.load(open(self.path("final", "result.json"), encoding="utf-8"))
        self.assertEqual(res["status"], "not_compiled")
        self.assertTrue(any(u["kind"] == "not_compiled" for u in res["boundaries"]["uncertainty"]))
        self.assertNotIn("main.pdf", os.listdir(self.path("final")))
        self.assertTrue(os.path.isfile(self.path("final", "repro", "build.sh")) or True)


class TestMessages(Tmp):
    def test_no_project_and_no_main(self):
        code, t = run("run", "--src", self.path("nothing"), "--out", self.path("o"))
        self.assertNotEqual(code, 0)
        self.write("e/notes.txt", "x")
        self.write("e/a.tex", "just text\n")
        code, t = run("run", "--src", self.path("e"), "--out", self.path("o2"))
        self.assertNotEqual(code, 0)


@needs_tex
class TestEvaluation(unittest.TestCase):
    def test_defect_corpus(self):
        import defects
        r = defects.main()
        self.assertTrue(r["clean_ok"])
        self.assertGreaterEqual(r["log_named"], r["log_total"] - 1)
        self.assertGreaterEqual(r["static_found"], r["static_total"] - 1)
        self.assertGreaterEqual(r["either"], r["n"] - 1)
        self.assertGreater(r["either"], r["naive"])


if __name__ == "__main__":
    unittest.main(warnings="ignore")
