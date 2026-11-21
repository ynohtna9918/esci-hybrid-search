# File manifest

Every file that will exist in the repo, the spec that governs it, and the phase in which it is created.
Generated or downloaded artifacts are marked _(gen)_. Do not add files outside this list without updating it.

## Root

| File | Purpose | Spec | Phase |
|---|---|---|---|
| `README.md` | overview, headline results (generated block), navigation | 04.5 | W0 |
| `CLAUDE.md` | working rules for Claude Code | — | W0 |
| `.gitignore` | ignores data, local env, large dev-run artifacts | — | W0 |
| `.env.example` | local env vars template | 00.2, 08.5 | W1 |
| `pyproject.toml` / `uv.lock` | package metadata, dependency groups, ruff/mypy/pytest config | 00.1 | W1 |
| `Makefile` | all developer entry points | 08.6 | W1 (grows each phase) |
| `docker-compose.yml` | local Postgres+pgvector, DynamoDB Local | 08.5 | W1 |
| `Dockerfile` / `.dockerignore` | API image (arm64, models baked in) | 08.4 | W4 |

## `configs/`

| File | Purpose | Spec | Phase |
|---|---|---|---|
| `base.yaml` | shared experiment defaults | 00.2 | W1 |
| `data_checksums.json` | sha256 of raw ESCI files (written on first download, then committed) | 01.1 | W1 |
| `experiments/p0_random.yaml` | P0 | 03.2 | W1 |
| `experiments/p1_bm25.yaml` | P1 | 03.2 | W1 |
| `experiments/p2_pgfts.yaml` | P2 | 03.3 | W2 |
| `experiments/p3_dense.yaml` | P3 | 03.4 | W2 |
| `experiments/p4_hybrid.yaml` | P4 (lexical engine per ADR-0002) | 03.5 | W2 |
| `experiments/p5_hybrid_ce.yaml` | P5 | 03.6 | W3 |
| `experiments/p6_hybrid_bedrock.yaml` | P6 (exploratory, cost-capped) | 03.6 | W3 |
| `service.yaml` | service pipelines, budgets, cache | 05.6 | W4 |
| `frozen.txt` | sha256 list of the configs entering the final evaluation | 04.6 | W5 |

## `src/esci_search/`

