# SPEC-03: Retrieval, fusion, reranking, pipelines

Package: `src/esci_search/retrieval/`. Pure library code; used by the eval runner (SPEC-04) and the service (SPEC-05).

## SPEC-03.1 Interfaces (`retrieval/base.py`)

```python
class Retriever(Protocol):
    name: str
    def retrieve(self, query: Query, k: int) -> RankedList                          # Track F: full corpus
    def score(self, query: Query, product_ids: Sequence[str]) -> RankedList         # Track R: given candidates
    def retrieve_batch(self, queries: Sequence[Query], k: int) -> list[RankedList]  # default: loop
    def score_batch(self, items: Sequence[tuple[Query, Sequence[str]]]) -> list[RankedList]

class Reranker(Protocol):
    name: str
    def rerank(self, query: Query, candidates: RankedList, top_n: int) -> RankedList
```

- `score()` must return **every** given id exactly once (score 0.0 if the retriever has no signal for it).
- `BaseRetriever` provides the default batch methods. Dense retrieval overrides them to batch-encode.
- **Rerank output contract:** the first `min(top_n, len)` positions are ordered by reranker score; the remaining
  positions keep their input relative order. Tail scores are rewritten to `min(head) - 1 - i * 1e-6`
  (`i` = 0-based tail index) so the `RankedList` invariant (SPEC-00.3) holds. Use the helper
  `RankedList.concat_head_tail(head, tail)`.

## SPEC-03.2 Baselines (`retrieval/random_ranker.py`, `retrieval/bm25.py`)

- `RandomRanker(seed)`: `score()` assigns uniform random scores from
  `np.random.default_rng([seed, query_id])`, so the result for a query does not depend on evaluation order.
  `retrieve()` raises `RetrievalError` (Track R only).
- `Bm25Retriever(index: Bm25Index)`: delegates to `Bm25Index.search` / `score_candidates` (SPEC-02.2).

## SPEC-03.3 Postgres full-text (`retrieval/pgfts.py`)

- `PgFtsRetriever(pool: ConnectionPool, statement_timeout_ms: int = 2000)`.
- `retrieve`: `sql.PGFTS_RETRIEVE` (SPEC-02.4).
- `score`: `sql.PGFTS_SCORE`; ids not returned get 0.0.
- An empty tsquery (all stopwords) returns an empty list for `retrieve` and zeros for `score`. It never raises.
- Ranking cost note: `ts_rank_cd` is computed for **every** row that matches, so common-term queries are slow.
  The per-query latency distribution goes into ADR-0002.

## SPEC-03.4 Dense (`retrieval/dense.py`)

```python
class DenseRetriever(BaseRetriever):
    def __init__(self, encoder: Encoder, backend: Literal["exact", "pgvector"],
                 *, emb_path: Path | None = None, pool: ConnectionPool | None = None,
                 ef_search: int = 100) -> None
```

- `exact` backend: loads `embeddings.npy` (fp16) and `product_ids.npy`; scores = `E @ q` computed in fp32 chunks
  of 100k rows; `retrieve` uses `np.argpartition`, then a stable sort. It is the ground truth for HNSW fidelity
  (EVAL_PROTOCOL §8.6).
- `pgvector` backend: `sql.DENSE_RETRIEVE` with `SET LOCAL hnsw.ef_search` (`ef_search` is a validated int, so it is
  formatted into the SET statement rather than bound as a parameter).
- `score` always computes exact dot products against the candidates' stored vectors (both backends),
  so Track R is independent of HNSW.
- `retrieve_batch` encodes all queries in one batch (size 256), then searches.

## SPEC-03.5 Fusion (`retrieval/fusion.py`)

```python
def rrf(lists: Sequence[RankedList], weights: Sequence[float], *, k_rrf: int = 60, top_n: int | None = None) -> RankedList

class HybridRetriever(BaseRetriever):
    def __init__(self, lexical: Retriever, dense: Retriever, *, n_lex: int = 100, n_dense: int = 100,
                 k_rrf: int = 60, w_dense: float = 1.0, n_out: int = 100) -> None
```

- Formula: DESIGN §4. Weight order = list order; the lexical weight is fixed at 1.0.
- Ranks are 1-based **positions** in each input list (input ties are already broken by SPEC-00.3).
- Track R: `score()` fuses the two `score()` lists over the same candidate set. Track F: fuses `retrieve()` lists.
- `rrf` depends only on ranks, never on raw scores (a property test checks invariance to score rescaling).

