#!/usr/bin/env python3
"""tx.py - tex-ledger: make a LaTeX project compile, fix it with checked edits, and hand over sources whose build can be repeated.

The project is copied (the original is never touched). `run` compiles it as a reproducible build would, reads the log into root causes (a closed brace missing in an included file is reported once,
with the errors it caused folded under it), runs static checks that need no TeX, and prints the brief. You edit the copy; `check` recompiles and shows what was fixed, what is new and what remains;
`fix` applies deterministic fixes one rule at a time and keeps each only if the compile does not get worse; `build` writes the final sources, the PDF, the build report (engine, packages with
versions, passes, commands, PDF hash twice), the change log with diffs, repeat-build files and result.json.

  tx.py run [--case /input/case.json] [--src DIR|FILE|ZIP] --out OUT [--engine E] [--no-compile]
  tx.py diag W | lint W | check W | fix W [--unverified] | build W --out OUT [--case ...] [--answers a.json]
  tx.py template W --template DIR     compare the manuscript's front matter with a template's; `adapt` writes the manuscript into the template (experimental)
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import sys
import zipfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import texlog  # noqa: E402
import texrun  # noqa: E402
import texsrc  # noqa: E402

VERSION = "1.0.0"
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "build", "_build", "out", "output", ".work", ".idea", ".vscode"}
COPY_EXT_SKIP = (".aux", ".log", ".out", ".toc", ".lof", ".lot", ".blg", ".fls", ".fdb_latexmk", ".synctex.gz", ".bbl-SAVE-ERROR", ".pyc", ".DS_Store")


# ------------------------------------------------------------------------------------------------ io
def jload(p, default=None):
    if not os.path.isfile(p):
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def jsave(p, obj):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, p)


def wtext(p, text):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def rtext(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def find_key(obj, names):
    if isinstance(obj, dict):
        for k in names:
            if k in obj:
                return obj[k]
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


def strings(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


# ------------------------------------------------------------------------------------------------ project intake
def safe_unzip(path, dest):
    with zipfile.ZipFile(path) as z:
        total = 0
        for info in z.infolist():
            target = os.path.normpath(os.path.join(dest, info.filename))
            if not target.startswith(os.path.abspath(dest) + os.sep) and target != os.path.abspath(dest):
                raise SystemExit("ERROR: the archive contains a path outside the folder: %s" % info.filename)
            total += info.file_size
            if total > 300_000_000:
                raise SystemExit("ERROR: the archive is larger than 300 MB when unpacked")
        z.extractall(dest)


def locate_source(a):
    """-> directory that holds the project (maybe unpacked from a zip) and the case dict"""
    case = jload(a.case) if a.case and os.path.isfile(a.case) else None
    base = os.path.dirname(os.path.abspath(a.case)) if a.case else "/input"
    cands = []
    if a.src:
        cands.append(os.path.abspath(a.src))
    if case:
        for key, val in strings(case):
            if len(val) < 300 and re.search(r"\.(?:tex|zip|tar\.gz)$|^[\w./-]+$", val.strip()):
                for root in (base, os.getcwd()):
                    p = val if os.path.isabs(val) else os.path.join(root, val)
                    if os.path.exists(p):
                        cands.append(os.path.abspath(p))
                        break
    cands.append(base)
    cands.append("/input")
    for c in cands:
        if os.path.isfile(c) and c.lower().endswith(".zip"):
            d = os.path.join(a.work, "unzipped")
            shutil.rmtree(d, ignore_errors=True)
            safe_unzip(c, d)
            kids = [k for k in os.listdir(d) if not k.startswith(".") and k != "__MACOSX"]
            if len(kids) == 1 and os.path.isdir(os.path.join(d, kids[0])):
                return os.path.join(d, kids[0]), case
            return d, case
        if os.path.isfile(c) and c.lower().endswith(".tex"):
            return os.path.dirname(c), case
        if os.path.isdir(c):
            has = [f for dp, dn, fn in os.walk(c) for f in fn if f.endswith(".tex")]
            if has:
                zips = [f for f in os.listdir(c) if f.lower().endswith(".zip")]
                if not has and zips:
                    continue
                return c, case
            zips = [os.path.join(c, f) for f in sorted(os.listdir(c)) if f.lower().endswith(".zip")]
            if zips:
                d = os.path.join(a.work, "unzipped")
                shutil.rmtree(d, ignore_errors=True)
                safe_unzip(zips[0], d)
                kids = [k for k in os.listdir(d) if not k.startswith(".") and k != "__MACOSX"]
                return (os.path.join(d, kids[0]) if len(kids) == 1 and os.path.isdir(os.path.join(d, kids[0])) else d), case
    raise SystemExit("ERROR: no LaTeX project found (looked at --src, the case's paths, %s and /input): pass --src DIR|FILE.tex|ZIP" % base)


def copy_tree(src, dst):
    shutil.rmtree(dst, ignore_errors=True)
    n = 0
    for dp, dn, fn in os.walk(src):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        rel = os.path.relpath(dp, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in fn:
            if f.endswith(COPY_EXT_SKIP) or f.startswith(".") or os.path.getsize(os.path.join(dp, f)) > 50_000_000:
                continue
            shutil.copy2(os.path.join(dp, f), os.path.join(dst, rel, f))
            n += 1
            if n > 4000:
                raise SystemExit("ERROR: more than 4000 files: pass the project folder, not a whole drive")
    return n


def task_info(case, roots):
    text = ""
    for root in roots:
        p = os.path.join(root, "task.md")
        if os.path.isfile(p):
            text = rtext(p)
            break
    if case:
        for key, val in strings(case):
            if re.search(r"task|instruction|prompt|requirement|任务|要求|说明|description", key, re.I) and len(val) > 15:
                text += "\n" + val
    engine = None
    for rx, e in ((r"xelatex|XeLaTeX|XeTeX", "xelatex"), (r"lualatex|LuaLaTeX|LuaTeX", "lualatex"), (r"pdflatex|pdfLaTeX|pdfTeX", "pdflatex")):
        if re.search(rx, text):
            engine = e
            break
    tmpl = re.search(r"(IEEEtran|IEEE ?(?:Transactions|Access)|ACM ?(?:sig\w*|art)|acmart|elsarticle|Elsevier|Springer|svjour3|llncs|LNCS|NeurIPS|ICML|ICLR|CVPR|AAAI|ctexart|ctexrep|ctexbook|revtex|REVTeX|aastex|copernicus|iopart|mdpi|MDPI|Frontiers|wileyNJD|bmcart|thesis|学位论文|期刊模板|会议模板)", text)
    return {"text": text.strip()[:6000], "engine": engine, "template": tmpl.group(1) if tmpl else None}


# ------------------------------------------------------------------------------------------------ state
def load(work):
    st = jload(os.path.join(work, "state.json"))
    if st is None:
        raise SystemExit("no state.json in %s: run `run` first" % work)
    return st


def save(work, st):
    jsave(os.path.join(work, "state.json"), st)


def sig(d):
    return (d["code"], d["file"], re.sub(r"\d+", "#", d["message"])[:60])


def score(res):
    """(errors, undefined references and citations, bibliography errors): lower is better"""
    if not res.get("parsed"):
        return (10 ** 6, 0, 0)
    d = res["parsed"]["diagnostics"]
    return (sum(1 for x in d if x["kind"] == "error" and not x["code"].startswith("bibtex")) + (0 if res.get("pdf") else 1), sum(1 for x in d if x["code"] in ("undefined_ref", "undefined_cite")), len(res["bib"]["errors"]))


def summarize_compile(res):
    if not res.get("parsed"):
        return {"status": res.get("status"), "errors": None, "warnings": None, "passes": len(res.get("passes", [])), "converged": res.get("converged")}
    d = res["parsed"]["diagnostics"]
    return {"status": res["status"], "engine": res["engine"], "errors": sum(1 for x in d if x["kind"] == "error"), "warnings": sum(1 for x in d if x["kind"] == "warning"), "badboxes": sum(1 for x in d if x["kind"] == "badbox"),
            "undefined": sum(1 for x in d if x["code"] in ("undefined_ref", "undefined_cite")), "passes": len([p for p in res["passes"] if p["command"].startswith(("pdflatex", "xelatex", "lualatex"))]), "converged": res["converged"],
            "bib_tool": res["bib"].get("tool"), "bib_errors": len(res["bib"]["errors"]), "pdf": bool(res.get("pdf"))}


def do_compile(work, st, tools=None):
    src = os.path.join(work, "src")
    tools = tools or texrun.find_tex(st.get("texbin"))
    res = texrun.compile_project(src, st["main"], st["engine"], tools, source_epoch=st.get("source_epoch"))
    return res


def context_lines(src, file, line, n=1):
    p = os.path.join(src, file or "")
    if not file or not line or not os.path.isfile(p):
        return []
    lines = rtext(p).split("\n")
    return ["%4d| %s" % (k + 1, lines[k][:140]) for k in range(max(0, line - 1 - n), min(len(lines), line + n))]


# ------------------------------------------------------------------------------------------------ run / brief
FOLDABLE = {"float_in_box", "dimension_error", "extra_alignment", "alignment_tab", "lonely_item", "missing_item", "undefined_env", "bad_math_env", "double_script", "parameter_error", "misplaced_noalign", "extra_brace", "missing_brace", "error", "missing_dollar"}


def link_roots(roots, proj, lint_issues):
    """a runaway / file-ended error is reported where TeX noticed it; the unclosed brace the static scan found is where it starts.
    Errors TeX reported between that place and the point where it gave up (inside the runaway argument) are consequences of it and are folded under it."""
    _link_roots(roots, proj, lint_issues)
    for r in list(roots):
        ls = r.get("likely_source") or ""
        m = re.match(r"([^:\s]+):(\d+) ", ls)
        if r["code"] in ("runaway", "file_ended", "extra_brace", "missing_brace") and m:
            sf, sl = m.group(1), int(m.group(2))
            for o in list(roots):
                if o is not r and o["code"] in FOLDABLE and o.get("file") == sf and (o.get("line") or 0) >= sl:
                    roots.remove(o)
                    r["consequences"] = r.get("consequences", 0) + o.get("members", 1)


def _link_roots(roots, proj, lint_issues):
    for r in roots:
        if r["code"] in ("runaway", "file_ended", "extra_brace", "missing_brace"):
            cand = [i for i in lint_issues if i["code"] in ("unclosed_brace", "extra_brace") ]
            if cand:
                r["likely_source"] = "%s:%s (%s)" % (cand[0]["file"], cand[0]["line"], cand[0]["message"][:70])
        if r["code"] == "env_mismatch":
            cand = [i for i in lint_issues if i["code"] in ("env_mismatch", "env_unclosed")]
            if cand:
                r["likely_source"] = "%s:%s (%s)" % (cand[0]["file"], cand[0]["line"], cand[0]["message"][:70])
        if r["code"] == "missing_dollar":
            cand = [i for i in lint_issues if i["code"] in ("underscore_in_text", "odd_dollar")]
            if cand:
                r["likely_source"] = "%s:%s (%s)" % (cand[0]["file"], cand[0]["line"], cand[0]["message"][:70])


def brief_text(work, st, res, lint_issues, roots):
    L = ["# Build brief (generated)\n"]
    t = st["task"]
    L.append("## Task\n- engine named in the task: %s | template named: %s\n%s\n" % (t["engine"] or "none", t["template"] or "none", ("```\n" + t["text"][:1000] + "\n```") if t["text"] else "- no task text"))
    L.append("## Project\n- main: %s | files: %s | bibliographies: %s\n- engine: %s (%s)\n- missing inputs: %s" % (st["main"], ", ".join(st["files"][:12]), ", ".join(st["bibs"]) or "none", st["engine"], st["engine_reason"], ", ".join("%s:%s %s" % x for x in st["missing_inputs"][:8]) or "none"))
    tools = st["tools"]
    L.append("- TeX on this machine: %s" % (", ".join("%s (%s)" % (k, v.split("(")[0].strip()[:40]) for k, v in tools["versions"].items()) or "NOT FOUND: static checks only"))
    cs = st["baseline"]
    L.append("\n## Baseline build\n- %s" % json.dumps(cs, ensure_ascii=False))
    if res and res.get("passes"):
        for p in res["passes"]:
            L.append("  - pass %d: `%s` %.1fs errors %d warnings %d undefined %d%s%s" % (p["n"], p["command"][:60], p["seconds"], p["errors"], p["warnings"], p["undefined"], " rerun requested" if p["rerun_requested"] else "", (" changed " + ",".join(p["changed"])) if p["changed"] else ""))
        for n in res["notes"]:
            L.append("  - NOTE: " + n)
    L.append("\n## Root causes (%d; errors that only follow another are folded under it)" % len(roots))
    for k, r in enumerate(roots, 1):
        L.append("%d. [%s] %s at %s%s" % (k, r["code"], r["summary"][:110], r["where"], (" - %d later error(s) are consequences" % r["consequences"]) if r.get("consequences") else ""))
        if r.get("likely_source"):
            L.append("   likely starts at: %s" % r["likely_source"])
        if r.get("fix"):
            L.append("   fix: %s" % r["fix"])
        for cl in context_lines(os.path.join(work, "src"), r.get("file"), r.get("line"))[:3]:
            L.append("   " + cl)
    if res and res.get("parsed"):
        d = res["parsed"]["diagnostics"]
        warn = Counter(x["code"] for x in d if x["kind"] == "warning")
        L.append("\n## Warnings: %s" % dict(warn))
        for x in [x for x in d if x["code"] in ("undefined_ref", "undefined_cite", "multiply_defined")][:8]:
            L.append("- %s:%s %s" % (x["file"], x["line"], x["message"][:110]))
        bb = sorted([x for x in d if x["kind"] == "badbox" and (x["detail"].get("pt") or 0) > 10], key=lambda x: -(x["detail"].get("pt") or 0))[:5]
        for x in bb:
            L.append("- %s:%s %s" % (x["file"], x["line"], x["message"][:100]))
        if res["bib"].get("errors"):
            L.append("- bibliography (%s): %s" % (res["bib"]["tool"], "; ".join(res["bib"]["errors"][:3])))
    e = [i for i in lint_issues if i["severity"] == "error"]
    w = [i for i in lint_issues if i["severity"] == "warn"]
    L.append("\n## Static checks (no TeX needed): %d errors, %d warnings, %d notes" % (len(e), len(w), len(lint_issues) - len(e) - len(w)))
    for i in (e + w)[:25]:
        L.append("- %s %s:%s [%s] %s%s" % (i["severity"], i["file"], i["line"], i["code"], i["message"][:120], (" -> " + i["fix"][:80]) if i["fix"] else ""))
    return "\n".join(L) + "\n"


def cmd_run(a):
    os.makedirs(a.out, exist_ok=True)
    a.work = a.work or os.path.join(a.out, ".work")
    os.makedirs(a.work, exist_ok=True)
    srcdir, case = locate_source(a)
    n = copy_tree(srcdir, os.path.join(a.work, "src"))
    copy_tree(srcdir, os.path.join(a.work, "orig"))
    roots = [os.path.dirname(os.path.abspath(a.case))] if a.case else ["/input"]
    task = task_info(case, roots + [srcdir])
    proj = texsrc.Project(os.path.join(a.work, "src"), a.main)
    if not proj.main:
        raise SystemExit("ERROR: no .tex file with \\documentclass in %s (%d files copied)" % (srcdir, n))
    eng, why = proj.engine()
    if a.engine:
        eng, why = a.engine, "--engine"
    elif task["engine"]:
        eng, why = task["engine"], "named in the task"
    tools = texrun.find_tex(a.texbin)
    st = {"version": VERSION, "main": proj.main, "files": proj.order, "bibs": list(proj.bibs), "missing_inputs": proj.missing_inputs, "engine": eng, "engine_reason": why, "task": task, "case": case, "case_id": (find_key(case, ["case_id", "caseId"]) or find_key(case, ["id"])) if case else None,
          "tools": {"versions": tools["versions"], "have": {k: bool(v) for k, v in tools.items() if k != "versions"}}, "texbin": a.texbin, "source": os.path.basename(srcdir.rstrip("/")), "changes": [], "applied_rules": []}
    lint_issues = texsrc.lint(proj, eng)
    res = None
    if a.no_compile:
        st["baseline"] = {"status": "not_compiled", "note": "--no-compile"}
    else:
        res = do_compile(a.work, st, tools)
        st["baseline"] = summarize_compile(res)
        st["source_epoch"] = res.get("source_epoch")
    st["baseline_sig"] = [list(sig(d)) for d in (res["parsed"]["diagnostics"] if res and res.get("parsed") else []) if d["kind"] == "error"]
    st["baseline_score"] = list(score(res)) if res else None
    roots_ = texlog.root_causes(res["parsed"]["diagnostics"]) if res and res.get("parsed") else []
    link_roots(roots_, proj, lint_issues)
    save(a.work, st)
    jsave(os.path.join(a.work, "baseline_diag.json"), {"roots": roots_, "lint": lint_issues, "compile": st["baseline"]})
    txt = brief_text(a.work, st, res, lint_issues, roots_)
    wtext(os.path.join(a.out, "brief.md"), txt)
    print(txt)
    print("[brief written to %s; the working copy is %s]" % (os.path.join(a.out, "brief.md"), os.path.join(a.work, "src")))
    print("Next: edit the working copy (or `fix --safe`), `check` after each change, then `build`.")


def cmd_diag(a):
    st = load(a.work)
    res = do_compile(a.work, st)
    d = res["parsed"]["diagnostics"] if res.get("parsed") else []
    roots = texlog.root_causes(d)
    proj = texsrc.Project(os.path.join(a.work, "src"), st["main"])
    link_roots(roots, proj, texsrc.lint(proj, st["engine"]))
    print("compile: %s" % json.dumps(summarize_compile(res), ensure_ascii=False))
    for k, r in enumerate(roots, 1):
        print("%d. [%s] %s at %s%s" % (k, r["code"], r["summary"][:120], r["where"], (" (+%d consequences)" % r["consequences"]) if r.get("consequences") else ""))
        if r.get("likely_source"):
            print("   likely starts at: %s" % r["likely_source"])
        print("   fix: %s" % r.get("fix", ""))
        for cl in context_lines(os.path.join(a.work, "src"), r.get("file"), r.get("line"), 2):
            print("   " + cl)
    for x in d:
        if x["kind"] == "error" and x["cascade"] and a.all:
            print("   (consequence) %s:%s %s" % (x["file"], x["line"], x["message"][:100]))
    for x in d:
        if x["kind"] in ("warning", "badbox") and (a.all or x["code"] in ("undefined_ref", "undefined_cite", "multiply_defined", "missing_glyph", "float_too_large")):
            print("  %s %s:%s %s" % (x["kind"], x["file"], x["line"], x["message"][:110]))
    jsave(os.path.join(a.work, "diag.json"), {"roots": roots, "diagnostics": d})


def cmd_lint(a):
    st = load(a.work)
    proj = texsrc.Project(os.path.join(a.work, "src"), st["main"])
    iss = texsrc.lint(proj, st["engine"])
    jsave(os.path.join(a.work, "lint.json"), iss)
    c = Counter(i["severity"] for i in iss)
    print("static checks: %s" % dict(c))
    for i in iss:
        if i["severity"] != "info" or a.all:
            print("  %-5s %s:%s [%s] %s%s" % (i["severity"], i["file"], i["line"], i["code"], i["message"][:130], (" -> " + i["fix"][:80]) if i["fix"] else ""))


def cmd_check(a):
    """recompile after your edits: what is fixed, what is new, what remains"""
    st = load(a.work)
    res = do_compile(a.work, st)
    cur = summarize_compile(res)
    d = res["parsed"]["diagnostics"] if res.get("parsed") else []
    errs = [x for x in d if x["kind"] == "error"]
    base = Counter(tuple(x) for x in st.get("baseline_sig", []))
    now_c = Counter(sig(x) for x in errs)
    fixed = list((base - now_c).elements())
    new = []
    seen_new = Counter()
    for x in errs:
        k = sig(x)
        seen_new[k] += 1
        if seen_new[k] > base.get(k, 0):
            new.append(x)
    print("baseline: %s" % json.dumps(st["baseline"], ensure_ascii=False))
    print("now:      %s" % json.dumps(cur, ensure_ascii=False))
    print("errors fixed since the baseline: %d | new: %d | remaining: %d" % (len(fixed), len(new), len(errs) - len(new)))
    roots = texlog.root_causes(d)
    proj = texsrc.Project(os.path.join(a.work, "src"), st["main"])
    link_roots(roots, proj, texsrc.lint(proj, st["engine"]))
    for r in roots:
        print("  [%s] %s at %s%s%s" % (r["code"], r["summary"][:100], r["where"], (" (+%d consequences)" % r["consequences"]) if r.get("consequences") else "", ("  likely: " + r["likely_source"]) if r.get("likely_source") else ""))
        if r.get("fix"):
            print("      fix: %s" % r["fix"])
    for x in new[:5]:
        print("  NEW %s:%s %s" % (x["file"], x["line"], x["message"][:100]))
    for p in res.get("passes", []):
        print("  pass %d `%s` errors %d undefined %d%s" % (p["n"], p["command"][:40], p["errors"], p["undefined"], " rerun" if p["rerun_requested"] else ""))
    for n in res.get("notes", []):
        print("  NOTE:", n)


# ------------------------------------------------------------------------------------------------ fix
def pkg_insert(text, pkg):
    """insert \\usepackage{pkg} after the last \\usepackage / \\documentclass of the preamble (before hyperref and other late packages when pkg is not one of those)"""
    lines = text.split("\n")
    last_use, hyper, begin = None, None, None
    for k, ln in enumerate(lines):
        if re.search(r"\\begin\{document\}", ln):
            begin = k
            break
        if re.match(r"\s*\\(?:usepackage|RequirePackage)", ln):
            last_use = k
            if "hyperref" in ln and hyper is None:
                hyper = k
        elif re.match(r"\s*\\documentclass", ln) and last_use is None:
            last_use = k
    at = (hyper if hyper is not None and pkg not in texsrc.AFTER_HYPERREF_OK else (last_use + 1 if last_use is not None else 0))
    if hyper is not None and pkg not in texsrc.AFTER_HYPERREF_OK:
        at = hyper
    elif last_use is not None:
        at = last_use + 1
    lines.insert(at, "\\usepackage{%s}" % pkg)
    return "\n".join(lines)


def candidate_rules(proj, st, engine, base):
    """deterministic fixes whose problem exists in the CURRENT sources, plus a package for each command the compile log reports undefined"""
    issues = texsrc.lint(proj, engine)
    rules = texsrc.safe_fixes(proj, issues, engine)
    if base and base.get("parsed"):
        roots = texlog.root_causes(base["parsed"]["diagnostics"])
        for r in roots:
            m = re.match(r"undefined command \\(\w+)", r["summary"])
            if not m:
                continue
            p = texlog.CMD_PACKAGES.get(m.group(1), "")
            name = p.split(" ")[0] if p and not p.startswith("(") else ""
            t = proj.files[st["main"]]
            if name and name.isalpha() and not re.search(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\b%s\b[^}]*\}" % re.escape(name), t) and not any(x[0] == "missing_package_" + name for x in rules):
                new = pkg_insert(t, name)
                diff = [l for l in difflib.unified_diff(t.split("\n"), new.split("\n"), st["main"], st["main"], lineterm="", n=0) if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
                rules.append(("missing_package_" + name, {st["main"]: new}, [{"file": st["main"], "rule": "missing package: \\usepackage{%s} added (the log reports an undefined command that it defines)" % name, "diff": "\n".join(diff)}]))
    for i in issues_for_pkgs(proj, st, engine):
        name = i["package"]
        if name and not any(x[0] == "missing_package_" + name for x in rules):
            t = proj.files[st["main"]]
            if not re.search(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\b%s\b[^}]*\}" % re.escape(name), t):
                new = pkg_insert(t, name)
                diff = [l for l in difflib.unified_diff(t.split("\n"), new.split("\n"), st["main"], st["main"], lineterm="", n=0) if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
                rules.append(("missing_package_" + name, {st["main"]: new}, [{"file": st["main"], "rule": "missing package: \\usepackage{%s} added (%s is used and the package is not loaded)" % (name, i.get("command") and "\\" + i["command"] or i.get("environment")), "diff": "\n".join(diff)}]))
    return rules


def issues_for_pkgs(proj, st, engine):
    return [i for i in texsrc.lint(proj, engine) if i["code"] in ("command_needs_package", "env_needs_package")]


def cmd_fix(a):
    st = load(a.work)
    src = os.path.join(a.work, "src")
    tools = texrun.find_tex(st.get("texbin"))
    have_tex = bool(tools.get(st["engine"]) or any(tools.get(e) for e in ("pdflatex", "xelatex", "lualatex")))
    if not have_tex and not a.unverified:
        print("no TeX engine here: fixes cannot be verified by a compile; nothing applied (use --unverified to apply the deterministic fixes anyway)")
        return
    base = do_compile(a.work, st, tools) if have_tex else None
    cur_score = score(base) if base else None
    applied, skipped, tried = [], [], set()
    for _ in range(12):
        proj = texsrc.Project(src, st["main"])
        rules = [r for r in candidate_rules(proj, st, st["engine"], base) if r[0] not in tried]
        if not rules:
            break
        rule, edits, recs = rules[0]
        tried.add(rule)
        backup = {rel: rtext(os.path.join(src, rel)) for rel in edits}
        for rel, new in edits.items():
            wtext(os.path.join(src, rel), new)
        if have_tex:
            res = do_compile(a.work, st, tools)
            sc = score(res)
            ok = sc <= cur_score
        else:
            res, ok, sc = None, True, None
        if ok:
            applied.append((rule, recs, sc))
            st["changes"] += [dict(r, verified=bool(have_tex), score_before=list(cur_score) if cur_score else None, score_after=list(sc) if sc else None) for r in recs]
            st["applied_rules"].append(rule)
            if sc:
                cur_score, base = sc, res
        else:
            for rel, txt in backup.items():
                wtext(os.path.join(src, rel), txt)
            skipped.append((rule, sc, cur_score))
    save(a.work, st)
    if not applied and not skipped:
        print("no deterministic fix applies")
        return
    for rule, recs, sc in applied:
        print("APPLIED %s %s" % (rule, ("(errors / undefined refs / bibliography errors now %s)" % (sc,)) if sc else "(unverified: no TeX)"))
        for r in recs:
            print("   %s" % r["file"])
    for rule, sc, cs in skipped:
        print("REVERTED %s: the compile got worse (%s vs %s)" % (rule, sc, cs))
    if not applied:
        print("nothing kept")


# ------------------------------------------------------------------------------------------------ template
def front_matter(text):
    """what a document's front matter carries: documentclass + options, title, authors, abstract, keywords, packages"""
    body = text
    pre, _, doc = body.partition("\\begin{document}")
    out = {"class": None, "options": "", "packages": [], "macros": {}, "abstract": None, "keywords": None, "title": None}
    m = re.search(r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}", pre)
    if m:
        out["class"], out["options"] = m.group(2), m.group(1) or ""
    out["packages"] = [(p[0] or "", p[1]) for p in re.findall(r"\\usepackage(?:\[([^\]]*)\])?\{([^}]+)\}", pre)]
    for cmd in ("title", "author", "date", "affil", "affiliation", "address", "email", "keywords", "institute", "thanks", "icmltitle", "icmlauthor", "runningtitle", "shorttitle", "subtitle", "orcid", "corresp", "cortext", "tnotetext"):
        for m in re.finditer(r"\\%s(?![A-Za-z])(?:\[[^\]]*\])?\s*\{" % cmd, text):
            arg, _ = texsrc.grab_arg(text, m.end() - 1)
            if arg is not None:
                out["macros"].setdefault(cmd, []).append(arg.strip()[:400])
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.S)
    if m:
        out["abstract"] = m.group(1).strip()
    m = re.search(r"\\begin\{(?:IEEEkeywords|keyword|keywords)\}(.*?)\\end\{(?:IEEEkeywords|keyword|keywords)\}", text, re.S)
    if m:
        out["keywords"] = m.group(1).strip()
    elif out["macros"].get("keywords"):
        out["keywords"] = out["macros"]["keywords"][0]
    if out["macros"].get("title"):
        out["title"] = out["macros"]["title"][0]
    return out