| File | Purpose | Spec | Phase |
|---|---|---|---|
| `__init__.py` | `__version__` | — | W1 |
| `config.py` | `Settings`, `ExperimentConfig`, `load_experiment` | 00.2 | W1 |
| `types.py` | `Query`, `Product`, `Scored`, `RankedList`, `GAIN` | 00.3 | W1 |
| `errors.py` | exception hierarchy | 00.4 | W1 |
| `logging.py` | logger factory, JSON formatter, request-id context | 00.5 | W1 |
| `paths.py` | canonical data/results paths | 00.6 | W1 |
| `data/__init__.py`, `data/__main__.py` | `make data` CLI | 01.6 | W1 |
| `data/download.py` | pinned download, LFS guard, checksums | 01.1 | W1 |
| `data/load.py` | load + validate parquet | 01.2 | W1 |
| `data/splits.py` | dev / ci_dev / train / test | 01.3 | W1 |
| `data/text.py` | field cleaning, `doc_text`, `normalize_query` | 01.4 | W1 |
| `data/datacard.py` | writes `docs/DATA_CARD.md` | 01.5 | W1 |
| `index/__init__.py`, `index/__main__.py` | `make index` CLI | 02 | W1 |
| `index/tokenize.py` | lexical tokenizer | 02.1 | W1 |
| `index/bm25_index.py` | build/load BM25, corpus hash | 02.2 | W1 |
| `index/embed.py` | `Encoder`, resumable corpus embedding | 02.3 | W2 |
| `index/pg_schema.sql` | Postgres DDL | 02.4 | W2 |
| `index/sql.py` | canonical SQL constants | 02.4 | W2 |
| `index/pg_load.py` | schema apply, idempotent bulk load, HNSW build, `index_meta` | 02.5 | W2 |
| `index/s3_upload.py` | `upload-s3` subcommand | 02.5 | W4 |
| `retrieval/__init__.py` | — | — | W1 |
| `retrieval/base.py` | `Retriever`, `Reranker`, `BaseRetriever` | 03.1 | W1 |
| `retrieval/random_ranker.py` | P0 | 03.2 | W1 |
| `retrieval/bm25.py` | P1 | 03.2 | W1 |
| `retrieval/pgfts.py` | P2 | 03.3 | W2 |
| `retrieval/dense.py` | P3, exact + pgvector backends | 03.4 | W2 |
| `retrieval/fusion.py` | `rrf`, `HybridRetriever` | 03.5 | W2 |
| `retrieval/rerank_ce.py` | cross-encoder reranker | 03.6 | W3 |
| `retrieval/rerank_bedrock.py` | Bedrock reranker + budget guard | 03.6 | W3 |
| `retrieval/pipeline.py` | `Resources`, registry, params models | 03.7 | W1 (P0/P1), extended W2–W3 |
| `eval/__init__.py`, `eval/__main__.py` | `run` / `compare` / `final` / `gate` CLI | 04 | W1 |
| `eval/qrels.py` | queries, qrels, candidates, subsets, test lock | 04.1 | W1 |
| `eval/metrics.py` | nDCG, condensed nDCG, Judged@k, Recall_E@k | 04.2 | W1 |
| `eval/significance.py` | bootstrap, randomization test, Holm | 04.3 | W1 |
| `eval/runner.py` | run directories | 04.4 | W1 |
| `eval/final.py` | final-evaluation guard and runner | 04.6 | W1 (guard), used W5 |
| `eval/gate.py` | CI relevance regression gate | 08.2 | W1 |
| `service/__init__.py` | — | — | W4 |
| `service/app.py` | FastAPI app, lifespan, routes, error handlers | 05.1–05.2 | W4 |
| `service/api_models.py` | request/response models | 05.1 | W4 |
| `service/deps.py` | pool, encoder, rerankers, limiter | 05.2 | W4 |
| `service/search.py` | async search flow, budgets, degradation | 05.3 | W4 |
| `service/cache.py` | DynamoDB cache-aside; `create-local-table` CLI | 05.4 | W4 |
| `service/telemetry.py` | middleware, access log, EMF metrics | 05.5 | W4 |
| `service/prefetch_models.py` | bake models into the image | 08.4 | W4 |

## `infra/`

| File | Purpose | Spec | Phase |
|---|---|---|---|
| `app.py`, `cdk.json` | CDK app, context | 06.1 | W4 |
| `stacks/__init__.py` | — | — | W4 |
| `stacks/account.py` | OIDC deploy role, AWS Budget | 06.5 | W4 |
| `stacks/network.py` | VPC, endpoints, security groups | 06.2 | W4 |
| `stacks/data.py` | RDS, DynamoDB, S3, ECR, secret | 06.3 | W4 |
| `stacks/service.py` | ECS, task definitions (api, loader, loadgen), ALB | 06.4, 07.0 | W4 |
| `stacks/monitoring.py` | dashboard, alarms, SNS | 06.5 | W4 |
| `tests/test_stacks.py` | template assertions | 06 | W4 |

## `loadtest/`

| File | Purpose | Spec | Phase |
|---|---|---|---|
| `make_query_file.py` | uniform and Zipf request sequences, `h_max` | 07.1 | W5 |
| `k6/search.js` | scenarios and thresholds | 07.2 | W5 |
| `analyze.py` | percentiles from raw samples, CloudWatch pull, `h` check | 07.3 | W5 |
| `Dockerfile`, `entrypoint.sh` | in-region load generator image | 08.4 | W5 |
| `data/` _(gen, ignored)_ | generated request files | 07.1 | W5 |

## `scripts/`

