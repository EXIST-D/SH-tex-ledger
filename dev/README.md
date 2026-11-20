# dev/ - tests and evaluations of tex-ledger (not part of the Skill runtime)

| file | what |
|---|---|
| `test_all.py` | 33 regression tests (stdlib `unittest`); `python3 dev/test_all.py [-v]` (about 30 s with TeX; compile tests are skipped without it) |
| `defects.py` | 20 defects injected one at a time into a clean invented project; counts how often the log reader and the static checks name and place them, versus reading only the first log error |
| `make_examples.py` | regenerates `submission/examples/out` and `run.txt` from real runs (the manual edits are `examples/manual_edits.txt`) |

Everything is invented; no third-party documents are included. Numbers are in the repository README and `submission/references/diagnostics.md`.