def find_template_main(tdir):
    p = texsrc.Project(tdir)
    return p, p.main


def cmd_template(a):
    st = load(a.work)
    tp, tmain = find_template_main(a.template)
    if not tmain:
        raise SystemExit("ERROR: no .tex with \\documentclass in the template folder")
    t_fm = front_matter(rtext(os.path.join(a.template, tmain)))
    m_fm = front_matter(rtext(os.path.join(a.work, "src", st["main"])))
    rows = []
    for k in sorted(set(t_fm["macros"]) | set(m_fm["macros"])):
        rows.append((k, k in m_fm["macros"], k in t_fm["macros"]))
    print("template: class %s [%s], main %s, %d support files (.cls / .sty / .bst: %s)" % (t_fm["class"], t_fm["options"], tmain, len(tp.order), ", ".join(sorted(f for f in os.listdir(a.template) if f.endswith((".cls", ".sty", ".bst")))[:8]) or "none (class from the TeX distribution)"))
    print("manuscript: class %s [%s]" % (m_fm["class"], m_fm["options"]))
    print("front-matter commands (manuscript has / template uses):")
    for k, mine, theirs in rows:
        print("  \\%-14s manuscript %-3s template %-3s%s" % (k, "yes" if mine else "no", "yes" if theirs else "no", "   <- the template needs it and the manuscript has no value: ask the author" if theirs and not mine else ("   (not used by the template: drop or map it)" if mine and not theirs else "")))
    print("abstract: manuscript %s, template %s | keywords: manuscript %s, template %s" % (bool(m_fm["abstract"]), bool(t_fm["abstract"]), bool(m_fm["keywords"]), bool(t_fm["keywords"])))
    tpk = {p[1] for p in t_fm["packages"]}
    mpk = {p[1] for p in m_fm["packages"]}
    print("manuscript packages the template does not load: %s" % (", ".join(sorted(mpk - tpk)) or "none"))
    clash = [p for p in mpk if p in ("geometry", "fullpage", "a4wide", "times", "mathptmx", "newtxtext", "setspace", "titlesec", "fancyhdr", "authblk", "sectsty") ]
    if clash:
        print("layout-changing packages in the manuscript that a template normally forbids: %s" % ", ".join(clash))


