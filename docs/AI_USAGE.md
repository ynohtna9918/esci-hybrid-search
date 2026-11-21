# AI-assisted development log

This project is built with an AI coding assistant (Claude Code). The job description this project targets asks
for engineers who "critically validate, verify, and integrate AI-generated code". This log is the evidence.

**Rule:** whenever AI-generated code, specs, or claims turned out wrong and something caught it, add an entry.
Entries are never deleted.

| # | Date | File / spec | What the AI produced | How it was caught | Fix | Lesson |
|---|---|---|---|---|---|---|
| 1 | 2026-11-21 | planning → ADR-0006 | nDCG formula with exponential gain $2^{rel}-1$ | Checked against KDD Cup Task 1 sources while writing EVAL_PROTOCOL | Linear gain is primary; exponential is kept as a secondary metric | Verify metric definitions against the benchmark's own scoring before writing code |
| 2 | 2026-11-21 | SPEC-08.4, SPEC-00.1 | Spec claimed PyPI aarch64 torch wheels are CPU-only and relied on the default index for torch | Owner review of the PR 1 plan (W1 scaffold), before any install | Explicit PyTorch indexes per extra (`cpu` → whl/cpu, `gpu` → whl/cu130), mutually exclusive via `[tool.uv] conflicts`; image and CI use `--extra cpu` | Don't rely on an unverified property of a wheel's default build; pin the index that guarantees it |
| 3 | 2026-11-21 | SPEC-00.3, SPEC-00.5 | Planned modules `esci_search/types.py` and `esci_search/logging.py`, which shadow the stdlib `types` and `logging` (the AI's PR 1 plan kept the names without flagging it) | Owner review of the PR 1 plan, before any code was written | Renamed to `core_types.py` and `logs.py` across specs, manifest and CLAUDE.md | Check new module names against the stdlib (`sys.stdlib_module_names`) |

## How verification is done here
1. **Spec first, tests from the spec:** tests are written from `docs/specs/*` "Tests" tables before implementation.
2. **External oracles:** `sklearn.metrics.ndcg_score` for nDCG; exact search for HNSW; official dataset counts; `h_max` for the cache hit rate.
3. **Review checklist per PR:** does the code match the spec section it cites? Are the edge cases in the spec tested?
   Did `make check` pass? What was *not* verified?
