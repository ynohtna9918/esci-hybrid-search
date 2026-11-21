# SPEC-05: Online search service

Package: `src/esci_search/service/`. Run: `make serve` (`uvicorn esci_search.service.app:app --port 8000 --workers 1`).
Config: `configs/service.yaml` + `Settings` (SPEC-00.2).

## SPEC-05.1 HTTP API (`service/api_models.py`)

### `GET /healthz`: liveness
`200 {"status": "ok", "git_sha": "<sha7>"}` whenever the process is up. No dependency calls.

### `GET /readyz`: readiness (ALB health check)
`200 {"status": "ready", "index_version": "..."}` only after startup warm-up has finished and a Postgres ping
(`SELECT 1`, 200 ms timeout) succeeds. Otherwise `503 {"status": "not_ready", "reason": "..."}`.

### `POST /v1/search`

Request:
```json
{ "query": "iphone 13 case clear", "k": 10, "pipeline": "hybrid_rrf", "debug": false }
```
| Field | Rule |
|---|---|
| `query` | string; 1–256 chars after strip |
| `k` | int, 1–50, default 10 |
| `pipeline` | must be in `service.allowed_pipelines`; default `service.default_pipeline` |
| `debug` | bool, default false; adds per-input-list ranks to each result |

Response `200`:
```json
{
  "request_id": "01JD...", "pipeline": "hybrid_rrf", "index_version": "3fa2c1d0-e5-small-v2-20261205",
  "cache_hit": false, "degraded": false, "degraded_reasons": [],
  "results": [ { "rank": 1, "product_id": "B08XYZ", "title": "...", "brand": "...", "score": 0.0325 } ],
  "timings_ms": { "cache": 3.1, "encode": 11.2, "lexical": 24.0, "dense": 9.8, "fuse": 0.2,
                  "rerank": 0.0, "hydrate": 4.1, "total": 52.3 }
}
```
- Every stage key is always present (0.0 if skipped). On a cache hit, `timings_ms` reflects the current request, not the cached one.
- `degraded_reasons` ⊆ {`dense_timeout`, `dense_error`, `lexical_timeout`, `lexical_error`, `rerank_timeout`, `rerank_error`}.

Errors (body `{"error": {"code": str, "message": str}, "request_id": str}`):
| Status | `code` | When |
|---|---|---|
| 422 | `invalid_request` | validation failure (FastAPI handler overridden to this shape) |
| 503 | `dependency_unavailable` | Postgres pool unavailable, or both lexical and dense failed |
| 503 | `deadline_exceeded` | total deadline (1,500 ms) exceeded |

Headers:
- Honor an incoming `X-Request-ID` (≤ 64 chars, `[A-Za-z0-9-]`), else generate a ULID; always echo it.
- `X-Cache-Bypass: 1` skips cache get **and** put. It is honored only when `ESCI_ALLOW_CACHE_BYPASS=true`
  (set during load-test sessions, so uncached latency can be measured; SPEC-07.2). Otherwise it is ignored.

## SPEC-05.2 Lifecycle and dependencies (`service/app.py`, `service/deps.py`)

FastAPI `lifespan`:
1. `configure_logging(json=True)`; load `configs/service.yaml`.
2. Create `psycopg_pool.AsyncConnectionPool(min, max)`; register pgvector types on each connection.
3. Read the active `index_version` from `index_meta`; fail startup if none is active.
4. Load the `Encoder` (SPEC-02.3) and run one warm-up encode; if `hybrid_ce` is allowed, load the cross-encoder
   and warm it up; if `hybrid_bedrock` is allowed, create the boto3 client.
5. Create the DynamoDB client and the `SearchCache`. Mark the service ready.

CPU-bound work (encoding, cross-encoder) runs in `anyio.to_thread.run_sync` behind a
`CapacityLimiter(ESCI_CPU_CONCURRENCY, default 2)`. `torch.set_num_threads(ESCI_TORCH_THREADS)` (default = vCPU count).

## SPEC-05.3 Search flow and budgets (`service/search.py`)

```python
async def search(req: SearchRequest, ctx: RequestContext) -> SearchResponse
```