## SPEC-03.6 Rerankers (`retrieval/rerank_ce.py`, `retrieval/rerank_bedrock.py`)

**Cross-encoder**
- `CrossEncoderReranker(model_name="cross-encoder/ms-marco-MiniLM-L-12-v2", max_length=256, batch_size=32, device=None)`.
- Pairs are (`query.text`, `doc_text`). `doc_text` lookup is injected as `Callable[[Sequence[str]], list[str]]`
  (parquet dict offline; a Postgres hydrate query online).
- Score = raw logit. Deterministic in eval mode (`torch.inference_mode`, no dropout).

**Bedrock**
- `BedrockReranker(model_id: Literal["cohere.rerank-v3-5:0", "amazon.rerank-v1:0"], region="us-west-2", max_queries: int)`.
- Calls `boto3.client("bedrock-agent-runtime").rerank(...)` with `rerankingConfiguration.type = "BEDROCK_RERANKING_MODEL"`
  and `modelArn = f"arn:aws:bedrock:{region}::foundation-model/{model_id}"`; sources are inline text documents.
- **Cost guard:** every call increments `results/bedrock_usage.json` (`{model_id: n_calls}`); once
  `n_calls >= max_queries`, the reranker raises `RetrievalError("bedrock budget exhausted")`. Default `max_queries=500`.
- Retries: botocore `standard` mode, 3 attempts; timeouts connect 2 s / read 5 s.
- Before the first use in W3: record the documented per-request document count and size limits
  in ADR-0007, and truncate `doc_text` accordingly.

## SPEC-03.7 Pipeline registry (`retrieval/pipeline.py`)

```python
class Resources:                     # lazy, cached handles shared across pipelines
    def bm25(self, params: Bm25Params) -> Bm25Index
    def encoder(self, spec: EncoderSpec) -> Encoder
    def pg_pool(self) -> ConnectionPool
    def doc_text_lookup(self) -> Callable[[Sequence[str]], list[str]]

class Pipeline(Protocol):
    name: str
    def run_track_r(self, queries: Sequence[Query], candidates: Mapping[int, Sequence[str]]) -> list[RankedList]
    def run_track_f(self, queries: Sequence[Query], k: int = 100) -> list[RankedList]

PIPELINES: Final[dict[str, PipelineFactory]]   # keys: random, bm25, pgfts, dense, hybrid_rrf, hybrid_ce, hybrid_bedrock
def build_pipeline(name: str, params: Mapping[str, Any], resources: Resources) -> Pipeline
```

Params models (pydantic, `extra="forbid"`):

| Pipeline | Params (defaults) |
|---|---|
| `random` | `seed` (from config) |
| `bm25` | `k1=1.2, b=0.75` |
| `pgfts` | — |
| `dense` | `backend="pgvector"` (Track R always exact), `ef_search=100`, `encoder="intfloat/e5-small-v2"` |
| `hybrid_rrf` | `lexical="bm25"`, `n_lex=100`, `n_dense=100`, `k_rrf=60`, `w_dense=1.0`, `n_out=100` + dense params |
| `hybrid_ce` | `hybrid_rrf` params + `n_rerank=50`, `ce_model`, `ce_batch_size=32`, `ce_max_length=256` |
| `hybrid_bedrock` | `hybrid_rrf` params + `n_rerank=50`, `model_id="cohere.rerank-v3-5:0"`, `max_queries=500` |

Track R for rerank pipelines: rerank the top `n_rerank` of the hybrid ordering of the judged candidates.

## Tests

| Test | Asserts |
|---|---|
| `unit/test_random_ranker.py` | same (seed, query_id) → same order regardless of call order; `retrieve` raises |
| `unit/test_fusion.py` | hand-computed 3-doc example; a doc in one list gets one term; ranks-only invariance (hypothesis: rescale scores); weights applied; deterministic ties |
| `unit/test_rerank_contract.py` | fake reranker: head ordered by its scores, tail order preserved, invariant holds; `top_n > len` handled |
| `unit/test_bedrock_guard.py` | (moto/stub) budget counter increments; exceeding the limit raises; request shape matches the API |
| `unit/test_pipeline_registry.py` | every key builds with defaults (with fake resources); unknown param → `ConfigError` |
| `integration/test_retrievers_pg.py` | pgfts and pgvector on fixture data: k respected, sorted, empty tsquery handled; HNSW vs exact overlap@10 ≥ 0.9 on the fixture |
