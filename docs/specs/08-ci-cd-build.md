# SPEC-08: CI/CD, container build, local environment, Makefile

## SPEC-08.1 CI (`.github/workflows/ci.yml`)

Triggers: push to `main`, every pull request. `concurrency: ci-${{ github.ref }}` with cancel-in-progress.

| Job | Runner | Steps |
|---|---|---|
| `check` | `ubuntu-24.04` | `uv sync --frozen` → `ruff check` → `ruff format --check` → `mypy` → `pytest -m "not integration and not data"` |
| `integration` | `ubuntu-24.04` | service containers `pgvector/pgvector:pg17` (health: `pg_isready`) and `amazon/dynamodb-local` → apply the schema → `pytest -m integration` |
| `infra` | `ubuntu-24.04` | `npm i -g aws-cdk@2` → `cdk synth` with dummy context → `pytest infra/tests` |
| `loadtest-lint` | `ubuntu-24.04` | `k6 inspect loadtest/k6/search.js` |
| `eval-gate` | `ubuntu-24.04` | SPEC-08.2 |

Caches: uv cache; the HuggingFace cache keyed on model names (for `eval-gate`).
All third-party actions are pinned to commit SHAs.

## SPEC-08.2 Relevance regression gate

- Data: `tests/fixtures/mini_esci/`, the 200 `ci_dev` queries, their judged candidates, and those products' text
  (committed, with an Apache-2.0 NOTICE). BM25 IDF here comes from the fixture products only, so the gate numbers are
  **not** comparable to full runs. They are only compared with themselves over time.
- Command: `python -m esci_search.eval gate --fixture tests/fixtures/mini_esci --baseline results/ci_baseline.json`.
- Pipelines: `random`, `bm25`, `dense` (exact), `hybrid_rrf`, `hybrid_ce`; Track R only.
- Pass rule: for each pipeline, `ndcg >= baseline - 0.005`; `random` must equal the baseline exactly (a determinism check).
- `make ci-baseline` regenerates the baseline. A PR that changes it needs the `baseline-update` label and an
  explanation in the description; the gate job checks for the label whenever the file changes.

## SPEC-08.3 Deploy (`.github/workflows/deploy.yml`)

- Trigger: `workflow_dispatch` only. Environment `aws-dev` (manual approval configured in GitHub).
  `permissions: id-token: write, contents: read`.
- Runner `ubuntu-24.04-arm` (native arm64 build; no QEMU).
- Steps: OIDC `configure-aws-credentials` (role `esci-deploy`) → build and push `esci-search:<sha7>` to ECR →
  `cdk deploy EsciService EsciMonitoring -c image_tag=<sha7> -c ingress_cidr=<stored var>` →
  **temporary ingress**: add the runner's public IP /32 to `alb_sg` with description `gha-<run_id>` →
  smoke test → revoke the rule in an `if: always()` step.
- Smoke test (`scripts/smoke_test.py --base-url ...`):
  1. `/readyz` returns 200 within 5 min;
  2. each query in `tests/fixtures/golden_queries.json` has its expected `product_id` in the top 10 (`hybrid_rrf`);
  3. an empty query returns 422 with the error shape.
- On failure: the job fails; the ECS deployment circuit breaker rolls back the service.
- The deploy role may call `ec2:AuthorizeSecurityGroupIngress` and `ec2:RevokeSecurityGroupIngress` only on `alb_sg`.

## SPEC-08.4 Container image (`Dockerfile`, `.dockerignore`)

- Multi-stage; base `python:3.12-slim-bookworm` pinned by digest; `linux/arm64`.
- Install the core + retrieval + service groups with `uv sync --frozen --no-dev` (torch from PyPI aarch64 wheels, which are CPU-only).
- **Models baked in at build time:** `python -m esci_search.service.prefetch_models --dest /models` downloads
  `intfloat/e5-small-v2` and `cross-encoder/ms-marco-MiniLM-L-12-v2` at pinned HF revisions;
  runtime sets `HF_HUB_OFFLINE=1` and `HF_HOME=/models`. Startup never touches the network for models.
- Runs as non-root `app` (uid 10001). `CMD ["uvicorn", "esci_search.service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]`.
- Size target: < 2.5 GB (measured and recorded in the PR that adds it).
- `loadtest/Dockerfile`: `grafana/k6` binary copied into `amazon/aws-cli` (both pinned); entrypoint
  `loadtest/entrypoint.sh` (fetch inputs from S3 → run k6 → upload outputs).

## SPEC-08.5 Local environment (`docker-compose.yml`, `.env.example`)

| Service | Image | Port | Notes |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | 5432 | user/db/password `esci`; `-c shared_buffers=1GB -c maintenance_work_mem=2GB`; named volume; healthcheck `pg_isready` |
| `dynamodb` | `amazon/dynamodb-local` | 8001→8000 | `-jar DynamoDBLocal.jar -inMemory -sharedDb` |

`make up-local` runs `docker compose up -d --wait`, applies the schema, and creates the cache table
(`python -m esci_search.service.cache create-local-table`).

## SPEC-08.6 Makefile targets

| Target | Command(s) |
|---|---|
| `check` | `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not integration and not data"` |
| `test` | `check` + `uv run pytest -m integration` |
| `test-data` | `uv run pytest -m data` |
| `up-local` / `down-local` | SPEC-08.5 / `docker compose down` |
| `data` | `uv run python -m esci_search.data` |
| `index` | `uv run python -m esci_search.index all` |
| `eval` | `uv run python -m esci_search.eval run --exp configs/experiments/$(EXP).yaml` |
| `final-eval` | `FINAL_EVAL=1 uv run python -m esci_search.eval final` |
| `results` | `uv run python scripts/make_results_table.py` |
| `ci-baseline` | `uv run python -m esci_search.eval gate --fixture tests/fixtures/mini_esci --write-baseline results/ci_baseline.json` |
| `serve` | `uv run uvicorn esci_search.service.app:app --reload --port 8000` |
| `cloud-up` / `cloud-down` / `cloud-load-index` | `scripts/cloud_up.sh` / `scripts/cloud_down.sh` / `scripts/cloud_load_index.sh` |
| `loadtest` | `scripts/run_loadtest.sh $(SCENARIO) $(PIPELINE) $(RATE)` |
| `cost-snapshot` | `scripts/cost_snapshot.sh $(FROM) $(TO)` |

## Tests

- `ci.yml` and `deploy.yml` pass `actionlint` (run in the `check` job).
- `unit/test_smoke_script.py`: the smoke test fails on a missing golden product and on a non-422 for an empty query (HTTP mocked).
- The image build is verified in the PR that adds the Dockerfile: `docker run ... /readyz` against local compose returns 200.
