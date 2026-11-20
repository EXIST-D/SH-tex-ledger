#!/usr/bin/env python3
"""texlog.py - read a TeX / LaTeX / BibTeX / Biber log and say what went wrong, where, and what is only a consequence.

Input: the .log text (compiled with -file-line-error and a wide max_print_line, which `tx.py build` does; wrapped logs of 79 columns are joined). Output: diagnostics
{kind: error|warning|badbox|info, code, message, file, line, context, detail, cascade}, the files that were read, the packages with their versions, and `rerun` / `fatal` flags.
`root_causes` collapses an error list to what a person should fix first: the first error, undefined commands grouped by command, missing files / packages, and the errors that follow a
structural error in the same file are marked as likely consequences.
"""
from __future__ import annotations

import re
from collections import OrderedDict, defaultdict

CMD_PACKAGES = {
    "toprule": "booktabs", "midrule": "booktabs", "bottomrule": "booktabs", "cmidrule": "booktabs", "addlinespace": "booktabs", "includegraphics": "graphicx", "rotatebox": "graphicx", "scalebox": "graphicx", "resizebox": "graphicx",
    "mathbb": "amssymb", "mathfrak": "amssymb", "checkmark": "amssymb", "square": "amssymb", "text": "amsmath", "dfrac": "amsmath", "tfrac": "amsmath", "eqref": "amsmath", "boldsymbol": "amsmath", "xrightarrow": "amsmath", "operatorname": "amsmath",
    "bm": "bm", "SI": "siunitx", "si": "siunitx", "num": "siunitx", "qty": "siunitx", "unit": "siunitx", "SIrange": "siunitx", "ang": "siunitx", "sisetup": "siunitx", "url": "url (or hyperref)", "href": "hyperref", "cref": "cleveref", "Cref": "cleveref",
    "xspace": "xspace", "textcolor": "xcolor", "color": "xcolor", "colorbox": "xcolor", "definecolor": "xcolor", "multirow": "multirow", "cellcolor": "colortbl (xcolor [table])", "rowcolor": "colortbl (xcolor [table])", "subfloat": "subfig",
    "subcaption": "subcaption", "State": "algpseudocode (algorithmicx)", "Require": "algpseudocode", "Ensure": "algpseudocode", "lstlisting": "listings", "lstinputlisting": "listings", "tikz": "tikz", "addplot": "pgfplots", "citep": "natbib", "citet": "natbib",
    "citeauthor": "natbib", "autocite": "biblatex", "parencite": "biblatex", "textcite": "biblatex", "printbibliography": "biblatex", "addbibresource": "biblatex", "mathscr": "mathrsfs", "SetKwInput": "algorithm2e", "lipsum": "lipsum",
    "textmu": "textcomp", "ding": "pifont", "cancel": "cancel", "mathbbm": "bbm", "tabularx": "tabularx", "makecell": "makecell", "diagbox": "diagbox", "sout": "ulem", "hl": "soul", "captionof": "caption", "captionsetup": "caption", "newtheorem": "amsthm",
    "proof": "amsthm", "theoremstyle": "amsthm", "FloatBarrier": "placeins", "mathcal": "(built in; check for a misspelling)", "RequirePackage": "(only in .sty / .cls)", "setmainfont": "fontspec", "setCJKmainfont": "xeCJK", "CJKfamily": "CJK / ctex",
    "dashrule": "background", "begin{CJK}": "CJK", "hline": "(built in; check for \\\\ missing before it)", "threeparttable": "threeparttable", "tnote": "threeparttable", "rowcolors": "xcolor [table]", "nameref": "hyperref", "autoref": "hyperref",
}
CORE_CS = {"begin", "end", "item", "caption", "label", "ref", "cite", "section", "subsection", "textbf", "textit", "centering", "par", "hline", "multicolumn", "emph", "footnote", "bibliography", "bibliographystyle", "input", "include", "maketitle", "title", "author", "date", "\\"}
CASCADE_FIRST = {"runaway", "file_ended", "env_mismatch", "extra_brace", "missing_brace", "missing_dollar", "bad_math_env", "paragraph_ended"}

