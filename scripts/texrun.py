#!/usr/bin/env python3
"""texrun.py - run TeX the way a reproducible build does, and record what happened.

`find_tex` locates the engines (pdflatex / xelatex / lualatex), latexmk, bibtex, biber. `compile_project` copies nothing: it runs in the directory it is given, with
-interaction=nonstopmode -file-line-error (all errors in one run), a wide max_print_line (logs are not wrapped), SOURCE_DATE_EPOCH + FORCE_SOURCE_DATE (the PDF does not depend on the clock),
runs BibTeX / Biber when the aux file asks for it, and repeats until the cross-reference files stop changing. Every pass is recorded (command, seconds, errors, undefined references, changed files).
"""
from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
import subprocess
import time

import texlog

STABLE_EXT = (".aux", ".toc", ".lof", ".lot", ".out", ".bbl", ".idx", ".ind", ".nav", ".bcf", ".run.xml", ".glo", ".gls")
CLEAN_EXT = STABLE_EXT + (".log", ".blg", ".fls", ".fdb_latexmk", ".synctex.gz", ".pdf", ".dvi", ".xdv", ".ilg", ".bbl-SAVE-ERROR", ".brf", ".snm", ".vrb", ".lol", ".lox", ".thm", ".tdo", ".xwm", ".figlist", ".makefile", ".figlist")


def candidate_bins(extra=None):
    out = [extra] if extra else []
    home = os.path.expanduser("~")
    out += glob.glob(home + "/Library/TinyTeX/bin/*") + glob.glob(home + "/.TinyTeX/bin/*") + glob.glob("/usr/local/texlive/*/bin/*") + glob.glob("/Library/TeX/texbin") + glob.glob("/opt/homebrew/bin") + glob.glob("/usr/bin")
    return [d for d in out if d and os.path.isdir(d)]


def which(name, texbin=None):
    p = shutil.which(name)
    if p:
        return p
    for d in candidate_bins(texbin):
        q = os.path.join(d, name)
        if os.path.isfile(q) and os.access(q, os.X_OK):
            return q
    return None


def find_tex(texbin=None):
    """-> {engine: path|None ..., 'latexmk', 'bibtex', 'biber', 'versions': {...}}"""
    tools = {n: (None if os.environ.get("TX_NO_TEX") else which(n, texbin)) for n in ("pdflatex", "xelatex", "lualatex", "latexmk", "bibtex", "biber", "kpsewhich")}
    vers = {}
    for n in ("pdflatex", "xelatex", "lualatex", "bibtex", "biber"):
        if tools[n]:
            try:
                out = subprocess.run([tools[n], "--version"], capture_output=True, text=True, timeout=20).stdout.splitlines()
                vers[n] = out[0].strip() if out else ""
            except (OSError, subprocess.SubprocessError):
                vers[n] = "?"
    tools["versions"] = vers
    return tools


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(workdir, stem):
    snap = {}
    for e in STABLE_EXT:
        p = os.path.join(workdir, stem + e)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                data = fh.read()
            if e == ".aux":
                data = re.sub(rb"\\@abspage@last\{\d+\}", b"", data)
            snap[e] = hashlib.md5(data).hexdigest()
    return snap


def clean(workdir, stem):
    for e in CLEAN_EXT:
        p = os.path.join(workdir, stem + e)
        if os.path.isfile(p):
            os.remove(p)


def env_for(source_epoch):
    env = dict(os.environ)
    env.update({"max_print_line": "10000", "error_line": "254", "half_error_line": "238", "SOURCE_DATE_EPOCH": str(source_epoch), "FORCE_SOURCE_DATE": "1", "TEXINPUTS": "." + os.pathsep + os.environ.get("TEXINPUTS", ""), "BIBINPUTS": "." + os.pathsep + os.environ.get("BIBINPUTS", ""),
                "TZ": "UTC", "LC_ALL": "C"})
    return env


def uses_biber(workdir, stem):
    bcf = os.path.join(workdir, stem + ".bcf")
    return os.path.isfile(bcf)


def wants_bibtex(workdir, stem):
    aux = os.path.join(workdir, stem + ".aux")
    if not os.path.isfile(aux):
        return False
    t = open(aux, encoding="utf-8", errors="replace").read()
    return "\\bibdata" in t and "\\citation" in t


def run_cmd(cmd, cwd, env, timeout):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, errors="replace")
        return r.returncode, r.stdout, time.time() - t0, False
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")), time.time() - t0, True


