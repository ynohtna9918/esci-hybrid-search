# Evaluation protocol (pre-registered)

**Frozen on:** 2026-11-21, before any experiment was run.
Changes require an ADR and an entry in §12 "Amendments". Results that contradict hypotheses
are reported anyway.

---

## 1. Questions

- Q1. How much does dense retrieval add over BM25 on ESCI US queries?
- Q2. Does hybrid (RRF) beat the better of its two inputs?
- Q3. How much does cross-encoder reranking add, and at what latency?
- Q4. What relevance do we lose by using Postgres full-text (`ts_rank_cd`) instead of true BM25?
- Q5 (exploratory). Does a hosted reranker (Bedrock) beat a local cross-encoder?

## 2. Data

Source: `amazon-science/esci-data`, files `shopping_queries_dataset_examples.parquet` and
`shopping_queries_dataset_products.parquet`, joined on (`product_locale`, `product_id`).

| Item | Definition |
|---|---|
| Locale | `product_locale == "us"` |
| Version | `small_version == 1` (the Task 1 reduced set) |
| Corpus (Track F) | every product in the products file with `product_locale == "us"` |
| Labels | `esci_label` ∈ {E, S, C, I} |

Expected counts (official README, asserted in tests): 29,844 queries / 601,354 judgments;
train 20,888 / 419,653; test 8,956 / 181,701.

### Splits

| Split | Built from | Size | Use |
|---|---|---|---|
| `train` | official `train` minus `dev` | 19,388 queries | reserved for v2 fine-tuning; not used in v1 |
| `dev` | 1,500 queries sampled from official `train` (SPEC-01.3, seed 42) | 1,500 | all tuning, ablations, debugging, plots |
| `ci_dev` | the first 200 queries of `dev` in sampled order | 200 | CI regression gate |
| `test` | official `test` | 8,956 | **only** `make final-eval`, run once |

## 3. Gains and nDCG

Gain mapping (KDD Cup 2022 Task 1): **E = 1.0, S = 0.1, C = 0.01, I = 0.0**. Gains are
used **linearly** (see ADR-0006).

$$\text{DCG@}k(q) = \sum_{i=1}^{\min(k,\,n_q)} \frac{g(q, d_i)}{\log_2(i+1)}, \qquad \text{nDCG@}k(q) = \frac{\text{DCG@}k(q)}{\text{IDCG@}k(q)}$$

- $q$: a query
- $d_i$: the product at 1-based rank $i$ in the system's ranked list for $q$
- $g(q, d_i)$: the gain of $d_i$ for $q$ from the mapping above; unjudged products have no gain (see §5)
- $n_q$: the length of the ranked list being scored
- $k$: the cutoff; "nDCG" without a cutoff means $k = n_q$ (the whole list)
- $\log_2(i+1)$: the position discount (rank 1 → 1, rank 2 → 1.585, ...)
- $\text{IDCG@}k(q)$: the DCG@k of the ideal ordering, i.e. all judged products for $q$ sorted by gain, descending

**System score** = mean of nDCG@k(q) over the evaluated queries.

**Edge cases**
- Queries with IDCG = 0 (all candidates labeled I) are **excluded** from every system, and the count is reported.
- Ties in system scores are broken by `product_id` ascending, so a ranking is a deterministic function of the scores.
- We also report the **discriminative subset**: queries with at least 2 distinct gain values among their judged products.
  Queries with only one distinct gain give every system the same nDCG and dilute differences.

## 4. Track R: rerank the judged candidates (comparable to KDD Cup Task 1)

- Candidates for $q$ = exactly the products judged for $q$ (all four labels).
- Each system orders the candidates; no products from outside are added.
- **Primary metric:** nDCG (whole list). **Secondary:** nDCG@10.
- Applicable to P0–P6 (dense and lexical scores are computed over the candidate set only).

## 5. Track F: full-corpus retrieval (what the service does)

- Each system retrieves the top $K = 100$ from the full US corpus.
- Most retrieved products are **unjudged**. We do not treat unjudged as irrelevant.
- **nDCG'@10 (condensed list):** remove unjudged products from the ranked list, keep the
  relative order of the judged ones, and compute nDCG@10 on the result (Sakai, SIGIR 2007).
  IDCG uses all judged products for $q$.
- **Judged@10:** fraction of the top 10 that are judged. Always reported next to nDCG'@10,
  because condensed lists can flatter systems that retrieve many unjudged items.
- **Recall_E@100:**

