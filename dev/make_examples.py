#!/usr/bin/env python3
"""make_examples.py - regenerate submission/examples/out and run.txt from real runs (nothing typed by hand; the manual edits are the tab-separated lines of examples/manual_edits.txt).
The example project is INVENTED. Needs TeX for the compile steps (without it the transcript shows the static-only behaviour)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUB = os.path.join(ROOT, "submission") if os.path.isdir(os.path.join(ROOT, "submission")) else ROOT
EX = os.path.join(SUB, "examples")
TX = os.path.join(SUB, "scripts", "tx.py")
KEEP = ("build_report.md", "changes.md", "review_checklist.md", "result.json", "brief.md", "repro")


def scrub(text, *paths):
    for p in sorted(set(x for x in paths if x), key=len, reverse=True):
        text = text.replace(p, "<dir>")
    text = re.sub(r"/(?:Users|home|var/folders|private)/[^\s\"',)]*", "<dir>", text)
    return re.sub(r"<dir>/tmp\w+", "<work>", text)


def sh(args, log, cut=None):
    r = subprocess.run([sys.executable, TX] + args, capture_output=True, text=True, cwd=EX)
    out = r.stdout + r.stderr
    if cut:
        lines = out.splitlines()
        out = "\n".join(lines[:cut] + (["... (%d more lines; the full brief is out/brief.md)" % (len(lines) - cut)] if len(lines) > cut else []))
    log.write(scrub("$ tx.py " + " ".join(args) + "\n" + out + "\n\n", EX, tempfile.gettempdir()))
    return r


def main():
    out = os.path.join(EX, "out")
    shutil.rmtree(out, ignore_errors=True)
    if os.path.isfile(os.path.join(EX, "run.txt")):
        os.remove(os.path.join(EX, "run.txt"))
    work = tempfile.mkdtemp()
    log = open(os.path.join(tempfile.gettempdir(), "run_tx.txt"), "w", encoding="utf-8")
    sh(["run", "--src", "paper", "--out", "out", "--work", work], log, cut=70)
    sh(["fix", work, "--safe"], log)
    sh(["check", work], log)
    for ln in open(os.path.join(EX, "manual_edits.txt"), encoding="utf-8").read().splitlines():
        f, old, new = ln.split("\t")
        p = os.path.join(work, "src", f)
        t = open(p, encoding="utf-8").read()
        if old not in t:
            raise SystemExit("manual edit does not apply: %s" % ln)
        open(p, "w", encoding="utf-8").write(t.replace(old, new, 1))
    log.write("# manual edits applied to the working copy (examples/manual_edits.txt)\n\n")
    sh(["fix", work, "--safe"], log)
    sh(["check", work], log)
    sh(["build", work, "--out", "out"], log)
    log.close()
    for f in os.listdir(out):
        if f not in KEEP:
            p = os.path.join(out, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    shutil.move(os.path.join(tempfile.gettempdir(), "run_tx.txt"), os.path.join(EX, "run.txt"))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