def cmd_adapt(a):
    st = load(a.work)
    tdir = a.template
    tp, tmain = find_template_main(tdir)
    if not tmain:
        raise SystemExit("ERROR: no .tex with \\documentclass in the template folder")
    ttext = rtext(os.path.join(tdir, tmain))
    mtext = rtext(os.path.join(a.work, "src", st["main"]))
    mfm, tfm = front_matter(mtext), front_matter(ttext)
    out = ttext
    notes = []
    for cmd in ("title",):
        if mfm["macros"].get(cmd) and tfm["macros"].get(cmd):
            out = re.sub(r"(\\%s(?:\[[^\]]*\])?\s*\{)" % cmd, lambda m: m.group(1), out)
            arg_t, e = texsrc.grab_arg(out, re.search(r"\\%s(?![A-Za-z])" % cmd, out).end())
            s = out.index("{", re.search(r"\\%s(?![A-Za-z])" % cmd, out).end())
            out = out[:s + 1] + mfm["macros"][cmd][0] + out[e - 1:]
            notes.append("title replaced")
    if mfm["abstract"] and tfm["abstract"]:
        out = re.sub(r"(\\begin\{abstract\}).*?(\\end\{abstract\})", lambda m: m.group(1) + "\n" + mfm["abstract"] + "\n" + m.group(2), out, count=1, flags=re.S)
        notes.append("abstract replaced")
    elif mfm["abstract"]:
        notes.append("the template has no abstract environment: the abstract stays in the body")
    if mfm["keywords"] and tfm["keywords"]:
        for env in ("IEEEkeywords", "keyword", "keywords"):
            if "\\begin{%s}" % env in out:
                out = re.sub(r"(\\begin\{%s\}).*?(\\end\{%s\})" % (env, env), lambda m: m.group(1) + "\n" + mfm["keywords"] + "\n" + m.group(2), out, count=1, flags=re.S)
                notes.append("keywords replaced")
                break
        else:
            if tfm["macros"].get("keywords"):
                s = re.search(r"\\keywords\s*\{", out)
                arg, e = texsrc.grab_arg(out, s.end() - 1)
                out = out[:s.end()] + mfm["keywords"] + out[e - 1:]
                notes.append("keywords replaced")
    authors_missing = bool(mfm["macros"].get("author")) and bool(tfm["macros"].get("author"))
    if authors_missing:
        notes.append("AUTHORS NOT MAPPED: author / affiliation blocks differ between templates; the template's example authors are still there and must be replaced by hand")
    # body: from after the manuscript's front matter to before the bibliography
    mb = mtext.partition("\\begin{document}")[2]
    mb = re.sub(r"\\end\{document\}.*", "", mb, flags=re.S)
    mb = re.sub(r"\\maketitle", "", mb)
    mb = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", "", mb, flags=re.S)
    mb = re.sub(r"\\(?:begin|end)\{(?:IEEEkeywords|keyword|keywords)\}", "", mb)
    mb = re.sub(r"\\keywords\s*\{[^}]*\}", "", mb)
    mb = re.sub(r"\\(?:title|author|date|affil|address|email|thanks)(?![A-Za-z])(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", mb)
    bm = re.search(r"\\bibliographystyle|\\bibliography\{|\\printbibliography|\\begin\{thebibliography\}", mb)
    body = mb[:bm.start()] if bm else mb
    bibpart = mb[bm.start():] if bm else ""
    tdoc = out.partition("\\begin{document}")
    after = tdoc[2]
    start = 0
    m1 = re.search(r"\\end\{abstract\}|\\end\{IEEEkeywords\}|\\end\{keyword\}|\\maketitle", after)
    ends = [m.end() for m in re.finditer(r"\\end\{abstract\}|\\end\{IEEEkeywords\}|\\end\{keyword\}|\\end\{keywords\}|\\maketitle|\\keywords\s*\{(?:[^{}])*\}", after)]
    start = max(ends) if ends else 0
    tb = re.search(r"\\bibliographystyle|\\bibliography\{|\\printbibliography|\\begin\{thebibliography\}|\\end\{document\}", after[start:])
    stop = start + tb.start() if tb else len(after)
    new_after = after[:start] + "\n" + body.strip() + "\n\n" + (bibpart.strip() + "\n" if bibpart.strip() and not re.search(r"\\bibliographystyle|\\bibliography\{|\\printbibliography", after[stop:]) else "") + after[stop:]
    if bibpart and re.search(r"\\bibliography\{", after[stop:]):
        mine = re.search(r"\\bibliography\{([^}]*)\}", bibpart)
        if mine:
            new_after = re.sub(r"\\bibliography\{[^}]*\}", lambda m: "\\bibliography{%s}" % mine.group(1), new_after, count=1)
            notes.append("\\bibliography now points at the manuscript's .bib")
    out = tdoc[0] + "\\begin{document}" + new_after
    # packages and definitions of the manuscript the template lacks
    mpre = mtext.partition("\\begin{document}")[0]
    tpk = {p[1] for p in tfm["packages"]}
    skip = {"geometry", "fullpage", "a4wide", "times", "mathptmx", "newtxtext", "newtxmath", "setspace", "titlesec", "fancyhdr", "authblk", "sectsty", "hyperref", "inputenc", "fontenc"}
    add, dropped = [], []
    for opt, nm in front_matter(mtext)["packages"]:
        for p in nm.split(","):
            p = p.strip()
            if p in tpk:
                continue
            if p in skip:
                dropped.append(p)
            else:
                add.append("\\usepackage%s{%s}" % ("[%s]" % opt if opt else "", p))
    defs = re.findall(r"^\\(?:newcommand|renewcommand|DeclareMathOperator|newtheorem|def|providecommand)\b.*$", mpre, re.M)
    block = "\n".join(add + defs)
    if block:
        out = out.replace("\\begin{document}", "% --- carried over from the manuscript ---\n" + block + "\n\\begin{document}", 1)
        notes.append("packages carried over: %s; definitions: %d" % (", ".join(re.findall(r"\{([^}]+)\}", " ".join(add))) or "none", len(defs)))
    if dropped:
        notes.append("layout packages NOT carried over (the template decides the layout): %s" % ", ".join(dropped))
    dest = os.path.join(a.work, "adapted")
    shutil.rmtree(dest, ignore_errors=True)
    copy_tree(tdir, dest)
    bibs = [f for f in os.listdir(os.path.join(a.work, "src")) if f.endswith(".bib")]
    for f in bibs:
        shutil.copy2(os.path.join(a.work, "src", f), os.path.join(dest, f))
    for dp, dn, fn in os.walk(os.path.join(a.work, "src")):
        for f in fn:
            if f.lower().endswith(texsrc.GFX_EXT) or f.endswith(".bib"):
                rel = os.path.relpath(os.path.join(dp, f), os.path.join(a.work, "src"))
                os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
                shutil.copy2(os.path.join(dp, f), os.path.join(dest, rel))
    wtext(os.path.join(dest, tmain), out)
    print("adapted project written to %s (main %s)" % (dest, tmain))
    for n in notes:
        print("  - " + n)
    st["adapted"] = {"dir": "adapted", "main": tmain, "notes": notes}
    save(a.work, st)
    print("Now compile it: `tx.py use W adapted` makes it the working copy; or copy it over src/ and run `check`.")