$$\text{Recall}_E@100(q) = \frac{|\text{top}_{100}(q) \cap E_q|}{|E_q|}$$

  - $\text{top}_{100}(q)$: the set of the system's first 100 retrieved products for $q$
  - $E_q$: the set of products judged **E** for $q$; queries with $|E_q| = 0$ are excluded from this metric
  - This is recall over *known* exact matches, a lower bound on true recall.
- **Primary metric:** Recall_E@100 for retrieval stages (P1–P4); nDCG'@10 for final rankings (P4–P6).

## 6. Statistics

For each planned comparison A vs B, on per-query score differences $\delta_q = s_A(q) - s_B(q)$:

- **Effect:** mean $\bar\delta$ with a **95% paired bootstrap CI** (10,000 resamples of queries, percentile method, seed 42).
- **Test:** two-sided paired randomization test (10,000 sign flips of $\delta_q$, seed 42).
- **Multiplicity:** Holm–Bonferroni across the confirmatory comparisons in §7 (family-wise α = 0.05).
- We call a difference **significant** only if the Holm-adjusted p < 0.05 **and** the CI excludes 0.

## 7. Planned comparisons

Confirmatory (on `test`, in `make final-eval`):

| ID | Comparison | Track | Metric | Direction |
|---|---|---|---|---|
| C1 | P3 `dense` vs P1 `bm25` | R and F | nDCG / Recall_E@100 | two-sided |
| C2 | P4 `hybrid_rrf` vs better of (P1, P3) on dev | R and F | nDCG / Recall_E@100 | two-sided |
| C3 | P5 `hybrid_ce` vs P4 | R and F | nDCG / nDCG'@10 | two-sided |
| C4 | P2 `pgfts` vs P1 `bm25` | R and F | nDCG / Recall_E@100 | two-sided |

Exploratory (dev only, labeled as exploratory in every table):
- E1: P6 `hybrid_bedrock` vs P5 on ≤ 500 dev queries (cost cap).
- E2: Ablations: RRF `k_rrf`, dense weight, `n_rerank` ∈ {20, 50, 100}, `ef_search` ∈ {40, 100, 200}, `doc_text` = title-only vs full.

## 8. Sanity checks (must pass before any number is reported)

1. **Metric oracle:** `metrics.ndcg` equals `sklearn.metrics.ndcg_score` within 1e-9 on random tie-free inputs.
2. **Oracle ranking** (sort by true gain) scores exactly 1.0 on Track R.
3. **Random floor:** P0 is run with 5 seeds; mean and std are reported. ESCI candidates are mostly E,
   so the random floor is high. Deltas must be read against it, not against 0.
4. **Counts** match §2 exactly.
5. **Leakage guard:** the runner refuses `split=test` unless `FINAL_EVAL=1`, the git tree is clean,
   and every config in the run is listed in `configs/frozen.txt`.
6. **HNSW fidelity:** on Track F, dense-HNSW Recall@100 relative to exact search ≥ 0.95 on dev
   at the chosen `ef_search`; otherwise, report it as a confound.

## 9. External anchors (context, not targets)

- Official Task 1 baseline: nDCG **0.83** on the public test set, averaged over US/ES/JP, with
  per-locale **fine-tuned** cross-encoders (US: `cross-encoder/ms-marco-MiniLM-L-12-v2`).
- First place in KDD Cup 2022 Task 1: nDCG 0.9043 (large ensembles).
- Our P5 uses the same US base model **zero-shot** on **US only**, so it is not directly comparable.
  We report it next to the anchor with this caveat.

## 10. System metrics

- **Latency:** client-side from k6 (`http_req_duration`) and server-side per stage from EMF.
  We report p50/p95/p99 with request counts. Percentiles are computed over raw samples, never averaged across runs.
- **Throughput Q:** the highest constant arrival rate at which p99 ≤ SLO and error rate < 0.5% hold for 5 minutes.
- **Cache hit rate h:** from the `zipf` scenario; reported as a function of the Zipf exponent $s$ ∈ {0.8, 1.0, 1.2}.
- **Cost:** DESIGN §8 formula, with unit prices and dates recorded.

## 11. Final evaluation procedure

1. Freeze configs: list them in `configs/frozen.txt` and commit.
2. `FINAL_EVAL=1 make final-eval` runs every frozen config on `test`, Tracks R and F.
3. The outputs (`results/final/<frozen_hash>/`, including every run directory under `runs/`) are committed
   unmodified, together with the commit SHA.
4. `make results` regenerates tables. If a bug is found afterwards, the fix and the rerun are both
   committed, and §12 records what changed. The old results are kept.

## 12. Amendments

_None yet._