RX_ERR_FLE = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^\s:][^:]*?):(?P<line>\d+): (?P<msg>.*)$")
RX_ERR_CLASSIC = re.compile(r"^! (?P<msg>.*)$")
RX_LINE = re.compile(r"^l\.(\d+) ?(.*)$")
RX_WARN = re.compile(r"^(?P<who>LaTeX|Package [\w@.\-]+|Class [\w@.\-]+|LaTeX Font|pdfTeX|Module [\w@.\-]+|natbib|hyperref|Package) ?(?P<kind>Warning|Info|Error)?: ?(?P<msg>.*)$")
RX_PKGLINE = re.compile(r"^(?:Package|Document Class|File): ?(?P<name>[\w@.\-]+)(?: |:)?(?P<rest>.*)$")
RX_FILE_OPEN = re.compile(r"\((\.{0,2}/[^\s()]+|[A-Za-z]:[^\s()]+|[\w\-./]+\.(?:tex|sty|cls|clo|def|cfg|fd|aux|bbl|out|toc|lof|lot|ldf|bst|bib|cnf|lbx|cbx|dbx|tikz|ltx|code\.tex|map|tfm|enc|ist|mkii|dtx|ins))")
RX_OVERFULL = re.compile(r"^(Overfull|Underfull) \\([hv])box \((?P<amt>[^)]*)\)(?: (?P<where>in paragraph|in alignment|in vbox|detected|has occurred while \\output is active)(?: at lines (?P<l1>\d+)--(?P<l2>\d+)| at line (?P<l3>\d+)| detected at line (?P<l4>\d+))?.*)?$")
RX_BIBTEX_ERR = re.compile(r"^(?P<msg>(?:I couldn't open (?:database|style) file|I found no \\(?:citation|bibdata|bibstyle)|I was expecting|Illegal, another \\bibstyle|Repeated entry|I'm skipping whatever remains|Sorry---you've exceeded|You're missing a field name|Too many commas|You've used \d+ entries|Warning--I didn't find|Warning--empty|Warning--string name|Warning--to sort).*)$")


def unwrap(text):
    """join lines that TeX broke at max_print_line = 79 (only when most lines are exactly 79 wide)"""
    lines = text.splitlines()
    if sum(1 for l in lines if len(l) == 79) < 5:
        return lines
    out, i = [], 0
    while i < len(lines):
        cur = lines[i]
        while len(cur) == 79 and i + 1 < len(lines) and lines[i + 1] and not re.match(r"^(l\.\d+|!|LaTeX|Package|Overfull|Underfull|\(\./|Document Class)", lines[i + 1]):
            i += 1
            cur += lines[i]
        out.append(cur)
        i += 1
    return out


def classify_error(msg):
    m = msg.strip()
    low = m.lower()
    c = lambda code, **kw: (code, kw)
    mm = re.search(r"Undefined control sequence", m)
    if mm:
        return c("undefined_cs")
    mm = re.search(r"File [`'\"]?([^'\"` ]+)['\"]? not found", m)
    if mm:
        f = mm.group(1)
        return c("missing_file", name=f, kind=("package" if f.endswith(".sty") else "class" if f.endswith(".cls") else "file"))
    if "LaTeX Error: Environment" in m and "undefined" in m:
        return c("undefined_env", name=(re.search(r"Environment ([\w*@-]+)", m) or [None, ""])[1])
    mm = re.search(r"\\begin\{([\w*]+)\}(?: on input line (\d+))? ended by \\end\{([\w*]+)\}", m)
    if mm:
        return c("env_mismatch", opened=mm.group(1), closed=mm.group(3), opened_line=int(mm.group(2)) if mm.group(2) else None)
    if "Bad math environment delimiter" in m:
        return c("bad_math_env")
    if "Missing $ inserted" in m:
        return c("missing_dollar")
    if "Runaway argument" in m or "Paragraph ended before" in m:
        return c("runaway")
    if "File ended while scanning" in m:
        return c("file_ended")
    if "Extra }, or forgotten" in m or "Too many }'s" in m or "Extra \\endgroup" in m:
        return c("extra_brace")
    if "Missing } inserted" in m or "Missing \\endgroup inserted" in m or "Missing { inserted" in m:
        return c("missing_brace")
    if "Misplaced alignment tab character" in m:
        return c("alignment_tab")
    if "Extra alignment tab has been changed to \\cr" in m:
        return c("extra_alignment")
    if "Misplaced \\noalign" in m or "Misplaced \\omit" in m:
        return c("misplaced_noalign")
    if "Illegal parameter number" in m or "Parameter character" in m:
        return c("parameter_error")
    if "Missing number, treated as zero" in m or "Illegal unit of measure" in m:
        return c("dimension_error")
    if "Double subscript" in m or "Double superscript" in m:
        return c("double_script")
    if "Command \\" in m and "already defined" in m:
        return c("already_defined", name=(re.search(r"Command (\\\S+) already", m) or [None, ""])[1])
    if "Can be used only in preamble" in m:
        return c("preamble_only")
    if "Lonely \\item" in m:
        return c("lonely_item")
    if "Option clash for package" in m:
        return c("option_clash", name=(re.search(r"package ([\w-]+)", m) or [None, ""])[1])
    if "Unicode character" in m or "inputenc Error" in m or "Invalid UTF-8" in m:
        return c("unicode")
    if "Package" in m and "Error" in m:
        mm = re.match(r"Package ([\w@.\-]+) Error", m)
        return c("package_error", name=mm.group(1) if mm else "")
    if "Emergency stop" in m or "Fatal error" in m or "no output PDF" in low:
        return c("fatal")
    if "Float(s) lost" in m or "Too many unprocessed floats" in m:
        return c("float_overflow")
    if "Not in outer par mode" in m:
        return c("float_in_box")
    if "Something's wrong--perhaps a missing \\item" in m:
        return c("missing_item")
    if "Text line contains an invalid character" in m:
        return c("invalid_char")
    if "Argument of" in m and "has an extra }" in m:
        return c("extra_brace")
    if "LaTeX Error:" in m:
        return c("latex_error")
    return c("error")