def cmd_use(a):
    st = load(a.work)
    ad = st.get("adapted")
    if not ad:
        raise SystemExit("no adapted project: run `adapt` first")
    src = os.path.join(a.work, "src")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(os.path.join(a.work, "adapted"), src)
    st["main"] = ad["main"]
    proj = texsrc.Project(src, st["main"])
    st["files"], st["bibs"], st["missing_inputs"] = proj.order, list(proj.bibs), proj.missing_inputs
    st["engine"], st["engine_reason"] = proj.engine()
    st["changes"].append({"file": ad["main"], "rule": "manuscript moved into the template (adapt)", "diff": "; ".join(ad["notes"])[:600]})
    save(a.work, st)
    print("working copy is now the adapted project (main %s, engine %s)" % (st["main"], st["engine"]))


# ------------------------------------------------------------------------------------------------ build
def unified(orig_dir, new_dir):
    changes = []
    seen = set()
    for dp, dn, fn in os.walk(new_dir):
        dn[:] = [d for d in dn if not d.startswith(".")]
        for f in fn:
            if not f.endswith((".tex", ".bib", ".sty", ".cls", ".bst")):
                continue
            rel = os.path.relpath(os.path.join(dp, f), new_dir)
            seen.add(rel)
            po = os.path.join(orig_dir, rel)
            old = rtext(po).split("\n") if os.path.isfile(po) else []
            new = rtext(os.path.join(dp, f)).split("\n")
            if old != new:
                d = list(difflib.unified_diff(old, new, "a/" + rel, "b/" + rel, lineterm="", n=1))
                changes.append({"file": rel, "status": "added" if not os.path.isfile(po) else "modified", "lines_added": sum(1 for l in d if l.startswith("+") and not l.startswith("+++")), "lines_removed": sum(1 for l in d if l.startswith("-") and not l.startswith("---")), "diff": "\n".join(d[:400])})
    for dp, dn, fn in os.walk(orig_dir):
        for f in fn:
            if f.endswith((".tex", ".bib", ".sty", ".cls", ".bst")):
                rel = os.path.relpath(os.path.join(dp, f), orig_dir)
                if rel not in seen and not os.path.isfile(os.path.join(new_dir, rel)):
                    changes.append({"file": rel, "status": "removed", "lines_added": 0, "lines_removed": len(rtext(os.path.join(dp, f)).split("\n")), "diff": ""})
    return sorted(changes, key=lambda c: c["file"])