| File | Purpose | Spec | Phase |
|---|---|---|---|
| `make_results_table.py` | `results/RESULTS.md` + README block | 04.5 | W1 |
| `smoke_test.py` | readiness, golden queries, 422 check | 08.3 | W4 |
| `cloud_up.sh` / `cloud_down.sh` | session lifecycle | 06.7 | W4 |
| `cloud_load_index.sh` | S3 upload + loader task | 06.6 | W4 |
| `run_loadtest.sh` | loadgen task + analysis | 07.4 | W5 |
| `cost_snapshot.sh` | Cost Explorer export | 06.7 | W5 |

## `tests/`

| File | Spec | Phase |
|---|---|---|
| `conftest.py` (markers `integration`, `data`; shared fixtures) | 00.7 | W1 |
| `unit/test_config.py`, `unit/test_types.py` | 00 | W1 |
| `unit/test_text.py`, `unit/test_splits.py`, `unit/test_load_validation.py`, `unit/test_download.py` | 01 | W1 |
| `unit/test_tokenize.py`, `unit/test_bm25.py` | 02 | W1 |
| `unit/test_embed.py` | 02 | W2 |
| `unit/test_random_ranker.py`, `unit/test_pipeline_registry.py` | 03 | W1 |
| `unit/test_fusion.py` | 03 | W2 |
| `unit/test_rerank_contract.py`, `unit/test_bedrock_guard.py` | 03 | W3 |
| `unit/test_metrics.py`, `unit/test_significance.py`, `unit/test_leakage_guard.py`, `unit/test_runner_smoke.py` | 04 | W1 |
| `unit/test_api_validation.py`, `unit/test_search_degradation.py`, `unit/test_cache.py`, `unit/test_request_id.py` | 05 | W4 |
| `unit/test_smoke_script.py` | 08 | W4 |
| `unit/test_make_query_file.py`, `unit/test_analyze.py` | 07 | W5 |
| `integration/test_pg_load.py`, `integration/test_retrievers_pg.py` | 02, 03 | W2 |
| `integration/test_service_e2e.py` | 05 | W4 |
| `data/test_counts.py` | 01 | W1 |
| `fixtures/synthetic/products.json` (20 hand-written products) | 00.7 | W1 |
| `fixtures/mini_esci/{queries,qrels,products}.parquet`, `fixtures/mini_esci/NOTICE` | 00.7, 08.2 | W1 |
| `fixtures/golden_queries.json` | 05, 08.3 | W4 |

## `.github/workflows/`

| File | Spec | Phase |
|---|---|---|
| `ci.yml` | 08.1, 08.2 | W1 |
| `deploy.yml` | 08.3 | W4 |

## `docs/`

| File | Purpose | Phase |
|---|---|---|
| `PRFAQ.md`, `DESIGN.md`, `EVAL_PROTOCOL.md`, `ROADMAP.md`, `FILE_MANIFEST.md` | specs and plan | W0 |
| `specs/00-conventions.md` … `specs/08-ci-cd-build.md` | module specs | W0 |
| `adr/0000-template.md`, `adr/0001` … `adr/0007` | decisions (some completed with measurements in W2–W3) | W0 |
| `AI_USAGE.md` | log of AI-generated code that was caught wrong, and how | W0, ongoing |
| `DATA_CARD.md` _(gen)_ | dataset statistics | W1 |

## `results/`

| Path | Committed? | Phase |
|---|---|---|
| `RESULTS.md` _(gen)_ | yes | W1+ |
| `ci_baseline.json` | yes (label-gated) | W1 |
| `bedrock_usage.json` | yes (the budget counter must survive clones) | W3 |
| `runs/<run_id>/` dev runs | config, `metrics.json`, `env.json`, `timings.json` only; parquet files ignored | W1+ |
| `comparisons/*.json` | yes | W1+ |
| `final/<frozen_hash>/` | yes, everything | W5 |
| `loadtest/<run_id>/`, `loadtest/INDEX.md` | yes | W5 |
| `cost/*.json` | yes | W5 |
