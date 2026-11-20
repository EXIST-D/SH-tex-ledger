#!/usr/bin/env python3
"""texsrc.py - the LaTeX source as a project: files, the input graph, and static checks that need no TeX installation.

`Project` reads the main file and everything it \\input / \\include / \\subfile / \\import s, the bibliographies, the graphics. `lint` finds, with file and line:
unbalanced braces and environments, odd `$`, unescaped % after numbers / _ in text, undefined or duplicated labels, \\ref / \\cite targets that do not exist, .bib keys / duplicates / missing fields,
missing input and graphic files, table rows whose column count differs from the column specification, floats without caption or with \\label before \\caption, scaling hacks, package order and
conflicts (hyperref last, subfig + subcaption, natbib + biblatex, inputenc with xelatex ...), obsolete commands, engine requirements.
`safe_fixes` are deterministic text rewrites (each returns change records); the caller recompiles and keeps a fix only if it does not make things worse.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

import texlog
CMD_PACKAGES_STATIC = {c: [p.split(" ")[0]] + ([x for x in re.findall(r"\b(?:or|\+|\[)\s*([a-z]+)", p)] if "(" in p else []) for c, p in texlog.CMD_PACKAGES.items() if re.match(r"^[a-z]+( \(or [a-z]+\)| \([a-z \[\]]+\))?$", p) and not p.startswith("(")}
CMD_PACKAGES_STATIC.update({"url": ["url", "hyperref", "xurl"], "color": ["xcolor", "color"], "textcolor": ["xcolor", "color"], "definecolor": ["xcolor", "color"], "text": ["amsmath", "amstext", "mathtools"], "eqref": ["amsmath", "mathtools"], "bm": ["bm"], "mathbb": ["amssymb", "amsfonts", "mathbb", "unicode-math", "newtxmath", "mathtools"], "mathfrak": ["amssymb", "amsfonts", "eufrak", "unicode-math"], "citep": ["natbib"], "citet": ["natbib"], "citeauthor": ["natbib"]})
VERBATIM_ENVS = ("verbatim", "verbatim*", "lstlisting", "minted", "comment", "Verbatim", "BVerbatim", "alltt")
TABLE_ENVS = ("tabular", "tabular*", "tabularx", "longtable", "tabulary", "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "Bmatrix", "smallmatrix", "cases", "align", "align*", "alignat", "alignat*", "flalign", "flalign*", "eqnarray", "eqnarray*", "split", "aligned", "alignedat", "gathered", "array", "IEEEeqnarray", "supertabular", "xtabular", "tabbing", "subarray", "multline", "dcases")
ENV_PACKAGES = {"algorithm": ["algorithm", "algorithm2e", "algorithmic", "algpseudocode"], "algorithmic": ["algorithmic", "algorithmicx", "algpseudocode"], "theorem": ["amsthm", "ntheorem", "theorem"], "proof": ["amsthm", "ntheorem"], "lstlisting": ["listings"], "subfigure": ["subfigure"],
                "tikzpicture": ["tikz"], "axis": ["pgfplots"], "multicols": ["multicol"], "longtable": ["longtable"], "tabularx": ["tabularx"], "align": ["amsmath", "mathtools"], "align*": ["amsmath", "mathtools"], "gather": ["amsmath", "mathtools"], "cases": ["amsmath", "mathtools"],
                "minted": ["minted"], "wrapfigure": ["wrapfig"], "sidewaystable": ["rotating"], "threeparttable": ["threeparttable"], "CJK": ["CJK"], "otherlanguage": ["babel", "polyglossia"]}
MATH_ENVS = ("equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*", "displaymath", "math", "flalign", "flalign*", "split", "alignat", "alignat*")
GFX_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".PNG", ".JPG", ".PDF", ".JPEG", ".EPS", ".bmp", ".tif", ".tiff")
AFTER_HYPERREF_OK = {"cleveref", "bookmark", "hypcap", "glossaries", "glossaries-extra", "tagpdf", "doi", "xurl", "nameref", "backref", "hyperxmp", "autonum", "pdfcomment", "zref-hyperref"}
CONFLICTS = [("subfig", "subcaption"), ("subfigure", "subfig"), ("subfigure", "subcaption"), ("natbib", "biblatex"), ("cite", "biblatex"), ("times", "mathptmx"), ("fontspec", "inputenc"), ("fontspec", "fontenc"), ("unicode-math", "amssymb"), ("unicode-math", "amsfonts"), ("algorithm2e", "algorithmic"), ("algorithm2e", "algpseudocode"), ("algorithmic", "algpseudocode"), ("subfigure", "subcaption")]
XE_ONLY = {"fontspec", "xeCJK", "unicode-math", "polyglossia", "xunicode"}
OBSOLETE_PKG = {"epsfig": "use graphicx", "subfigure": "use subcaption (or subfig)", "a4wide": "use geometry", "times": "use mathptmx / newtxtext + newtxmath, or the template's font package", "psfig": "use graphicx", "doublespace": "use setspace", "caption2": "use caption", "t1enc": "use \\usepackage[T1]{fontenc}", "fancyheadings": "use fancyhdr"}
OBS_CMD = [(r"\\bf(?![A-Za-z])", "\\bf is a switch removed from LaTeX2e fonts: use \\bfseries or \\textbf{...} (\\mathbf in math)"), (r"\\it(?![A-Za-z])", "\\it: use \\itshape or \\textit{...}"), (r"\\rm(?![A-Za-z])", "\\rm: use \\rmfamily or \\textrm{...}"),
           (r"\\sc(?![A-Za-z])", "\\sc: use \\scshape or \\textsc{...}"), (r"\\tt(?![A-Za-z])", "\\tt: use \\ttfamily or \\texttt{...}"), (r"\\sl(?![A-Za-z])", "\\sl: use \\slshape or \\textsl{...}"), (r"\\over(?![A-Za-z])", "\\over: use \\frac{..}{..}"),
           (r"\\centerline\b", "\\centerline: use \\centering inside the float or the center environment"), (r"\\begin\{eqnarray\*?\}", "eqnarray has bad spacing and clashes with amsmath: use align")]


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def blank_verbatim(text):
    """text with the contents of verbatim-like environments and \\verb replaced by spaces (line structure kept)"""
    for env in VERBATIM_ENVS:
        text = re.sub(r"(\\begin\{%s\})(.*?)(\\end\{%s\})" % (re.escape(env), re.escape(env)), lambda m: m.group(1) + re.sub(r"[^\n]", " ", m.group(2)) + m.group(3), text, flags=re.S)
    text = re.sub(r"\\verb\*?(.)(.*?)\1", lambda m: "\\verb" + " " * (len(m.group(0)) - 5), text)
    text = re.sub(r"\\(?:lstinline|mintinline)(?:\[[^\]]*\])?\{[^}]*\}", lambda m: " " * len(m.group(0)), text)
    return text


def strip_comments(text):
    """list of lines without comments (a % not preceded by an odd number of backslashes starts a comment); verbatim contents blanked"""
    out = []
    for ln in blank_verbatim(text).split("\n"):
        i = 0
        cut = None
        while i < len(ln):
            if ln[i] == "\\":
                i += 2
                continue
            if ln[i] == "%":
                cut = i
                break
            i += 1
        out.append(ln if cut is None else ln[:cut])
    return out


def grab_arg(text, start):
    """the {...} argument that begins at or after `start` -> (content, end) or (None, start)"""
    i = text.find("{", start)
    if i < 0:
        return None, start
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    return None, start


class Project:
    def __init__(self, root, main=None):
        self.root = os.path.abspath(root)
        self.files = {}      # rel -> text
        self.order = []      # rel paths in reading order
        self.bibs = {}       # rel -> text
        self.missing_inputs = []   # (file, line, name)
        self.main = main or self.find_main()
        self.graphicspath = ["."]
        if self.main:
            self.load(self.main, [])

    # ---- files
    def all_tex(self):
        out = []
        for dp, dn, fn in os.walk(self.root):
            dn[:] = [d for d in dn if not d.startswith(".") and d not in ("build", "__pycache__", "node_modules")]
            for f in fn:
                if f.endswith(".tex"):
                    out.append(os.path.relpath(os.path.join(dp, f), self.root))
        return sorted(out)

    def find_main(self):
        cands = []
        for rel in self.all_tex():
            t = read(os.path.join(self.root, rel))
            if re.search(r"^[^%\n]*\\documentclass", t, re.M):
                cands.append(rel)
        if not cands:
            return None
        for pref in ("main.tex", "paper.tex", "ms.tex", "article.tex", "thesis.tex"):
            for c in cands:
                if os.path.basename(c) == pref and os.sep not in c:
                    return c
        # a candidate that nobody includes, with the most inputs
        included = set()
        for rel in self.all_tex():
            for m in re.finditer(r"\\(?:input|include|subfile)\{([^}]+)\}", read(os.path.join(self.root, rel))):
                included.add(os.path.normpath(m.group(1)) + ("" if m.group(1).endswith(".tex") else ".tex"))
        free = [c for c in cands if os.path.normpath(c) not in included]
        return sorted(free or cands, key=lambda c: (c.count(os.sep), c))[0]

    def resolve(self, name, base_rel, exts=(".tex", "")):
        base_dir = os.path.dirname(base_rel)
        for d in (base_dir, ""):
            for e in exts:
                p = os.path.normpath(os.path.join(d, name + (e if not name.endswith(e) or e == "" else "")))
                if os.path.isfile(os.path.join(self.root, p)):
                    return p
        return None

    def load(self, rel, stack):
        if rel in self.files or rel in stack:
            return
        full = os.path.join(self.root, rel)
        text = read(full)
        self.files[rel] = text
        self.order.append(rel)
        lines = strip_comments(text)
        joined = "\n".join(lines)
        for m in re.finditer(r"\\graphicspath\{((?:\{[^}]*\})+)\}", joined):
            for p in re.findall(r"\{([^}]*)\}", m.group(1)):
                self.graphicspath.append(p.rstrip("/"))
        for no, ln in enumerate(lines, 1):
            for m in re.finditer(r"\\(input|include|subfile|InputIfFileExists)\s*\{([^}]+)\}", ln):
                name = m.group(2).strip()
                tgt = self.resolve(name, rel, (".tex", ""))
                if tgt:
                    self.load(tgt, stack + [rel])
                else:
                    self.missing_inputs.append((rel, no, name))
            for m in re.finditer(r"\\import\*?\{([^}]*)\}\{([^}]+)\}", ln):
                tgt = self.resolve(os.path.join(m.group(1), m.group(2)), rel, (".tex", ""))
                if tgt:
                    self.load(tgt, stack + [rel])
                else:
                    self.missing_inputs.append((rel, no, m.group(1) + m.group(2)))
            for m in re.finditer(r"\\(?:bibliography|addbibresource)(?:\[[^\]]*\])?\s*\{([^}]+)\}", ln):
                for b in m.group(1).split(","):
                    b = b.strip()
                    tgt = self.resolve(b, rel, (".bib", ""))
                    if tgt and tgt not in self.bibs:
                        self.bibs[tgt] = read(os.path.join(self.root, tgt))
                    elif not tgt:
                        self.missing_inputs.append((rel, no, b + (".bib" if not b.endswith(".bib") else "")))

    # ---- views
    def lines(self, rel):
        return strip_comments(self.files[rel])

    def preamble(self):
        """(rel, line, kind, name, options) of documentclass / usepackage in reading order, up to \\begin{document}"""
        out = []
        for rel in self.order:
            for no, ln in enumerate(self.lines(rel), 1):
                if re.search(r"\\begin\{document\}", ln):
                    return out
                for m in re.finditer(r"\\(documentclass|usepackage|RequirePackage)\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}", ln):
                    for nm in m.group(3).split(","):
                        out.append((rel, no, m.group(1), nm.strip(), (m.group(2) or "").strip()))
        return out

    def engine(self):
        """(engine, reason): from a %!TEX program magic comment, else from the packages"""
        for rel in self.order[:1]:
            m = re.search(r"^%\s*!\s*(?:TEX|TeX)\s+(?:TS-)?program\s*=\s*(\w+)", self.files[rel], re.M)
            if m:
                e = m.group(1).lower()
                return {"pdftex": "pdflatex", "pdflatex": "pdflatex", "xetex": "xelatex", "xelatex": "xelatex", "luatex": "lualatex", "lualatex": "lualatex"}.get(e, e), "magic comment %!TEX program"
        pk = {p[3] for p in self.preamble()}
        cls = next((p[3] for p in self.preamble() if p[2] == "documentclass"), "")
        for p in XE_ONLY:
            if p in pk:
                return "xelatex", "package %s needs XeTeX / LuaTeX" % p
        if "luacode" in pk or "luatexja" in pk or "lualatex-math" in pk:
            return "lualatex", "package needs LuaTeX"
        if cls in ("ctexart", "ctexrep", "ctexbook") or "ctex" in pk:
            return "xelatex", "ctex works best with XeLaTeX (Chinese fonts)"
        return "pdflatex", "default"


# ------------------------------------------------------------------------------------------------ lint
def issue(out, code, sev, file, line, msg, fix="", **kw):
    out.append({"code": code, "severity": sev, "file": file, "line": line, "message": msg, "fix": fix, **kw})


def lint(proj, engine=None):
    iss = []
    if not proj.main:
        issue(iss, "no_main", "error", "", None, "no .tex file with \\documentclass was found", "pass the main file explicitly")
        return iss
    engine = engine or proj.engine()[0]
    labels, refs, cites = defaultdict(list), [], []
    for rel in proj.order:
        lines = proj.lines(rel)
        text = "\n".join(lines)
        # ---- braces
        stack = []
        for no, ln in enumerate(lines, 1):
            i = 0
            while i < len(ln):
                c = ln[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "{":
                    stack.append((no, i))
                elif c == "}":
                    if stack:
                        stack.pop()
                    else:
                        issue(iss, "extra_brace", "error", rel, no, "a } closes a group that was never opened", "remove the } or add the missing {")
                i += 1
        for no, col in stack[:3]:
            ctx = lines[no - 1][max(0, col - 20):col + 25].strip()
            issue(iss, "unclosed_brace", "error", rel, no, "a { is never closed (near \"%s\")" % ctx, "add the missing }: TeX will report this far from here (\"File ended while scanning ...\")")
        # ---- environments
        envs = []
        for no, ln in enumerate(lines, 1):
            for m in re.finditer(r"\\(begin|end)\{([^}]+)\}", ln):
                kind, name = m.group(1), m.group(2)
                if kind == "begin":
                    envs.append((name, no))
                else:
                    if envs and envs[-1][0] == name:
                        envs.pop()
                    elif any(e[0] == name for e in envs):
                        while envs and envs[-1][0] != name:
                            o = envs.pop()
                            issue(iss, "env_unclosed", "error", rel, o[1], "\\begin{%s} is not closed before \\end{%s} (line %d)" % (o[0], name, no), "add \\end{%s} or fix the nesting" % o[0])
                        envs.pop()
                    else:
                        o = envs[-1] if envs else None
                        issue(iss, "env_mismatch", "error", rel, no, "\\end{%s} does not match%s" % (name, (" \\begin{%s} from line %d" % o) if o else " any \\begin"), "make the pair match (one is a typo)")
                        if o:
                            envs.pop()
        for name, no in envs:
            issue(iss, "env_unclosed", "error", rel, no, "\\begin{%s} is never closed%s" % (name, " (the file ends without \\end{document})" if name == "document" else ""), "add \\end{%s}" % name)
        # ---- $ parity per paragraph, $$, % after number, underscore in text
        paras, cur, start = [], [], 1
        for no, ln in enumerate(lines, 1):
            if ln.strip() == "":
                if cur:
                    paras.append((start, cur))
                cur = []
                start = no + 1
            else:
                if not cur:
                    start = no
                cur.append(ln)
        if cur:
            paras.append((start, cur))
        for st, pl in paras:
            ptxt = "\n".join(pl)
            body = re.sub(r"\\\$", "  ", ptxt)
            body = re.sub(r"\$\$", "", body)
            if body.count("$") % 2 == 1:
                first = next((st + k for k, l in enumerate(pl) if "$" in re.sub(r"\\\$", "  ", l)), st)
                issue(iss, "odd_dollar", "error", rel, first, "an odd number of $ in this paragraph: a math formula is not closed", "close the $...$ pair (or escape a literal dollar as \\$)")
        for no, ln in enumerate(lines, 1):
            if "$$" in re.sub(r"\\\$", "  ", ln):
                issue(iss, "display_dollars", "warn", rel, no, "$$ ... $$ is a TeX primitive: it breaks spacing and amsmath numbering", "use \\[ ... \\] or an equation environment", autofix=True)

        for no, ln in enumerate(blank_verbatim(proj.files[rel]).split("\n"), 1):
            m = re.search(r"(?<![\\\d.])(\d+(?:\.\d+)?)%[ \t]*\S", ln)
            if m and not ln.lstrip().startswith("%"):
                issue(iss, "percent_after_number", "warn", rel, no, "\"%s%%\": an unescaped %% starts a comment and drops the rest of the line (\"%s\")" % (m.group(1), ln.strip()[:50]), "write \\% for a percent sign")
        # ampersands outside any table / alignment environment; environments whose package is not loaded
        tab_depth = 0
        for no, ln in enumerate(lines, 1):
            tab_depth += len(re.findall(r"\\begin\{(?:%s)\}" % "|".join(re.escape(e) for e in TABLE_ENVS), ln))
            if tab_depth <= 0 and re.search(r"(?<!\\)&", re.sub(r"\\(?:url|href|path)\{[^}]*\}", "", ln)) and not re.search(r"\\(?:newcommand|renewcommand|def|let|newenvironment|AtBeginDocument)", ln):
                issue(iss, "ampersand_in_text", "error", rel, no, "an & outside a table or alignment environment (\"%s\")" % ln.strip()[:50], "write \\& for a literal ampersand")
            tab_depth -= len(re.findall(r"\\end\{(?:%s)\}" % "|".join(re.escape(e) for e in TABLE_ENVS), ln))
            tab_depth = max(tab_depth, 0)
        # text-mode underscores / hashes / ampersands
        masked = mask_non_text(lines)
        for no, ln in enumerate(masked, 1):
            if re.search(r"(?<!\\)_", ln):
                issue(iss, "underscore_in_text", "error", rel, no, "an underscore outside math mode (\"%s\")" % ln.strip()[:60], "write \\_ (or put the name in \\texttt{...\\_...}, or use \\url / \\path for names and paths)")
            if re.search(r"(?<!\\)#", ln):
                issue(iss, "hash_in_text", "error", rel, no, "a # outside a macro definition", "write \\#")
        # ---- obsolete commands
        for pat, msg in OBS_CMD:
            for no, ln in enumerate(lines, 1):
                if re.search(pat, ln):
                    issue(iss, "obsolete_command", "info", rel, no, msg)
                    break
        # ---- labels, refs, cites, figures
        for no, ln in enumerate(lines, 1):
            for m in re.finditer(r"\\label\{([^}]+)\}", ln):
                labels[m.group(1).strip()].append((rel, no))
            for m in re.finditer(r"\\(?:ref|eqref|autoref|pageref|nameref|vref|cref|Cref|crefrange|labelcref)\*?\{([^}]+)\}", ln):
                for k in m.group(1).split(","):
                    refs.append((k.strip(), rel, no))
            for m in re.finditer(r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|parencite|textcite|autocite|footcite|nocite|supercite|cites)[A-Za-z]*\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}", ln):
                for k in m.group(1).split(","):
                    cites.append((k.strip(), rel, no))
            for m in re.finditer(r"\\includegraphics\*?(?:\[[^\]]*\])?\{([^}]+)\}", ln):
                name = m.group(1).strip()
                if re.match(r"^(/|[A-Za-z]:[\\/]|~)", name):
                    issue(iss, "absolute_path", "warn", rel, no, "absolute path \"%s\": the build cannot be repeated on another machine" % name, "copy the file into the project and use a relative path")
                found = None
                for d in proj.graphicspath:
                    for e in ("",) + GFX_EXT:
                        p = os.path.normpath(os.path.join(os.path.dirname(rel), d, name + e))
                        p2 = os.path.normpath(os.path.join(d, name + e))
                        for q in (p, p2):
                            if os.path.isfile(os.path.join(proj.root, q)):
                                found = q
                                break
                        if found:
                            break
                    if found:
                        break
                if not found and not re.match(r"^(/|[A-Za-z]:[\\/]|~)", name):
                    issue(iss, "missing_graphic", "error", rel, no, "graphic \"%s\" not found (tried %s and the \\graphicspath folders)" % (name, "/".join(e or "as written" for e in ("",) + GFX_EXT[:3])), "fix the path / file name (case matters on Linux) or add the file")
                elif found and found.lower().endswith(".svg"):
                    issue(iss, "svg_graphic", "warn", rel, no, "SVG is not read by pdfLaTeX / XeLaTeX directly", "convert to PDF or use the svg package with Inkscape")
            for m in re.finditer(r"\\(?:resizebox|scalebox)\{", ln):
                issue(iss, "scaling_hack", "info", rel, no, "%s scales a table / figure instead of fixing its layout: text size becomes inconsistent" % m.group(0)[1:-1], "prefer \\small / tabularx / column widths; keep scaling only for figures")
        for fl, fn, nm in [(f, n, nm) for f, n, nm in proj.missing_inputs if f == rel]:
            issue(iss, "missing_input", "error", rel, fn, "\\input / \\include / bibliography file \"%s\" not found" % nm, "fix the name / path (extension .tex is optional)")
        # ---- float checks
        for m in re.finditer(r"\\begin\{(figure\*?|table\*?)\}(\[[^\]]*\])?(.*?)\\end\{\1\}", text, re.S):
            body = m.group(3)
            line = text[:m.start()].count("\n") + 1
            if "\\caption" not in body:
                issue(iss, "float_no_caption", "warn", rel, line, "%s without \\caption" % m.group(1), "add a caption (and a label after it)")
            li, ci = body.find("\\label"), body.find("\\caption")
            if li >= 0 and ci >= 0 and li < ci:
                issue(iss, "label_before_caption", "error", rel, line + body[:li].count("\n"), "\\label comes before \\caption: \\ref will show the section number instead of the figure / table number", "move \\label after \\caption", autofix=True)
            if m.group(2) and re.fullmatch(r"\[h\]", m.group(2)):
                issue(iss, "float_h_only", "info", rel, line, "[h] alone is often ignored: LaTeX changes it to [ht]", "use [htbp] or [!htbp]", autofix=True)
        # ---- tables
        for m in re.finditer(r"\\begin\{(tabular\*?|tabularx|longtable|tabulary|array)\}(?:\{[^}]*\})?\s*(?:\[[a-z]\])?\s*(\{)", text):
            env = m.group(1)
            start = m.start(2)
            spec, end = grab_arg(text, start)
            if spec is None:
                continue
            ncol = count_cols(spec)
            endm = re.search(r"\\end\{%s\}" % re.escape(env), text[end:])
            if not endm or ncol is None:
                continue
            body = text[end:end + endm.start()]
            rows = split_rows(body)
            bad = []
            for rtext, off in rows:
                r = re.sub(r"\\(?:hline|toprule|midrule|bottomrule|cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\}|addlinespace(?:\[[^\]]*\])?|endhead|endfirsthead|endfoot|endlastfoot|noalign\{[^}]*\})", "", rtext)
                if not r.strip():
                    continue
                n = row_cols(r)
                if n != ncol and n > 1 or (n > ncol):
                    bad.append((text[:end + off].count("\n") + 1, n))
            for line, n in bad[:2]:
                issue(iss, "table_columns", "error", rel, line, "this row has %d column(s) but the column specification {%s} defines %d" % (n, spec, ncol), "add / remove & or fix the specification (\\multicolumn counts as its span)")
    # ---- cross references
    for lab, locs in labels.items():
        if len(locs) > 1:
            issue(iss, "duplicate_label", "error", locs[1][0], locs[1][1], "label \"%s\" is defined %d times (first at %s:%d)" % (lab, len(locs), locs[0][0], locs[0][1]), "give each label a unique name")
    for k, rel, no in refs:
        if k and k not in labels:
            near = sorted(labels, key=lambda l: -sim(l, k))[:1]
            issue(iss, "undefined_ref", "error", rel, no, "\\ref to label \"%s\" which no \\label defines" % k, ("did you mean \"%s\"?" % near[0]) if near and sim(near[0], k) > 0.6 else "define the label or fix the name")
    used_refs = {r[0] for r in refs}
    for lab, locs in labels.items():
        if lab not in used_refs:
            issue(iss, "unused_label", "info", locs[0][0], locs[0][1], "label \"%s\" is never referenced" % lab)
    # ---- bibliography
    bibkeys, dup = {}, []
    for brel, btxt in proj.bibs.items():
        for m in re.finditer(r"^\s*@(\w+)\s*[{(]\s*([^,\s]+)\s*,", btxt, re.M):
            if m.group(1).lower() in ("comment", "string", "preamble"):
                continue
            line = btxt[:m.start()].count("\n") + 1
            if m.group(2) in bibkeys:
                dup.append((brel, line, m.group(2)))
            bibkeys.setdefault(m.group(2), (brel, line))
        for m in re.finditer(r"^\s*@(\w+)\s*[{(]\s*([^,\s]+)\s*,(.*?)(?=^\s*@|\Z)", btxt, re.M | re.S):
            if m.group(1).lower() in ("comment", "string", "preamble"):
                continue
            body = m.group(3).lower()
            missing = [f for f, alts in (("author", ("author", "editor")), ("title", ("title",)), ("year", ("year", "date"))) if not any(re.search(r"(?:^|[,\s{])%s\s*=" % a, body) for a in alts)]
            if missing and m.group(1).lower() not in ("misc", "online", "manual", "booklet", "proceedings", "book") or (missing and "title" in missing):
                issue(iss, "bib_missing_field", "warn", brel, btxt[:m.start()].count("\n") + 1, "entry %s lacks %s" % (m.group(2), ", ".join(missing)), "complete the entry (the style may print blanks or warnings)")
    for brel, line, k in dup:
        issue(iss, "bib_duplicate_key", "error", brel, line, "BibTeX key \"%s\" appears twice" % k, "rename or delete one entry")
    for k, rel, no in cites:
        if k == "*":
            continue
        if bibkeys and k not in bibkeys:
            near = sorted(bibkeys, key=lambda b: -sim(b, k))[:1]
            issue(iss, "undefined_cite", "error", rel, no, "\\cite{%s}: no such key in the .bib file(s)" % k, ("did you mean \"%s\"?" % near[0]) if near and sim(near[0], k) > 0.6 else "add the entry or fix the key")
        elif not bibkeys and not has_thebibliography(proj):
            issue(iss, "cite_without_bibliography", "error", rel, no, "\\cite{%s} but the project has no .bib file or thebibliography environment" % k, "add \\bibliography{...} with its .bib file")
    if cites and bibkeys:
        cited = {c[0] for c in cites}
        unused = [k for k in bibkeys if k not in cited]
        if unused and "*" not in cited:
            issue(iss, "unused_bib_entries", "info", list(proj.bibs)[0], None, "%d .bib entries are never cited (e.g. %s)" % (len(unused), ", ".join(unused[:4])))
    if cites and not re.search(r"\\bibliographystyle|\\printbibliography|\\begin\{thebibliography\}|\\bibliography\{", "\n".join(proj.files.values())):
        issue(iss, "no_bibliography_command", "error", proj.main, None, "citations exist but no \\bibliography / \\printbibliography / thebibliography is written", "add \\bibliographystyle{...}\\bibliography{...} (or \\printbibliography for biblatex)")
    # ---- packages
    pre = proj.preamble()
    names = [p[3] for p in pre if p[2] != "documentclass"]
    seen = {}
    for rel, no, kind, nm, opt in pre:
        if kind == "documentclass":
            continue
        if nm in seen:
            issue(iss, "package_twice", "warn", rel, no, "package %s is loaded twice (first at %s:%d)%s" % (nm, seen[nm][0], seen[nm][1], " with different options" if seen[nm][2] != opt else ""), "load it once with all options", autofix=(seen[nm][2] == opt))
        else:
            seen[nm] = (rel, no, opt)
    if "hyperref" in names:
        hi = names.index("hyperref")
        late = [n for n in names[hi + 1:] if n not in AFTER_HYPERREF_OK]
        if late:
            p = [x for x in pre if x[3] == late[0]][0]
            issue(iss, "hyperref_not_last", "warn", p[0], p[1], "package %s is loaded after hyperref: hyperref should come last (except cleveref, bookmark ...) to avoid broken links and option clashes" % late[0], "move \\usepackage{hyperref} below the other packages", autofix=True)
    for a, b in CONFLICTS:
        if a in names and b in names:
            p = [x for x in pre if x[3] == b][0]
            if (a, b) in (("fontspec", "inputenc"), ("fontspec", "fontenc")):
                if engine in ("xelatex", "lualatex"):
                    issue(iss, "engine_package", "warn", p[0], p[1], "%s is for pdfLaTeX; with %s it is unnecessary and can warn / fail" % (b, engine), "remove \\usepackage[...]{%s}" % b, autofix=True)
            else:
                issue(iss, "package_conflict", "error", p[0], p[1], "packages %s and %s conflict (they define the same commands / environments)" % (a, b), "keep one of them")
    for rel, no, kind, nm, opt in pre:
        if nm in OBSOLETE_PKG:
            issue(iss, "obsolete_package", "info", rel, no, "package %s is obsolete: %s" % (nm, OBSOLETE_PKG[nm]))
        if nm in XE_ONLY and engine == "pdflatex":
            issue(iss, "engine_package", "error", rel, no, "package %s needs XeLaTeX or LuaTeX but the engine is pdfLaTeX" % nm, "compile with xelatex / lualatex (or add %!TEX program = xelatex)")
        if nm in ("inputenc", "fontenc") and engine in ("xelatex", "lualatex"):
            issue(iss, "engine_package", "warn", rel, no, "%s is for pdfLaTeX; with %s it is unnecessary" % (nm, engine), "remove it", autofix=True) if not any(i["code"] == "engine_package" and i["line"] == no for i in iss) else None
        if nm == "inputenc" and "utf8" in opt:
            issue(iss, "inputenc_utf8_default", "info", rel, no, "\\usepackage[utf8]{inputenc} has been the default since 2018", "can be removed")
    text_all = "\n".join("\n".join(proj.lines(r)) for r in proj.order)
    loaded0 = set(names) | {p[3] for p in pre if p[2] == "documentclass"}
    envs_used = set(re.findall(r"\\begin\{([\w*]+)\}", text_all))
    for env, pks in ENV_PACKAGES.items():
        if env in envs_used and not (set(pks) & loaded0):
            m = re.search(r"\\begin\{%s\}" % re.escape(env), text_all)
            issue(iss, "env_needs_package", "warn", proj.main, None, "environment %s is used but none of %s is loaded (the compile log decides whether the class provides it)" % (env, " / ".join(pks)), "\\usepackage{%s}" % pks[0], environment=env, package=pks[0])
    loaded = set(names) | {p[3] for p in pre if p[2] == "documentclass"}
    reported = set()
    for cmd, pk in CMD_PACKAGES_STATIC.items():
        m = re.search(r"\\%s(?![A-Za-z])" % re.escape(cmd), text_all)
        if m and not (set(pk) & loaded) and cmd not in reported:
            reported.add(cmd)
            line = text_all[:m.start()].count("\n") + 1
            issue(iss, "command_needs_package", "warn", proj.main, None, "\\%s is used but %s %s not loaded (the compile log decides whether the class provides it)" % (cmd, " / ".join(pk), "is" if len(pk) == 1 else "are"), "\\usepackage{%s}" % pk[0], command=cmd, package=pk[0])
    if re.search(r"\\text\{", text_all) and not any(n in names for n in ("amsmath", "amstext", "mathtools")):
        m = re.search(r"\\text\{", text_all)
        issue(iss, "text_without_amsmath", "error", proj.main, None, "\\text{...} is used but amsmath is not loaded", "add \\usepackage{amsmath}")
    for m in re.finditer(r"(?<![\\A-Za-z])(sin|cos|tan|log|exp|lim|max|min|det|arg)\s*(?:\(|_|\\)", "\n".join(strip_nonmath_keep_math(proj.lines(r)) for r in proj.order)):
        issue(iss, "math_operator_text", "info", proj.main, None, "\"%s\" typed as plain letters in math is set as a product of variables" % m.group(1), "use \\%s" % m.group(1))
        break
    iss.sort(key=lambda i: ({"error": 0, "warn": 1, "info": 2}[i["severity"]], i["file"] or "", i["line"] or 0))
    return iss


def has_thebibliography(proj):
    return any("thebibliography" in t for t in proj.files.values())


def sim(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def count_cols(spec):
    s = re.sub(r"\\\w+\{[^}]*\}", "", spec)
    s = re.sub(r"@\{[^}]*\}|!\{[^}]*\}|>\{[^}]*\}|<\{[^}]*\}", "", s)
    s = re.sub(r"\*\{(\d+)\}\{([^}]*)\}", lambda m: m.group(2) * int(m.group(1)), s)
    s = re.sub(r"[pmbXwW]\{[^}]*\}", "c", s)
    s = re.sub(r"[Sc]\{[^}]*\}", "c", s) if False else s
    n = len(re.findall(r"[lcrXSsp]", s))
    return n if n else None


def split_rows(body):
    rows, pos = [], 0
    depth = 0
    cur_start = 0
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            if body[i:i + 2] == "\\\\":
                if depth == 0:
                    rows.append((body[cur_start:i], cur_start))
                    cur_start = i + 2
                i += 2
                continue
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    rows.append((body[cur_start:], cur_start))
    return rows


def row_cols(r):
    n, depth, i = 1, 0, 0
    span_extra = 0
    for m in re.finditer(r"\\multicolumn\{(\d+)\}", r):
        span_extra += int(m.group(1)) - 1
    while i < len(r):
        c = r[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "&" and depth <= 0:
            n += 1
        i += 1
    return n + span_extra


def mask_non_text(lines):
    """lines with math, command arguments that legitimately hold _ or #, tabular preambles and verbatim removed, to look for text-mode underscores"""
    out = []
    in_math_env = 0
    skip_arg = re.compile(r"\\(?:label|ref|eqref|autoref|cref|Cref|cite[A-Za-z]*|input|include|includegraphics|bibliography|bibliographystyle|usepackage|documentclass|url|href|path|nolinkurl|newcommand|renewcommand|providecommand|def|let|newenvironment|DeclareMathOperator|graphicspath|addbibresource|hypersetup|texttt|lstinline|verb|input|subfile|import|setlength|pagestyle|thispagestyle|bibitem|newtheorem|newcolumntype|nameref|pageref|vref|addplot|filecontents|lstset|setcounter|AtBeginDocument)\b(?:\[[^\]]*\])*(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*")
    for ln in lines:
        l = ln
        if re.search(r"\\begin\{(?:%s)\}" % "|".join(re.escape(e) for e in MATH_ENVS + ("tikzpicture", "axis", "filecontents", "filecontents*", "lstlisting", "minted", "thebibliography")), l):
            in_math_env += 1
        if in_math_env:
            if re.search(r"\\end\{(?:%s)\}" % "|".join(re.escape(e) for e in MATH_ENVS + ("tikzpicture", "axis", "filecontents", "filecontents*", "lstlisting", "minted", "thebibliography")), l):
                in_math_env = max(0, in_math_env - 1)
            out.append("")
            continue
        l = skip_arg.sub(" ", l)
        l = re.sub(r"\\\[.*?\\\]|\\\(.*?\\\)|\$\$.*?\$\$|\$[^$]*\$", " ", l)
        l = re.sub(r"\\_|\\#|\\&", " ", l)
        out.append(l)
    return out