def repro_files(out, st, build):
    eng = st["engine"]
    stem = os.path.splitext(os.path.basename(st["main"]))[0]
    sub = os.path.dirname(st["main"])
    bibtool = build["bib"].get("tool")
    sh = ["#!/bin/sh", "# Rebuild %s with the same engine, passes and environment as the recorded build." % st["main"], "set -e", "cd \"$(dirname \"$0\")/src%s\"" % (("/" + sub) if sub else ""),
          "export SOURCE_DATE_EPOCH=%s FORCE_SOURCE_DATE=1 TZ=UTC LC_ALL=C max_print_line=10000" % build.get("source_epoch", 0)]
    for p in build["passes"]:
        c = p["command"]
        c = c.replace("-synctex=0 ", "-synctex=0 ")
        sh.append(c)
    wtext(os.path.join(out, "repro", "build.sh"), "\n".join(sh) + "\n")
    mk = ["# make -C src (needs latexmk)", "MAIN=%s" % stem, "ENGINE=%s" % {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}.get(eng, "-pdf"),
          "all:", "\tSOURCE_DATE_EPOCH=%s FORCE_SOURCE_DATE=1 latexmk $(ENGINE) -interaction=nonstopmode -file-line-error $(MAIN).tex" % build.get("source_epoch", 0), "clean:", "\tlatexmk -C $(MAIN).tex"]
    wtext(os.path.join(out, "repro", "Makefile"), "\n".join(mk) + "\n")
    rc = ["# latexmkrc: the same build with latexmk", "$pdf_mode = %d;" % {"pdflatex": 1, "xelatex": 5, "lualatex": 4}.get(eng, 1), "$bibtex_use = 2;" if bibtool == "bibtex" else "$biber = 'biber %O %S';" if bibtool == "biber" else "", "$max_repeat = 6;"]
    wtext(os.path.join(out, "repro", "latexmkrc"), "\n".join(x for x in rc if x) + "\n")