def classify_warning(msg):
    m = msg
    mm = re.search(r"Reference [`']([^']*)' on page (\d+) undefined", m)
    if mm:
        return "undefined_ref", {"label": mm.group(1)}
    mm = re.search(r"Citation [`']([^']*)' (?:on page \d+ )?undefined", m)
    if mm:
        return "undefined_cite", {"key": mm.group(1)}
    mm = re.search(r"Label [`']([^']*)' multiply defined", m)
    if mm:
        return "multiply_defined", {"label": mm.group(1)}
    if "There were undefined references" in m:
        return "undefined_refs_summary", {}
    if "There were undefined citations" in m or "undefined citations" in m:
        return "undefined_cites_summary", {}
    if "Rerun to get" in m or "Label(s) may have changed" in m or "Rerun LaTeX" in m:
        return "rerun", {}
    if "float specifier changed" in m:
        return "float_specifier", {}
    if "Float too large" in m:
        return "float_too_large", {}
    if "Font shape" in m and "undefined" in m:
        return "font_shape", {}
    if "Missing character" in m:
        return "missing_glyph", {}
    if "Token not allowed in a PDF string" in m:
        return "pdf_string", {}
    if "Command \\" in m and "invalid in math mode" in m:
        return "invalid_in_math", {}
    if "Unused global option" in m:
        return "unused_option", {}
    if "Empty bibliography" in m or "no \\citation" in m.lower():
        return "empty_bibliography", {}
    if "Citation" in m and "undefined" in m:
        return "undefined_cite", {"key": ""}
    if "Writing file" in m or "Hyper reference" in m:
        return "pdf_reference", {}
    if "Oversized" in m or "too wide" in m:
        return "overfull_like", {}
    return "warning", {}


