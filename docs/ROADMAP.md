# Roadmap and acceptance gates

Each phase ends with a **gate**: a list of checks that must pass before the next phase starts.
A gate is passed only by command output, not by assertion.

## W0: Specs (this commit)

- [x] PRFAQ, DESIGN, EVAL_PROTOCOL, specs 00–08, FILE_MANIFEST, ADRs

## W1: Data + baseline + evaluation harness

Scope: SPEC-00, SPEC-01, SPEC-02.1–02.2, SPEC-03.1–03.2, SPEC-03.7 (P0/P1 only), SPEC-04, SPEC-08.1–08.2, SPEC-08.5–08.6.

Gate G1:
- [ ] `make data` writes `data/processed/` and `docs/DATA_CARD.md`; US small-version counts equal
      the official README (29,844 queries / 601,354 judgments; train 20,888 / 419,653;
      test 8,956 / 181,701). This is a unit test, not a manual check.
- [ ] `tests/unit/test_metrics.py`: our nDCG equals `sklearn.metrics.ndcg_score` within 1e-9 on
      1,000 random cases; oracle ranking = 1.0; reversed oracle < 1.0.
- [ ] P0 `random` and P1 `bm25` run on dev, Track R; `metrics.json` written with bootstrap CIs.
- [ ] CI green (lint, types, unit).

## W2: Dense + Postgres + hybrid

Scope: SPEC-02.3–02.5, SPEC-03.3–03.5.

Gate G2:
- [ ] Embeddings for the full US corpus are written; `make index` is idempotent (a rerun is a no-op
      when the corpus hash is unchanged).
- [ ] Postgres loaded; `pgfts` and HNSW `dense` work on Track F; the HNSW recall@100 vs exact
      search is reported for `ef_search` ∈ {40, 100, 200} on 500 dev queries.
- [ ] `hybrid_rrf` tuned on dev (grid in DESIGN §4); the chosen config is frozen in `configs/experiments/p4_hybrid.yaml`.
- [ ] ADR-0002 (lexical engine) and ADR-0003 (RDS sizing) filled in with measured numbers.

## W3: Rerank

Scope: SPEC-03.6, SPEC-03.7.

Gate G3:
- [ ] `hybrid_ce` on dev with `n_rerank` ∈ {20, 50, 100}; quality vs CPU latency curve saved.
- [ ] `hybrid_bedrock` on **≤ 500 dev queries** (cost-capped); the result decides whether it ships.
- [ ] Ablation table on dev complete (EVAL_PROTOCOL §7).

## W4: Service + AWS

Scope: SPEC-05, SPEC-06, SPEC-08.

Gate G4:
- [ ] `make serve` passes the integration tests against local Docker (Postgres + DynamoDB Local).
- [ ] `make cloud-up` deploys from a clean clone; `/healthz` and the golden-query smoke test pass.
- [ ] Dashboard and alarms exist (verified with `aws cloudwatch describe-alarms`).
- [ ] Degradation tests: killing the encoder path yields `degraded: true` responses with lexical results.

## W5: Load, cost, final evaluation, write-up

Scope: SPEC-07, SPEC-04.6.

Gate G5:
- [ ] k6 `steady`, `ramp`, `zipf` reports in `results/loadtest/`; SLO pass/fail stated.
- [ ] Cost sheet in `results/cost/` with unit prices, dates, and the computed $/1M.
- [ ] `make final-eval` run **once** on the test split; outputs committed; README table generated.
- [ ] `make cloud-down` leaves no billable compute (verified by listing ECS services and ALBs).
- [ ] At least one upstream open-source contribution (issue or PR) linked in README.

## v2 candidates (not in scope)

Fine-tuned cross-encoder on the ESCI train split; product descriptions in `doc_text`; SQL-native
BM25 with term-statistics tables (would be a "query processing" showcase); ES/JP locales;
autoscaling; a learned fusion function.