def compile_project(workdir, main_rel, engine="pdflatex", tools=None, max_passes=6, timeout=120, source_epoch=None, keep_going=True, budget=300):
    """-> dict(ok, pdf, engine, passes[], converged, parsed, bib, log, notes[])"""
    tools = tools or find_tex()
    notes = []
    exe = tools.get(engine)
    if not exe:
        alt = next((e for e in ("pdflatex", "xelatex", "lualatex") if tools.get(e)), None)
        if not alt:
            return {"ok": False, "status": "no_tex", "engine": engine, "passes": [], "converged": False, "parsed": None, "bib": {}, "log": "", "pdf": None, "notes": ["no TeX engine found on this machine: only the static checks ran"]}
        notes.append("%s not installed: compiled with %s instead (result may differ)" % (engine, alt))
        engine, exe = alt, tools[alt]
    main_abs = os.path.join(workdir, main_rel)
    stem = os.path.splitext(os.path.basename(main_rel))[0]
    sub = os.path.dirname(main_abs)
    mname = os.path.basename(main_rel)
    if source_epoch is None:
        source_epoch = int(max([os.path.getmtime(os.path.join(dp, f)) for dp, dn, fn in os.walk(workdir) for f in fn if f.endswith((".tex", ".bib", ".sty", ".cls"))] or [0]))
    env = env_for(source_epoch)
    clean(sub, stem)
    passes, bib = [], {"tool": None, "ran": 0, "errors": [], "warnings": []}
    cmd = [exe, "-interaction=nonstopmode", "-file-line-error", "-synctex=0", mname]
    prev = {}
    t_start = time.time()
    last_log = ""
    parsed = None
    converged = False
    for n in range(1, max_passes + 1):
        if time.time() - t_start > budget:
            notes.append("time budget of %ds used after %d passes" % (budget, n - 1))
            break
        rc, out, secs, to = run_cmd(cmd, sub, env, timeout)
        logp = os.path.join(sub, stem + ".log")
        last_log = open(logp, encoding="utf-8", errors="replace").read() if os.path.isfile(logp) else out
        parsed = texlog.parse_log(last_log, mname)
        d = parsed["diagnostics"]
        errs = [x for x in d if x["kind"] == "error"]
        undef = [x for x in d if x["code"] in ("undefined_ref", "undefined_cite")]
        snap = snapshot(sub, stem)
        changed = sorted(e for e in set(snap) | set(prev) if snap.get(e) != prev.get(e)) if prev else sorted(snap)
        passes.append({"n": n, "command": " ".join(os.path.basename(cmd[0:1][0]) if i == 0 else c for i, c in enumerate(cmd)), "seconds": round(secs, 2), "errors": len(errs), "warnings": sum(1 for x in d if x["kind"] == "warning"), "undefined": len(undef), "rerun_requested": parsed["rerun"], "changed": changed, "timeout": to})
        if to:
            notes.append("pass %d timed out after %ds (an endless loop, an interactive prompt or a very slow package)" % (n, timeout))
            break
        # bibliography between pass 1 and 2
        if n == 1 or (bib["ran"] == 0 and wants_bibtex(sub, stem)):
            tool = None
            if uses_biber(sub, stem):
                tool = ("biber", tools.get("biber"))
            elif wants_bibtex(sub, stem):
                tool = ("bibtex", tools.get("bibtex"))
            if tool and bib["ran"] == 0:
                bib["tool"] = tool[0]
                if not tool[1]:
                    bib["errors"].append("%s is not installed: the bibliography cannot be built (install it, or switch backend)" % tool[0])
                    notes.append("%s missing: citations stay undefined" % tool[0])
                else:
                    bc = [tool[1], stem]
                    rc2, out2, secs2, to2 = run_cmd(bc, sub, env, 60)
                    bib["ran"] += 1
                    blg = os.path.join(sub, stem + ".blg")
                    btxt = open(blg, encoding="utf-8", errors="replace").read() if os.path.isfile(blg) else out2
                    for ln in btxt.splitlines():
                        s = ln.strip()
                        if re.match(texlog.RX_BIBTEX_ERR, s) or re.match(r"^(ERROR|WARN)\b", s) or "ERROR - " in s or "WARN - " in s:
                            (bib["errors"] if ("ERROR" in s or s.startswith(("I couldn't", "I found no", "I was expecting", "Repeated", "I'm skipping", "Illegal"))) else bib["warnings"]).append(s[:200])
                    passes.append({"n": n, "command": os.path.basename(bc[0]) + " " + stem, "seconds": round(secs2, 2), "errors": len(bib["errors"]), "warnings": len(bib["warnings"]), "undefined": 0, "rerun_requested": False, "changed": [".bbl"] if os.path.isfile(os.path.join(sub, stem + ".bbl")) else [], "timeout": to2})
                    snap = snapshot(sub, stem)
                    prev = {k: v for k, v in prev.items() if k != ".bbl"}
                    continue
        if prev and snap == prev and not parsed["rerun"]:
            converged = True
            break
        if not prev and not parsed["rerun"] and not any(x["code"] in ("undefined_ref", "undefined_cite") for x in d) and not changed_aux_needed(sub, stem):
            converged = True
            break
        prev = snap
    pdf = os.path.join(sub, stem + ".pdf")
    has_pdf = os.path.isfile(pdf)
    d = parsed["diagnostics"] if parsed else []
    errors = [x for x in d if x["kind"] == "error"]
    status = "ok" if has_pdf and not errors else ("pdf_with_errors" if has_pdf else "failed")
    return {"ok": status == "ok", "status": status, "engine": engine, "passes": passes, "converged": converged, "parsed": parsed, "bib": bib, "log": last_log, "pdf": pdf if has_pdf else None, "notes": notes, "source_epoch": source_epoch}


def changed_aux_needed(sub, stem):
    """a table of contents / list written in this pass but not yet read: one more pass is needed"""
    return any(os.path.isfile(os.path.join(sub, stem + e)) for e in (".toc", ".lof", ".lot", ".out"))


def package_versions(parsed):
    return dict(parsed["packages"]) if parsed else {}