def strip_nonmath_keep_math(lines):
    s = "\n".join(lines)
    parts = re.findall(r"\$[^$\n]+\$|\\begin\{(?:equation|align)\*?\}.*?\\end\{(?:equation|align)\*?\}", s, re.S)
    return "\n".join(parts)


# ------------------------------------------------------------------------------------------------ safe fixes
def safe_fixes(proj, issues, engine):
    """-> list of (rule_id, {rel: new_text}, [change records]) for the deterministic fixes whose problem exists; nothing is written to disk"""
    out = []
    codes = {i["code"] for i in issues}

    def changes_for(rule, edits):
        recs = []
        for rel, (old, new) in edits.items():
            if old != new:
                import difflib
                d = [l for l in difflib.unified_diff(old.split("\n"), new.split("\n"), rel, rel, lineterm="", n=0) if l.startswith(("@@", "+", "-")) and not l.startswith(("+++", "---"))]
                recs.append({"file": rel, "rule": rule, "diff": "\n".join(d[:30])})
        return recs
    if "display_dollars" in codes:
        edits = {}
        for rel, t in proj.files.items():
            if "$$" in t:
                new = re.sub(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", lambda m: "\\[" + m.group(1) + "\\]", t, flags=re.S)
                if new != t and new.count("$$") == 0:
                    edits[rel] = (t, new)
        if edits:
            out.append(("display_dollars", {r: v[1] for r, v in edits.items()}, changes_for("display_dollars: $$..$$ -> \\[..\\]", edits)))
    if "obsolete_command" in codes:
        edits = {}
        for rel, t in proj.files.items():
            lines = t.split("\n")
            new_lines = []
            for ln in lines:
                if ln.lstrip().startswith("%"):
                    new_lines.append(ln)
                    continue
                n = re.sub(r"\{\s*\\(bf|it|rm|sc|tt|sl)\s+([^{}$]*?)\}", lambda m: "\\text%s{%s}" % ({"bf": "bf", "it": "it", "rm": "rm", "sc": "sc", "tt": "tt", "sl": "sl"}[m.group(1)], m.group(2).strip()), ln) if ln.count("$") % 2 == 0 else ln
                new_lines.append(n)
            new = "\n".join(new_lines)
            if new != t:
                edits[rel] = (t, new)
        if edits:
            out.append(("old_font_switches", {r: v[1] for r, v in edits.items()}, changes_for("old font switches {\\bf X} -> \\textbf{X}", edits)))
    if "label_before_caption" in codes:
        edits = {}
        for rel, t in proj.files.items():
            new = re.sub(r"(\\begin\{(figure\*?|table\*?)\})(\[[^\]]*\])?(.*?)\\end\{\2\}", lambda m: swap_float(m), t, flags=re.S)
            if new != t:
                edits[rel] = (t, new)
        if edits:
            out.append(("label_after_caption", {r: v[1] for r, v in edits.items()}, changes_for("\\label moved after \\caption", edits)))
    if "float_h_only" in codes:
        edits = {}
        for rel, t in proj.files.items():
            new = re.sub(r"(\\begin\{(?:figure|table)\*?\})\[h\]", r"\1[htbp]", t)
            if new != t:
                edits[rel] = (t, new)
        if edits:
            out.append(("float_placement", {r: v[1] for r, v in edits.items()}, changes_for("float placement [h] -> [htbp]", edits)))
    if "package_twice" in codes:
        edits = {}
        for i in issues:
            if i["code"] == "package_twice" and i.get("autofix"):
                rel = i["file"]
                t = edits.get(rel, (proj.files[rel], None))[0]
                lines = t.split("\n")
                ln = lines[i["line"] - 1]
                if re.fullmatch(r"\s*\\usepackage(?:\[[^\]]*\])?\{[\w\-,]+\}\s*(?:%.*)?", ln):
                    lines[i["line"] - 1] = "% removed duplicate: " + ln.strip()
                    edits[rel] = (proj.files[rel], "\n".join(lines))
        if edits:
            out.append(("duplicate_package", {r: v[1] for r, v in edits.items()}, changes_for("duplicate \\usepackage commented out", edits)))
    if "engine_package" in codes and engine in ("xelatex", "lualatex"):
        edits = {}
        for i in issues:
            if i["code"] == "engine_package" and i.get("autofix"):
                rel = i["file"]
                t = edits.get(rel, (proj.files[rel], None))
                lines = (t[1] or t[0]).split("\n")
                ln = lines[i["line"] - 1]
                if re.fullmatch(r"\s*\\usepackage(?:\[[^\]]*\])?\{(?:inputenc|fontenc)\}\s*(?:%.*)?", ln):
                    lines[i["line"] - 1] = "% not needed with %s: %s" % (engine, ln.strip())
                    edits[rel] = (proj.files[rel], "\n".join(lines))
        if edits:
            out.append(("engine_packages", {r: v[1] for r, v in edits.items()}, changes_for("inputenc / fontenc commented out for %s" % engine, edits)))
    if "hyperref_not_last" in codes:
        edits = {}
        for rel in proj.order:
            t = proj.files[rel]
            lines = t.split("\n")
            idx = [k for k, l in enumerate(lines) if re.fullmatch(r"\s*\\usepackage(?:\[[^\]]*\])?\{hyperref\}\s*(?:%.*)?", l)]
            if not idx:
                continue
            last_pkg = max([k for k, l in enumerate(lines) if re.match(r"\s*\\usepackage", l) and not re.search(r"\{(?:%s)\}" % "|".join(AFTER_HYPERREF_OK), l)] or [-1])
            if last_pkg > idx[0]:
                h = lines.pop(idx[0])
                lines.insert(last_pkg, h)
                edits[rel] = (t, "\n".join(lines))
        if edits:
            out.append(("hyperref_last", {r: v[1] for r, v in edits.items()}, changes_for("hyperref moved after the other packages", edits)))
    return out


def swap_float(m):
    whole = m.group(0)
    body_start = m.start(4) - m.start(0)
    body_end = m.end(4) - m.start(0)
    body = m.group(4)
    lm = re.search(r"\\label\{[^}]*\}[ \t]*\n?", body)
    cm = re.search(r"\\caption(?:\[[^\]]*\])?", body)
    if not lm or not cm or lm.start() > cm.start():
        return whole
    label = lm.group(0).strip()
    nb = body[:lm.start()] + body[lm.end():]
    cm2 = re.search(r"\\caption(?:\[[^\]]*\])?", nb)
    _, cend = grab_arg(nb, cm2.end())
    if cend is None or cend <= cm2.start():
        return whole
    nb = nb[:cend] + label + nb[cend:]
    return whole[:body_start] + nb + whole[body_end:]
