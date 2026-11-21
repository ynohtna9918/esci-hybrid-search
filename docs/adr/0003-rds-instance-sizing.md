# ADR-0003: RDS instance sizing

- **Status:** Proposed. Rule fixed now; decision at gate G2.
- **Date:** 2026-11-21

## Context
The HNSW index should stay in memory for stable p99. The DESIGN §6 formula gives a rough estimate;
the measured relation size is authoritative.

## Measurements required
- `N` (corpus size, from `docs/DATA_CARD.md`)
- `pg_total_relation_size('product_embeddings')` including its HNSW index, locally, after `make index`
- `pg_total_relation_size('products')` including the GIN index

## Decision rule
Pick the smallest `db.t4g.*` class whose RAM ≥ 1.5 × (embeddings + HNSW) + 0.5 × (products + GIN).
If even `db.t4g.large` is insufficient, reduce `m` from 16 to 12 and re-measure recall vs exact (EVAL_PROTOCOL §8.6)
before considering a larger class.

## Decision
_TBD at G2._