def parse_log(text, main_file=""):
    lines = unwrap(text)
    diags, stack, files, pkgs = [], [], [], OrderedDict()
    i, n = 0, len(lines)
    rerun = fatal = False
    last_file = main_file

    def cur_file():
        return stack[-1] if stack else last_file

    def feed_parens(s):
        nonlocal last_file
        k = 0
        while k < len(s):
            ch = s[k]
            if ch == "(":
                m = RX_FILE_OPEN.match(s, k)
                if m:
                    f = m.group(1)
                    stack.append(f)
                    last_file = f
                    if f not in files:
                        files.append(f)
                    k = m.end()
                    continue
                stack.append(None)
            elif ch == ")":
                if stack:
                    stack.pop()
            k += 1

    def real_file():
        for f in reversed(stack):
            if f:
                return f
        return last_file

    while i < n:
        ln = lines[i]
        s = ln.rstrip()
        # ---- errors with file:line prefix
        m = RX_ERR_FLE.match(s)
        if m and not s.startswith(("l.", "LaTeX", "Package", "Overfull", "Underfull")) and not re.match(r"^\s", s) and re.search(r"\.(?:tex|sty|cls|ltx|bbl|aux|def|cfg|clo|fd)$", m.group("file")):
            msg = m.group("msg")
            ctx, j = [], i + 1
            block = []
            while j < n and not lines[j].startswith(("./", "!")) and not RX_ERR_FLE.match(lines[j]) and j - i < 60:
                block.append(lines[j])
                if RX_LINE.match(lines[j]):
                    ctx.append(lines[j])
                    if j + 1 < n and lines[j + 1].strip() != "" and not RX_ERR_FLE.match(lines[j + 1]):
                        ctx.append(lines[j + 1])
                    break
                j += 1
            code, kw = classify_error(msg)
            extra = [b for b in block if b.strip()]
            # a package error carries its message on the next lines
            if code in ("package_error", "latex_error", "error") and extra:
                msg = (msg + " " + extra[0].strip())[:300]
            diags.append({"kind": "error", "code": code, "message": msg.strip(), "file": norm_path(m.group("file")), "line": int(m.group("line")), "context": " | ".join(c.strip() for c in ctx)[:200], "detail": kw, "cascade": False, "order": len(diags)})
            if "Emergency stop" in msg or "Fatal error" in msg:
                fatal = True
            i = j + 1 if ctx else i + 1
            continue
        m = RX_ERR_CLASSIC.match(s)
        if m and not s.startswith("! =>"):
            msg = m.group("msg")
            ctx, j = [], i + 1
            lnum = None
            while j < n and j - i < 40:
                ml = RX_LINE.match(lines[j])
                if ml:
                    lnum = int(ml.group(1))
                    ctx = [lines[j]] + ([lines[j + 1]] if j + 1 < n else [])
                    break
                if lines[j].startswith("!"):
                    break
                j += 1
            code, kw = classify_error(msg)
            diags.append({"kind": "error", "code": code, "message": msg.strip(), "file": norm_path(real_file()), "line": lnum, "context": " | ".join(c.strip() for c in ctx)[:200], "detail": kw, "cascade": False, "order": len(diags)})
            if "Emergency stop" in msg or "Fatal error" in msg:
                fatal = True
            i = j + 1
            continue
        # ---- warnings (possibly continued by "(name)" lines)
        mw = RX_WARN.match(s)
        if mw and mw.group("kind") in ("Warning", "Error", "Info") or (mw and s.startswith(("LaTeX Warning:", "LaTeX Font Warning:"))):
            msg = mw.group("msg")
            j = i + 1
            while j < n and (re.match(r"^\([\w@.\-]+\)\s", lines[j]) or (lines[j].startswith("  ") and lines[j].strip() and j - i < 6 and not lines[j].lstrip().startswith(("(", "l."))) ):
                msg += " " + re.sub(r"^\([\w@.\-]+\)\s+", "", lines[j]).strip()
                j += 1
            lm = re.search(r"input line (\d+)", msg)
            kind = (mw.group("kind") or "Warning")
            if kind == "Info":
                i = j
                continue
            code, kw = classify_warning(msg)
            if kind == "Error":
                ecode, ekw = classify_error(s)
                diags.append({"kind": "error", "code": "package_error", "message": s.strip()[:300], "file": norm_path(real_file()), "line": int(lm.group(1)) if lm else None, "context": "", "detail": {"name": mw.group("who")}, "cascade": False, "order": len(diags)})
            else:
                diags.append({"kind": "warning", "code": code, "message": re.sub(r"\s+", " ", (mw.group("who") + " Warning: " + msg)).strip()[:300], "file": norm_path(real_file()), "line": int(lm.group(1)) if lm else None, "context": "", "detail": kw, "cascade": False, "order": len(diags)})
                if code == "rerun":
                    rerun = True
            i = j
            continue
        mo = RX_OVERFULL.match(s)
        if mo:
            l1 = mo.group("l1") or mo.group("l3") or mo.group("l4")
            amt = mo.group("amt")
            pt = re.search(r"([\d.]+)pt too (?:wide|high)", amt)
            bad = re.search(r"badness (\d+)", amt)
            ctx = ""
            if i + 1 < n and lines[i + 1].strip().startswith(("[]", "\\", "[")):
                ctx = lines[i + 1].strip()[:100]
            diags.append({"kind": "badbox", "code": mo.group(1).lower() + "_" + mo.group(2) + "box", "message": s.strip()[:200], "file": norm_path(real_file()), "line": int(l1) if l1 else None, "line_end": int(mo.group("l2")) if mo.group("l2") else None,
                          "context": ctx, "detail": {"pt": float(pt.group(1)) if pt else None, "badness": int(bad.group(1)) if bad else None}, "cascade": False, "order": len(diags)})
            i += 1
            continue
        mp = RX_PKGLINE.match(s)
        if mp and not stack_is_message(s):
            nm = mp.group("name")
            rest = mp.group("rest")
            mv = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2})\s*(?:v|version )?([\w.\-]+)?", rest)
            if nm and nm not in pkgs and (s.startswith("Package:") or s.startswith("Document Class:") or s.startswith("File:")):
                pkgs[nm] = (mv.group(1) + (" " + mv.group(2) if mv and mv.group(2) else "")) if mv else rest[:40].strip()
        mm = RX_BIBTEX_ERR.match(s)
        if mm and ("bibtex" in text[:200].lower() or "BibTeX" in text[:300] or "This is BibTeX" in text[:300] or s.startswith(("I ", "Warning--", "Repeated"))):
            diags.append({"kind": "error" if not s.startswith("Warning--") else "warning", "code": "bibtex_" + ("warning" if s.startswith("Warning--") else "error"), "message": s.strip(), "file": "(bibtex)", "line": None, "context": "", "detail": {}, "cascade": False, "order": len(diags)})
        if not (s.startswith(("LaTeX", "Package", "Overfull", "Underfull", "Class")) or re.match(r"^\([\w@.\-]+\)\s", s)):
            feed_parens(s)
        i += 1
    mark_cascades(diags)
    return {"diagnostics": diags, "files": files, "packages": dict(pkgs), "rerun": rerun, "fatal": fatal or any(d["code"] == "fatal" for d in diags)}


