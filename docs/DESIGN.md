# Design: esci-hybrid-search

Owner: Anthony Feng · Status: Draft v1 · Region: `us-west-2` (Oregon)

## 1. Goals and non-goals

**Goals (v1)**
- G1. Rank products for English (US) queries; measure relevance with ESCI human labels.
- G2. Quantify each layer's contribution (lexical, dense, fusion, rerank) with ablations and CIs.
- G3. Serve online with explicit SLOs; report p50/p95/p99 per stage under load.
- G4. Report cost per million queries from a stated cost model with measured inputs.
- G5. Operate it: IaC, CI/CD, dashboards, alarms, graceful degradation.

**Non-goals (v1)**: ES/JP locales; personalization; click models; learning-to-rank on behavior;
model fine-tuning (v2 candidate); autoscaling beyond a fixed task count; multi-region.

## 2. System overview

```
                 offline (local machine)                           online (AWS us-west-2)
 ┌──────────────────────────────────────────────┐     ┌─────────────────────────────────────────┐
 │ esci-data parquet ──► data/ (splits, card)   │     │  client ─► ALB ─► ECS Fargate (FastAPI)  │
 │        │                                     │     │                    │   │   │   │         │
 │        ├─► BM25 index (bm25s) ──┐            │     │      DynamoDB cache◄┘   │   │   └► Bedrock │
 │        ├─► embeddings (e5) ─────┼─► Postgres │ ──► │      (cache-aside)      │   │     Rerank   │
 │        │                        │  +pgvector │ S3  │                         ▼   ▼   (optional) │
 │        └─► eval runner ◄────────┘            │     │          RDS PostgreSQL 17 + pgvector    │
 │              │                               │     │          (products, tsvector, halfvec)   │
 │              ▼                               │     │  CloudWatch: EMF metrics, dashboard,     │
 │        results/runs/<run_id>/                │     │  alarms ─► SNS email                     │
 └──────────────────────────────────────────────┘     └─────────────────────────────────────────┘
```

All experiments (Track R and Track F) run **locally** against Docker Postgres. AWS is used only
for the online service, load tests, and the cost measurement. That keeps the bill bounded.

## 3. Data model

- **Corpus**: all rows of `shopping_queries_dataset_products.parquet` with `product_locale == "us"`.
  The exact count is recorded in the data card (`SPEC-01.5`); it is not assumed.
- **Document text** (`SPEC-01.4`): `title | brand | color | bullets` after normalization;
  `product_description` is excluded in v1 (often HTML or empty; an ablation candidate for v2).
- **Queries / qrels**: `shopping_queries_dataset_examples.parquet` with `product_locale == "us"`
  and `small_version == 1`. Labels map to gains E=1.0, S=0.1, C=0.01, I=0.0.

### Postgres schema (authoritative copy in `src/esci_search/index/pg_schema.sql`, SPEC-02.4)

| Table | Key columns | Notes |
|---|---|---|
| `products` | `product_id text PK`, `title`, `brand`, `color`, `bullets`, `doc_text`, `tsv tsvector` (generated, `english`) | GIN index on `tsv` |
| `product_embeddings` | `product_id PK FK`, `model text`, `emb halfvec(384)` | HNSW `halfvec_cosine_ops`, `m=16`, `ef_construction=64` |
| `index_meta` | `index_version PK`, `corpus_sha256`, `encoder`, `created_at`, `n_products`, `params jsonb` | one row per built index |

### DynamoDB table `esci-search-cache`

| Attribute | Type | Meaning |
|---|---|---|
| `ck` (PK) | S | `sha256(normalize(query) \| k \| pipeline \| index_version)` (pipeline implies rerank) |
| `payload` | B | zlib-compressed JSON of the response body (without timings) |
| `ttl` | N | epoch seconds; now + 24 h; DynamoDB TTL enabled |

## 4. Retrieval pipelines

Pipelines are named, versioned compositions (`SPEC-03.7`). The v1 set:

| ID | Name | Stages |
|---|---|---|
| P0 | `random` | seeded shuffle (Track R floor only) |
| P1 | `bm25` | bm25s (Lucene BM25, k1/b tuned on dev) |
| P2 | `pgfts` | Postgres `ts_rank_cd` over `tsv` |
| P3 | `dense` | e5-small-v2 query embedding → cosine (exact for Track R, HNSW for Track F) |
| P4 | `hybrid_rrf` | RRF(lexical, dense); lexical = winner of P1/P2 per ADR-0002 |
| P5 | `hybrid_ce` | P4 top-N → cross-encoder `cross-encoder/ms-marco-MiniLM-L-12-v2` |
| P6 | `hybrid_bedrock` | P4 top-N → Bedrock Rerank (`cohere.rerank-v3-5:0` or `amazon.rerank-v1:0`) |

**Reciprocal Rank Fusion:**

$$\text{RRF}(d) = \sum_{r \in R} \frac{w_r}{k_{\text{rrf}} + \text{rank}_r(d)}$$

