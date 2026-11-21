# SPEC-07: Load testing and latency/cost measurement

Directory: `loadtest/`. Normative definitions: EVAL_PROTOCOL §10, DESIGN §7–§8.

## SPEC-07.0 Where the load generator runs (important)

k6 runs **inside `us-west-2`** as an ECS `RunTask` (`loadgen` task, SPEC-06 addendum below), not on the laptop.
A client in another region (e.g. Shanghai → Oregon) would add 150 ms+ of WAN RTT and make p99 meaningless.
The load generator targets the API task's **private IP on port 8000** directly, so the numbers are service latency
**excluding the ALB**. ALB overhead is not measured in v1; the README states this.

Infra addendum (implemented in `infra/stacks/service.py`, tested in `infra/tests/test_stacks.py`):
- `loadgen_sg` (no ingress); `svc_sg` also admits TCP 8000 from `loadgen_sg`.
- Task definition `loadgen`: image `esci-loadgen:<tag>` (from `loadtest/Dockerfile`), 1 vCPU / 2 GB ARM64.
  Its task role is limited to `s3:GetObject` on `artifacts/loadtest/inputs/*` and `s3:PutObject` on `artifacts/loadtest/runs/*`.
- The API task gets `ESCI_ALLOW_CACHE_BYPASS=true` only when deployed with `-c loadtest_session=true`.

## SPEC-07.1 Request inputs (`loadtest/make_query_file.py`)

```
python loadtest/make_query_file.py --out loadtest/data/ --zipf 0.8 1.0 1.2 --n-requests 50000 --seed 42
```
- Query pool: the normalized query strings of the **`train`** split (never test; no labels are used).
- `queries_uniform.json`: the pool in a seeded random order (for `steady`/`ramp`, with cache bypass).
- `zipf_{s}.json`: `n_requests` draws where pool rank $r$ (a seeded random permutation) has probability
  $p(r) = r^{-s} / \sum_{j=1}^{N} j^{-s}$:
  - $r$: the popularity rank of a query (1 = most popular)
  - $s$: the Zipf exponent (larger means more skewed toward popular queries)
  - $N$: the pool size (number of distinct train queries)
- For each file, the script prints the **theoretical warm-cache hit-rate ceiling**
  $h_{\max} = 1 - U/n$, where $U$ is the number of distinct queries in the sequence and $n$ is the number of requests.
  The measured $h$ must be ≤ $h_{\max}$. A higher value means a bug.
- Files are uploaded to `s3://<artifacts>/loadtest/inputs/`.

## SPEC-07.2 Scenarios (`loadtest/k6/search.js`)

Env: `TARGET_URL`, `SCENARIO`, `PIPELINE` (default `hybrid_rrf`), `RATE`, `QUERY_FILE`, `SLO_P99_MS`.

| Scenario | Executor | Shape | Cache |
|---|---|---|---|
| `steady` | `constant-arrival-rate` | `RATE` RPS for 5 min (+30 s warm-up excluded) | bypass (`X-Cache-Bypass: 1`) |
| `ramp` | `ramping-arrival-rate` | 5→10→20→40→60→80 RPS, 2 min per stage | bypass |
| `zipf` | `constant-arrival-rate` | 20 RPS for 10 min; the first 2 min are excluded from `h` | **on** |

- `preAllocatedVUs: 50`, `maxVUs: 400`. Each request is tagged `{scenario, pipeline}`.
- Thresholds: `http_req_failed: rate<0.005`; `http_req_duration{expected_response:true}: p(99)<SLO_P99_MS`.
- Output: `--out json=raw.ndjson` (raw samples) + `handleSummary` → `summary.json`; the entrypoint uploads both
  to `s3://<artifacts>/loadtest/runs/<run_id>/`.
- **Finding Q:** `ramp` gives the coarse knee; then `steady` at that rate (and at one step below, if needed)
  confirms Q under the protocol's 5-minute rule.

## SPEC-07.3 Analysis (`loadtest/analyze.py`)

```
python loadtest/analyze.py --run s3://.../loadtest/runs/<run_id>/ --out results/loadtest/<run_id>/
```
- Download `raw.ndjson`; compute client-side p50/p95/p99, error rate, and achieved RPS **from raw samples**,
  per scenario stage (ramp) or for the whole window (steady/zipf), excluding warm-up.
- Pull the server-side `LatencyMs` p50/p99 per stage for the same window with CloudWatch `GetMetricData`.
- `zipf`: `h` = the sum of `CacheHit` divided by the request count after warm-up; check `h ≤ h_max` (SPEC-07.1).
- Write `summary.json` (all numbers + window timestamps + git sha + task size + `index_version`) and
  `latency_over_time.png`. Append a row to `results/loadtest/INDEX.md`.

## SPEC-07.4 Runner (`scripts/run_loadtest.sh`)

`make loadtest SCENARIO=steady PIPELINE=hybrid_rrf RATE=20`:
1. Resolve the API task's private IP (`aws ecs list-tasks` / `describe-tasks`).
2. `aws ecs run-task` the `loadgen` task with the env above; wait; fail if exit ≠ 0 (a k6 threshold breach is reported, not hidden).
3. Run `analyze.py` and print the SLO pass/fail line.

## Tests

| Test | Asserts |
|---|---|
| `unit/test_make_query_file.py` | uses only the train split; Zipf sequence is seeded and reproducible; empirical rank-1 frequency ≈ $p(1)$ within 10% at n=50k; `h_max` formula is correct on a hand example |
| `unit/test_analyze.py` | percentiles from a synthetic ndjson match `numpy.percentile` (method `linear`); warm-up exclusion; the `h > h_max` check fires |
| `loadtest/k6/search.js` | `k6 inspect` passes in CI (syntax and options) |