def contract_fields(case):
    oc = find_key(case, ["output_contract", "outputContract", "output_schema", "outputs"]) if case else None
    items = oc if isinstance(oc, list) else (oc.get("fields") or oc.get("required") or oc.get("properties") or oc.get("required_fields") or [k for k in oc if k not in ("type", "description", "title", "version", "schema", "$schema", "additionalProperties")]) if isinstance(oc, dict) else []
    if isinstance(items, dict):
        items = list(items)
    out = []
    for it in items:
        n = it if isinstance(it, str) else (it.get("name") or it.get("field") or it.get("key")) if isinstance(it, dict) else None
        if isinstance(n, str) and n not in out:
            out.append(n)
    return out


def derive_field(name, ctx):
    n = name.lower()
    words = set(re.split(r"[^a-z]+", n))

    def has(ascii_words=(), cjk=()):
        return bool(words & set(ascii_words)) or any(x in n for x in cjk)
    if n in ("status", "run_status", "state", "outcome") or has(("status",), ("状态",)):
        return True, ctx["status"]
    if has(("product", "manuscript", "deliverable", "target", "source", "sources", "project", "latex", "pdf", "output"), ("产物", "稿", "源码")) and not has(("mapping", "evidence", "provenance")):
        return True, {"main": ctx["main"], "files": ctx["files"], "pdf": ctx["pdf"], "status": ctx["status"]}
    if has(("mapping", "evidence", "provenance", "changes", "diagnostics", "log", "diff"), ("来源", "映射", "修改", "改动", "差异")):
        return True, {"changes": ctx["changes"], "diagnostics": ctx["roots"], "lint": ctx["lint"], "build_passes": ctx["passes"]}
    if has(("boundary", "boundaries", "limits", "limitations", "uncertainty", "uncertainties", "caveats", "review", "environment", "reproducibility", "repro"), ("边界", "版本", "不确定", "确认", "复现", "环境")):
        return True, {"environment": ctx["environment"], "build_passes": ctx["passes"], "residual": ctx["residual"], "human_review": ctx["review"], "uncertainty": ctx["uncertainty"], "reproducibility": ctx["repro"]}
    if has(("files", "artifacts"), ()):
        return True, ctx["files"]
    return False, None