| Step | Budget | On timeout or error |
|---|---|---|
| 1. normalize query (`normalize_query`, SPEC-01.4); build the cache key | — | — |
| 2. cache `get` | 50 ms | treat as a miss; metric `CacheError` |
| 3a. lexical retrieve `n_lex`: `pgfts` → async SQL from `index/sql.py` with `SET LOCAL statement_timeout`; `bm25` → in-process `Bm25Index.search` in a worker thread | 150 ms | degrade: `lexical_*` |
| 3b. encode + dense retrieve `n_dense` (in parallel with 3a via `asyncio.gather`) | 150 ms | degrade: `dense_*` |
| 4. RRF fuse (`retrieval.fusion.rrf`) | — | — |
| 5. rerank top `n_rerank` (CE: 600 ms; Bedrock: 800 ms) | per pipeline | keep the fused order; `rerank_*` |
| 6. hydrate `title, brand` with one `WHERE product_id = ANY(%s)` query | 100 ms | 503 `dependency_unavailable` |
| 7. respond; if not degraded, cache `put` in the background | — | log only |

- If both 3a and 3b fail → 503. Total hard deadline: 1,500 ms → 503 `deadline_exceeded`.
- Retrieval logic (fusion, rerank contract) is **imported** from SPEC-03, never re-implemented.
  Only the async I/O wrappers live here.

## SPEC-05.4 Cache (`service/cache.py`)

```python
class SearchCache:
    def __init__(self, client, table: str, *, ttl_s: int = 86_400, get_timeout_ms: int = 50, max_inflight_puts: int = 16)
    @staticmethod
    def key(norm_query: str, k: int, pipeline: str, index_version: str) -> str   # sha256 hex of "|".join(...)
    async def get(self, key: str) -> dict | None
    def put_background(self, key: str, body: dict) -> None
```
- `payload` = zlib(JSON(body without `timings_ms`, `request_id`, `cache_hit`)); skip if > 350 KB (DynamoDB item limit is 400 KB).
- Puts are bounded by a semaphore; when full, drop the put and increment `CachePutDropped`. A failure never reaches the client.
- Including `index_version` in the key invalidates the cache naturally on reindex. Nothing is ever flushed.

## SPEC-05.5 Telemetry (`service/telemetry.py`)

- Middleware: request id binding (SPEC-00.5); one structured access log per request (`method, path, status,
  pipeline, cache_hit, degraded, total_ms, k`, query truncated to 256 chars).
- CloudWatch EMF (`aws-embedded-metrics`, `AWS_EMF_ENVIRONMENT=Local` → stdout, ingested via the awslogs driver),
  namespace `EsciSearch`:

| Metric | Unit | Dimensions |
|---|---|---|
| `LatencyMs` | Milliseconds | `Pipeline, Stage` (stages of §5.3 + `total`) |
| `CacheHit` | Count (0/1) | `Pipeline` |
| `Degraded` | Count (0/1) | `Pipeline` |
| `Requests` | Count | `StatusClass` (2xx/4xx/5xx) |
| `CacheError`, `CachePutDropped` | Count | — |

- Locally (`ESCI_EMF=off`), metrics are logged at DEBUG instead.

## SPEC-05.6 Service config (`configs/service.yaml`)

```yaml
default_pipeline: hybrid_rrf
allowed_pipelines: [pgfts, dense, hybrid_rrf, hybrid_ce]   # hybrid_bedrock is added only for E1 sessions
params_from:                                              # copy frozen params from these experiments
  hybrid_rrf: p4_hybrid
  hybrid_ce: p5_hybrid_ce
budgets_ms: { cache_get: 50, lexical: 150, dense: 150, rerank_ce: 600, rerank_bedrock: 800, hydrate: 100, total: 1500 }
cache: { ttl_s: 86400 }
```
**Evaluated = deployed.** Pipeline params are copied verbatim from the frozen experiment configs, including the
lexical engine, which ADR-0002 decides for both the P4 config and the service. The service refuses to start if a
`params_from` config is not listed in `configs/frozen.txt` (after W3), so no untested configuration can ship.

## Tests

| Test | Asserts |
|---|---|
| `unit/test_api_validation.py` | empty/oversize query → 422 with the error shape; k bounds; unknown pipeline → 422 |
| `unit/test_search_degradation.py` | (fake retrievers) dense raises → 200, `degraded`, lexical-only results; both fail → 503; rerank timeout → fused order |
| `unit/test_cache.py` | key stable and sensitive to every component; oversize payload skipped; put failure swallowed; semaphore drop counted |
| `unit/test_request_id.py` | incoming id echoed; invalid id replaced; generated id is a ULID |
| `integration/test_service_e2e.py` | Docker PG + DynamoDB Local: search returns k sorted results; an identical second call has `cache_hit: true`; a new active `index_version` → miss |
| `tests/fixtures/golden_queries.json` | 10 dev queries whose top-1 E product the offline hybrid ranks in the top 3; used by the deploy smoke test (SPEC-08.3) |
