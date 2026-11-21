# AI-assisted development log

This project is built with an AI coding assistant (Claude Code). The job description this project targets asks
for engineers who "critically validate, verify, and integrate AI-generated code". This log is the evidence.

**Rule:** whenever AI-generated code, specs, or claims turned out wrong and something caught it, add an entry.
Entries are never deleted.

| # | Date | File / spec | What the AI produced | How it was caught | Fix | Lesson |
|---|---|---|---|---|---|---|
| 1 | 2026-11-21 | planning → ADR-0006 | nDCG formula with exponential gain $2^{rel}-1$ | Checked against KDD Cup Task 1 sources while writing EVAL_PROTOCOL | Linear gain is primary; exponential is kept as a secondary metric | Verify metric definitions against the benchmark's own scoring before writing code |

## How verification is done here
1. **Spec first, tests from the spec:** tests are written from `docs/specs/*` "Tests" tables before implementation.
2. **External oracles:** `sklearn.metrics.ndcg_score` for nDCG; exact search for HNSW; official dataset counts; `h_max` for the cache hit rate.
3. **Review checklist per PR:** does the code match the spec section it cites? Are the edge cases in the spec tested?
   Did `make check` pass? What was *not* verified?