def cmd_build(a):
    st = load(a.work)
    src = os.path.join(a.work, "src")
    tools = texrun.find_tex(st.get("texbin"))
    proj = texsrc.Project(src, st["main"])
    lint_issues = texsrc.lint(proj, st["engine"])
    res = do_compile(a.work, st, tools)
    d = res["parsed"]["diagnostics"] if res.get("parsed") else []
    roots = texlog.root_causes(d)
    link_roots(roots, proj, lint_issues)
    os.makedirs(a.out, exist_ok=True)
    outsrc = os.path.join(a.out, "src")
    copy_tree(src, outsrc)
    for e in texrun.CLEAN_EXT:
        for dp, dn, fn in os.walk(outsrc):
            for f in fn:
                if f.endswith(e) and e != ".pdf":
                    os.remove(os.path.join(dp, f))
    files = ["src/"]
    pdf_out, pdf_hash, repro = None, None, {"checked": False}
    if res.get("pdf"):
        pdf_out = os.path.join(a.out, os.path.splitext(os.path.basename(st["main"]))[0] + ".pdf")
        shutil.copy2(res["pdf"], pdf_out)
        files.append(os.path.basename(pdf_out))
        pdf_hash = texrun.sha(pdf_out)
        if not a.no_repeat:
            res2 = do_compile(a.work, st, tools)
            if res2.get("pdf"):
                h2 = texrun.sha(res2["pdf"])
                repro = {"checked": True, "same_pdf_bytes": h2 == pdf_hash, "hash_1": pdf_hash, "hash_2": h2, "note": "two clean builds with SOURCE_DATE_EPOCH / FORCE_SOURCE_DATE" + ("" if h2 == pdf_hash else "; the bytes differ (a package embeds a time stamp, a random id or an absolute path): compare with pdftotext")}
                res = res2 if score(res2) <= score(res) else res
    for f in [x for x in os.listdir(src) if x.endswith(".pdf") and pdf_out and False]:
        pass
    changes = unified(os.path.join(a.work, "orig"), src)
    repro_files(a.out, st, {**res, "source_epoch": res.get("source_epoch")})
    files.append("repro/")
    pk = texrun.package_versions(res.get("parsed"))
    env = {"engine": res["engine"], "tex_versions": st["tools"]["versions"], "packages": pk, "source_date_epoch": res.get("source_epoch"), "bib_tool": res["bib"].get("tool"), "os": sys.platform}
    passes = res.get("passes", [])
    residual = {"errors": [{"file": x["file"], "line": x["line"], "message": x["message"][:160], "cascade": x["cascade"]} for x in d if x["kind"] == "error"][:30], "undefined": [{"file": x["file"], "line": x["line"], "message": x["message"][:120]} for x in d if x["code"] in ("undefined_ref", "undefined_cite")][:20],
                "overfull": [{"file": x["file"], "line": x["line"], "pt": x["detail"].get("pt")} for x in d if x["code"] == "overfull_hbox" and (x["detail"].get("pt") or 0) > 5][:15], "bib_errors": res["bib"].get("errors", [])[:10], "lint_errors": [i for i in lint_issues if i["severity"] == "error"][:30]}
    errs = [x for x in d if x["kind"] == "error"]
    if res["status"] == "no_tex":
        status = "not_compiled"
    elif res["ok"] and res["converged"] and not residual["undefined"] and not residual["bib_errors"]:
        status = "success"
    else:
        status = "partial"
    review, unc = [], []
    for e in residual["errors"][:10]:
        review.append({"kind": "compile_error", "where": "%s:%s" % (e["file"], e["line"]), "detail": e["message"]})
    for u in residual["undefined"][:10]:
        review.append({"kind": "undefined_reference", "where": "%s:%s" % (u["file"], u["line"]), "detail": u["message"]})
    for b in residual["bib_errors"][:5]:
        review.append({"kind": "bibliography", "where": "", "detail": b})
    for i in residual["lint_errors"][:10]:
        review.append({"kind": "static_" + i["code"], "where": "%s:%s" % (i["file"], i["line"]), "detail": i["message"][:140]})
    if res["status"] == "no_tex":
        unc.append({"kind": "not_compiled", "detail": "no TeX engine was available: nothing was compiled, no PDF exists; only static checks ran; the build must be run where TeX is installed (repro/build.sh)"})
    if res["notes"]:
        for n in res["notes"]:
            unc.append({"kind": "build_note", "detail": n})
    if repro.get("checked") and not repro["same_pdf_bytes"]:
        unc.append({"kind": "pdf_not_byte_identical", "detail": repro["note"]})
    if not res["converged"] and res["status"] != "no_tex":
        unc.append({"kind": "not_converged", "detail": "the cross-reference files were still changing after %d passes" % len([p for p in passes if p["command"].startswith(("pdflatex", "xelatex", "lualatex"))])})
    unc.append({"kind": "log_reading_is_textual", "detail": "diagnostics come from the TeX log; a cause that TeX does not report (a wrong but valid command, layout that merely looks bad) is not found; read the PDF"})
    ctx = {"status": status, "main": st["main"], "files": files, "pdf": os.path.basename(pdf_out) if pdf_out else None, "changes": [{"file": c["file"], "status": c["status"], "lines_added": c["lines_added"], "lines_removed": c["lines_removed"], "diff": c["diff"][:2000]} for c in changes] + [dict(r, kind="applied_fix") for r in st.get("changes", [])],
           "roots": roots, "lint": [i for i in lint_issues if i["severity"] != "info"][:60], "passes": passes, "environment": env, "residual": residual, "review": review, "uncertainty": unc, "repro": repro}
    build_md = ["# Build report", "", "- status: %s" % status, "- main: %s | engine: %s" % (st["main"], res["engine"]), "- PDF: %s (sha256 %s)" % (ctx["pdf"] or "none", (pdf_hash or "")[:16]),
                "- reproducible: %s" % (json.dumps(repro) if repro.get("checked") else "not checked"), "", "## Environment", "```", json.dumps(env, indent=1), "```", "", "## Passes"]
    for p in passes:
        build_md.append("- pass %d `%s` %.1fs errors %d warnings %d undefined %d%s" % (p["n"], p["command"], p["seconds"], p["errors"], p["warnings"], p["undefined"], " (changed: %s)" % ",".join(p["changed"]) if p["changed"] else ""))
    build_md += ["", "## Repeat the build", "`sh repro/build.sh` (same commands and environment), or `make -C src -f ../repro/Makefile`, or latexmk with `repro/latexmkrc`."]
    wtext(os.path.join(a.out, "build_report.md"), "\n".join(build_md) + "\n")
    jsave(os.path.join(a.out, "build_report.json"), {"status": status, "environment": env, "passes": passes, "repro": repro, "residual": residual, "notes": res["notes"]})
    wtext(os.path.join(a.out, "changes.md"), "# Changes (original -> delivered sources)\n\n" + ("\n".join("## %s (%s, +%d -%d)\n```diff\n%s\n```" % (c["file"], c["status"], c["lines_added"], c["lines_removed"], c["diff"][:3000]) for c in changes) or "No source file changed.") + ("\n\n## Fixes applied by `fix` (each verified by a compile)\n" + "\n".join("- %s: %s" % (r["file"], r["rule"]) for r in st.get("changes", [])) if st.get("changes") else "") + "\n")
    jsave(os.path.join(a.out, "diagnostics.json"), {"roots": roots, "diagnostics": d, "lint": lint_issues})
    wtext(os.path.join(a.out, "review_checklist.md"), "# Review checklist\n\nMachine-assisted: nothing here is approved by the author.\n\n" + ("\n".join("- [ ] %s %s: %s" % (r["kind"], r["where"], r["detail"]) for r in review) or "- no open item") + "\n\n## Always check by hand\n- open the PDF: layout, figures, tables, equation numbering and references are only as good as the log says\n- that every edit in changes.md keeps the author's meaning (the compile cannot tell)\n- template rules the class does not enforce (page limits, anonymity, required statements)\n")
    files += ["build_report.md", "build_report.json", "changes.md", "diagnostics.json", "review_checklist.md"]
    case = st.get("case")
    fields = contract_fields(case)
    answers = jload(a.answers, {}) if a.answers else {}
    result = {"case_id": st.get("case_id")}
    unfilled = []
    for fld in fields:
        if fld == "case_id":
            continue
        if fld in answers:
            result[fld] = answers[fld]
            continue
        ok, v = derive_field(fld, ctx)
        result[fld] = v if ok else None
        if not ok:
            unfilled.append(fld)
    for nm, key in (("status", "status"), ("manuscript", "manuscript"), ("sources", "sources"), ("boundaries", "boundaries"), ("files", "files")):
        if nm not in result:
            result[nm] = derive_field({"status": "status", "manuscript": "source", "sources": "changes", "boundaries": "boundaries", "files": "files"}[key], ctx)[1]
    for k, v in answers.items():
        result.setdefault(k, v)
    result["_meta"] = {"generator": "tex-ledger/tx.py %s" % VERSION, "contract_fields": fields, "unfilled_fields": unfilled, "contract_found": bool(fields), "files": files}
    jsave(os.path.join(a.out, "result.json"), result)
    print(json.dumps({"written": a.out, "status": status, "engine": res["engine"], "passes": len([p for p in passes if p["command"].startswith(("pdflatex", "xelatex", "lualatex"))]), "converged": res["converged"], "errors": len(errs), "undefined": len(residual["undefined"]), "pdf": ctx["pdf"],
                      "same_pdf_bytes_on_rebuild": repro.get("same_pdf_bytes"), "changed_files": len(changes), "unfilled_contract_fields": unfilled, "contract_found": bool(fields)}, ensure_ascii=False))
    for r in review[:8]:
        print("OPEN %s %s: %s" % (r["kind"], r["where"], r["detail"][:140]))
    if unfilled:
        print("UNFILLED contract fields (put them in answers.json and re-run build --answers): " + ", ".join(unfilled))
    sys.exit(0 if (not unfilled or not fields) else 2)


