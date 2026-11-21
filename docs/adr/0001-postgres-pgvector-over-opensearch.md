# ADR-0001: PostgreSQL + pgvector as the single serving store

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
We need product records, full-text search, and approximate nearest-neighbor vector search online.
The budget is at most $60 total, and the project should show SQL/database work.

## Options
1. **Amazon OpenSearch Service**: native BM25 and k-NN in one engine. Costs a managed domain or a serverless
   minimum that keeps running between sessions; a second query language.
2. **RDS PostgreSQL + pgvector**: one engine for records, `tsvector` full-text, and HNSW vectors
   (RDS supports pgvector 0.8.0 on PG 17.1+). Lexical ranking is `ts_rank_cd`, **not BM25**.
3. Postgres for records + a separate vector DB: more moving parts, no clear gain at about 1M vectors.

## Decision
Option 2. The instance can be **stopped** between sessions (paying storage only), the SQL stays inspectable
(`EXPLAIN ANALYZE`), and the trade-offs are measurable inside this project.

## Consequences
- We lose true BM25 in the serving path unless BM25 runs in-process (ADR-0002). Comparison C4 in the
  evaluation protocol measures that quality cost instead of assuming it away.
- HNSW memory pressure on small instances (ADR-0003).