def stack_is_message(s):
    return False


def norm_path(p):
    if not p:
        return p
    p = re.sub(r"^\./", "", p)
    return p


GLOBAL_CORRUPTING = {"runaway", "file_ended", "env_mismatch", "extra_brace", "missing_brace", "paragraph_ended"}
INDEPENDENT = {"undefined_cs", "missing_file", "undefined_env", "bibtex_error", "bibtex_warning", "option_clash", "already_defined", "package_error", "preamble_only", "unicode", "fatal"}


def mark_cascades(diags):
    """A structural error (an argument or brace never closed, \\begin ended by the wrong \\end) corrupts the parse of everything after it, so the errors that TeX reports afterwards - except
    undefined commands, missing files / packages and similar independent problems - are probably its consequences. Local errors (missing $, alignment tab) only drag along the ones in the same file after them."""
    errs = [d for d in diags if d["kind"] == "error" and d["code"] != "fatal"]
    g = next((d for d in errs if d["code"] in GLOBAL_CORRUPTING), None)
    if g is not None:
        seen = False
        for d in errs:
            if d is g:
                seen = True
                continue
            if seen and d["code"] not in INDEPENDENT:
                d["cascade"] = True
    # a local error followed, in the same file, by structural / local noise
    first_local = None
    for d in errs:
        if d["cascade"]:
            continue
        if first_local is None and d["code"] in ("missing_dollar", "alignment_tab", "double_script", "dimension_error", "extra_alignment", "bad_math_env"):
            first_local = d
            continue
        if first_local is not None and d["file"] == first_local["file"] and (d["line"] or 0) >= (first_local["line"] or 0) and d["code"] in ("missing_dollar", "extra_alignment", "missing_item", "bad_math_env", "double_script") and d is not g:
            d["cascade"] = True


