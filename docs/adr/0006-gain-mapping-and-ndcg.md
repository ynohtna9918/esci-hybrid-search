# ADR-0006: Gain mapping and nDCG definition

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
KDD Cup 2022 Task 1 scores ESCI labels as E = 1.0, S = 0.1, C = 0.01, I = 0.0. The official baseline was scored
with Terrier 5.5. Two common nDCG variants exist: **linear gain** $g$ and **exponential gain** $2^{g} - 1$.

## Decision
- Primary: **linear gain** with discount $\log_2(i+1)$, i.e. the same definition as `sklearn.metrics.ndcg_score`,
  which serves as our test oracle.
- `metrics.json` also stores the exponential-gain variant under `ndcg_exp` for robustness, but no headline or
  hypothesis test uses it.

## Residual uncertainty
We have not verified Terrier 5.5's exact handling of fractional gains. Our numbers are therefore compared with the
official 0.83 only as context (EVAL_PROTOCOL §9), never as a claim of beating it.

## Note
An earlier planning message used $2^{rel}-1$ in the formula. That was the exponential variant; this ADR corrects it.
