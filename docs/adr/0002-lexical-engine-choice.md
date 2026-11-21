# ADR-0002: Lexical engine for the hybrid pipeline (bm25s in-process vs Postgres FTS)

- **Status:** Proposed. Decision rule fixed now; decision filled in at gate G2.
- **Date:** 2026-11-21

## Context
- `bm25s` gives true BM25 but lives in the API process (RAM: measured in W2).
- Postgres FTS (`websearch_to_tsquery` + `ts_rank_cd`) uses AND semantics and computes the rank for every
  matching row, so common-term queries can be slow, and recall on long queries can drop.

## Measurements required (dev split)
| Quantity | bm25 | pgfts |
|---|---|---|
| Recall_E@100 (Track F), P4 built on this lexical engine | | |
| nDCG'@10 (Track F), P4 built on this lexical engine | | |
| lexical-stage p50 / p99 latency, 1,500 dev queries, single client | | |
| API RSS with the index loaded (MB) | | n/a |

## Decision rule (fixed before measurement)
Choose **bm25** iff all of the following hold:
1. the hybrid built on bm25 beats the hybrid built on pgfts on Recall_E@100 with a 95% CI excluding 0;
2. bm25's lexical p99 ≤ 50 ms;
3. the API RSS with the bm25 index stays ≤ 60% of `service_memory`.

Otherwise choose **pgfts**. The chosen engine is written into `configs/experiments/p4_hybrid.yaml`,
and the service uses the same config (SPEC-05.6: evaluated = deployed).

## Decision
_TBD at G2 (link run ids)._