# ------------------------------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="tx.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.set_defaults(fn=cmd_run)
    p.add_argument("--case")
    p.add_argument("--src")
    p.add_argument("--out", required=True)
    p.add_argument("--work")
    p.add_argument("--main")
    p.add_argument("--engine", choices=["pdflatex", "xelatex", "lualatex"])
    p.add_argument("--no-compile", dest="no_compile", action="store_true")
    p.add_argument("--texbin")
    for nm, fn in (("diag", cmd_diag), ("lint", cmd_lint), ("check", cmd_check), ("fix", cmd_fix)):
        p = sub.add_parser(nm)
        p.set_defaults(fn=fn)
        p.add_argument("work")
        p.add_argument("--all", action="store_true")
        if nm == "fix":
            p.add_argument("--safe", action="store_true")
            p.add_argument("--unverified", action="store_true")
    for nm, fn in (("template", cmd_template), ("adapt", cmd_adapt)):
        p = sub.add_parser(nm)
        p.set_defaults(fn=fn)
        p.add_argument("work")
        p.add_argument("--template", required=True)
    p = sub.add_parser("use")
    p.set_defaults(fn=cmd_use)
    p.add_argument("work")
    p.add_argument("what", nargs="?")
    p = sub.add_parser("build")
    p.set_defaults(fn=cmd_build)
    p.add_argument("work")
    p.add_argument("--out", required=True)
    p.add_argument("--case", default="")
    p.add_argument("--answers")
    p.add_argument("--no-repeat", dest="no_repeat", action="store_true")
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except FileNotFoundError as e:
        raise SystemExit("ERROR: file not found: %s" % e.filename)
    except zipfile.BadZipFile:
        raise SystemExit("ERROR: the archive is not a valid zip file")


if __name__ == "__main__":
    main()