def root_causes(diags):
    """-> list of {code, summary, where, fix, members, severity}: undefined commands grouped, cascades folded into the first structural error"""
    errs = [d for d in diags if d["kind"] == "error" and d["code"] != "fatal"]
    out, seen_cs = [], defaultdict(list)
    for d in errs:
        if d["cascade"]:
            continue
        if d["code"] == "undefined_cs" and _cs_name(d) in CORE_CS:
            continue  # a core command that is "undefined" only because an earlier error left TeX in a broken state
        if d["code"] == "undefined_cs":
            cmd = re.search(r"(\\[A-Za-z@]+|\\.)\s*$", d.get("context", "").split("|")[0].strip()) or re.search(r"(\\[A-Za-z@]+)", d.get("context", ""))
            name = cmd.group(1).lstrip("\\") if cmd else "?"
            seen_cs[name].append(d)
            continue
        out.append(describe(d))
    for name, ds in seen_cs.items():
        pk = CMD_PACKAGES.get(name)
        out.append({"code": "undefined_cs", "severity": "error", "summary": "undefined command \\%s (%d use%s)" % (name, len(ds), "s" if len(ds) > 1 else ""), "where": "%s:%s" % (ds[0]["file"], ds[0]["line"]), "file": ds[0]["file"], "line": ds[0]["line"],
                    "fix": ("\\%s comes from package %s: add \\usepackage{%s} to the preamble" % (name, pk, pk.split(" ")[0]) if pk else "\\%s is not defined: check for a misspelling, a package that defines it, or a command whose \\newcommand is missing" % name), "members": len(ds), "order": ds[0]["order"]})
    casc = [d for d in errs if d["cascade"]]
    out.sort(key=lambda r: r["order"])
    if casc and out:
        out[0]["consequences"] = len(casc)
    return out


def _cs_name(d):
    cmd = re.search(r"(\\[A-Za-z@]+|\\.)\s*$", d.get("context", "").split("|")[0].strip()) or re.search(r"(\\[A-Za-z@]+)", d.get("context", ""))
    return cmd.group(1).lstrip("\\") if cmd else "?"


def describe(d):
    code, det = d["code"], d.get("detail") or {}
    fix = ""
    if code == "missing_file":
        nm, kind = det.get("name", ""), det.get("kind", "file")
        base = nm.replace(".sty", "").replace(".cls", "")
        fix = {"package": "package %s is not installed in this TeX distribution (tlmgr install %s) or the name in \\usepackage is wrong" % (base, base),
               "class": "class %s is not installed: put the .cls next to the source or install it (tlmgr install %s)" % (base, base),
               "file": "file %s is missing or its path / extension is wrong (check \\graphicspath, relative paths, upper / lower case)" % nm}[kind]
    elif code == "env_mismatch":
        fix = "\\begin{%s}%s is closed by \\end{%s}: make the pair match (one of them is a typo or a \\end is missing)" % (det.get("opened"), (" (line %s)" % det["opened_line"]) if det.get("opened_line") else "", det.get("closed"))
    elif code in ("runaway", "file_ended"):
        fix = "an argument or brace was never closed: find the last \\command{ whose } is missing before this point (the static check lists unbalanced braces per file)"
    elif code == "missing_dollar":
        fix = "math mode needed: a math symbol (_, ^, \\alpha ...) outside $...$, or an unescaped underscore in text (write \\_ ), or $ unbalanced"
    elif code == "alignment_tab":
        fix = "an & outside a table / align environment: write \\& for a literal ampersand"
    elif code == "extra_brace":
        fix = "a } closes more than was opened: remove it or add the missing {"
    elif code == "undefined_env":
        fix = "environment %s is not defined: load the package that defines it (e.g. algorithm, theorem via amsthm, subfigure ...) or fix the name" % det.get("name", "")
    elif code == "unicode":
        fix = "a character outside the font / input encoding: use xelatex / lualatex with fontspec (or ctex for Chinese), or replace the character with a LaTeX command"
    elif code == "option_clash":
        fix = "package %s is loaded twice with different options: load it once, with all options, before any package that loads it implicitly" % det.get("name", "")
    elif code == "already_defined":
        fix = "%s already exists: use \\renewcommand, or pick another name" % det.get("name", "")
    elif code == "bad_math_env":
        fix = "math environment opened and closed with different delimiters (check $ / \\( / \\[ / equation pairs above)"
    elif code == "float_overflow":
        fix = "too many floats waiting: add \\clearpage / \\FloatBarrier, loosen placement ([htbp]), or shrink / move floats"
    elif code == "bibtex_error":
        fix = "BibTeX could not process the database / style: check the \\bibliography{...} names and the .bib syntax at the line named"
    return {"code": code, "severity": d["kind"], "summary": d["message"][:160], "where": "%s:%s" % (d["file"], d["line"]), "file": d["file"], "line": d["line"], "fix": fix, "context": d.get("context", ""), "members": 1, "order": d["order"]}


def summary(parsed):
    c = defaultdict(int)
    for d in parsed["diagnostics"]:
        c[d["kind"]] += 1
    return dict(c)