- $d$: a candidate product
- $R$: the set of input ranked lists (here: lexical, dense)
- $\text{rank}_r(d)$: 1-based position of $d$ in list $r$; if $d$ is absent from $r$, that term is 0
- $k_{\text{rrf}}$: smoothing constant; default 60, tuned on dev from {10, 30, 60, 100}
- $w_r$: per-list weight; default 1.0, tuned on dev from {0.5, 1.0, 2.0} for the dense list

## 5. Online request flow (SPEC-05)

1. Validate the request; normalize the query (NFKC, lowercase, collapse whitespace).
2. Cache lookup (DynamoDB `GetItem`, 50 ms timeout). Return on a hit.
3. In parallel: lexical retrieval (top `n_lex`=100) and dense retrieval (encode + HNSW top `n_dense`=100).
4. RRF fuse → top `n_fuse`=50.
5. Optional rerank of the top `n_rerank`=50 (cross-encoder in-process, or Bedrock).
6. Hydrate titles from `products` (one `WHERE product_id = ANY($1)` query).
7. Respond; write to the cache asynchronously; emit EMF metrics per stage.

**Degradation**: if dense retrieval or the encoder fails, or exceeds its 150 ms stage budget,
serve lexical-only with `degraded: true`. If rerank fails, serve fused order with
`degraded: true`. Cache failures never fail a request. Postgres down → 503.

## 6. Capacity and sizing

Vector memory estimate, checked against the measured index size in W2:

$$M_{\text{vec}} \approx N \cdot (2 \cdot D + 2m \cdot 6) \text{ bytes}$$

- $M_{\text{vec}}$: rough RAM estimate for `halfvec` storage plus the HNSW layer-0 graph, excluding
  page/tuple overhead and upper layers (the measured relation size always wins over this estimate)
- $N$: number of products in the corpus (from the data card)
- $D$: embedding dimension (384 for e5-small-v2); `halfvec` stores 2 bytes per dimension
- $m$: the HNSW `m` parameter; layer 0 keeps up to $2m$ neighbors per node
- $6$: bytes per neighbor reference (a Postgres tuple pointer)

The RDS instance class is the smallest whose RAM is at least $1.5 \times$ the measured
`pg_total_relation_size` of `product_embeddings` plus its index. The starting assumption is
`db.t4g.medium`; the final choice is recorded in ADR-0003.

## 7. SLOs (initial targets, revisable only via ADR)

| Path | Load | p99 target | Error rate |
|---|---|---|---|
| `hybrid_rrf` (no rerank) | 20 RPS steady | ≤ 250 ms | < 0.5% |
| `hybrid_ce` | 5 RPS steady | ≤ 800 ms | < 0.5% |
| `hybrid_bedrock` | 2 RPS steady | ≤ 1000 ms | < 1% |
| cache hit | any | ≤ 30 ms | — |

## 8. Cost model

$$C_{1M} = \frac{C_{\text{hr}}}{Q \cdot 3600} \cdot 10^6 + (1 - h) \cdot f_{b} \cdot c_{b} \cdot 10^6$$

- $C_{1M}$: dollars per one million served queries
- $C_{\text{hr}}$: fixed hourly cost of the running stack (Fargate tasks + RDS instance + ALB + Secrets);
  unit prices come from the AWS pricing page on the measurement date and are recorded in `results/cost/`
- $Q$: maximum sustainable throughput (RPS) that still meets the path's SLO, measured by the k6 `ramp` scenario
- $h$: cache hit rate measured in the k6 `zipf` scenario; it depends on the assumed query
  popularity distribution, which is reported alongside it
- $f_b$: fraction of requests that call Bedrock (1 for `hybrid_bedrock`, 0 otherwise)
- $c_b$: Bedrock Rerank price per request at `n_rerank` documents, from the Bedrock pricing page

Cost guardrails: AWS Budgets $30/month with alerts at 80% and 100%; **no NAT Gateway**
(ADR-0004); `make cloud-down` destroys compute and ALB and keeps an RDS snapshot.

## 9. Security

- RDS in isolated subnets; its security group admits only the service security group on 5432.
- Task role is least-privilege: `dynamodb:GetItem/PutItem` on one table, `bedrock:Rerank` on
  two model ARNs, `secretsmanager:GetSecretValue` on one secret, `s3:GetObject` on the artifacts prefix.
- GitHub Actions deploys through an OIDC role; there are no long-lived keys.
- The API is public but rate-limited at the ALB/WAF layer (v2); v1 runs only during test windows.

## 10. Observability

- Structured JSON logs carry a `request_id`.
- CloudWatch Embedded Metric Format: `latency_ms` with dimensions `{stage, pipeline}`,
  plus `cache_hit`, `degraded`, and `status_class`.
- Dashboard: p50/p99 per stage, RPS, 5xx rate, cache hit ratio, RDS CPU, connections, and freeable memory.
- Alarms: p99(total) > SLO for 5 consecutive minutes; 5xx > 1% for 5 minutes; RDS freeable memory < 200 MB.

## 11. Alternatives considered

See ADRs: 0001 (Postgres+pgvector vs OpenSearch), 0002 (lexical engine choice rule),
0003 (RDS sizing), 0004 (no NAT; public-subnet Fargate), 0005 (Fargate vs Lambda),
0006 (gain mapping and nDCG definition), 0007 (Bedrock Rerank limits and truncation).
