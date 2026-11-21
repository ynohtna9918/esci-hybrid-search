# SPEC-00: Conventions, configuration, shared types

Applies to every module. Section IDs (`SPEC-00.x`) are referenced from code comments and PRs.

## SPEC-00.1 Environment

- Python **3.12**, managed with **uv** (`uv sync`, `uv run`). Lockfile `uv.lock` is committed.
- `pyproject.toml` defines the package `esci-search` (import name `esci_search`) with `src/` layout.
- Dependency groups:

| Group | Packages (lower-bounded, resolved in `uv.lock`) |
|---|---|
| core | `pandas>=2.2`, `pyarrow>=16`, `numpy>=1.26`, `pydantic>=2.7`, `pydantic-settings>=2.3`, `pyyaml>=6` |
| retrieval | `bm25s>=0.2`, `PyStemmer>=2.2`, `sentence-transformers>=3.0`, `psycopg[binary,pool]>=3.2`, `pgvector>=0.3` |
| cpu | `torch>=2.11` from the PyTorch CPU index |
| gpu | `torch>=2.11` from the PyTorch CUDA 13.0 index |
| service | `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `boto3>=1.35`, `aws-embedded-metrics>=3.2` |
| infra | `aws-cdk-lib>=2.150`, `constructs>=10`, `cdk-nag>=2.28` |
| dev | `pytest>=8`, `pytest-asyncio>=0.23`, `hypothesis>=6`, `scikit-learn>=1.5` (metric oracle only), `ruff>=0.6`, `mypy>=1.11`, `moto>=5` |

- `core` is `[project].dependencies`; `retrieval`, `cpu`, `gpu`, `service`, `infra` are
  `[project.optional-dependencies]` (extras); `dev` is a `[dependency-groups]` group (installed by default).
- **torch** is never a bare dependency. It comes from exactly one of the extras `cpu` or `gpu`:
  - `[tool.uv] conflicts = [[{ extra = "cpu" }, { extra = "gpu" }]]` makes them mutually exclusive.
  - `[tool.uv.sources]` routes `torch` to an explicit index per extra:
    `cpu` → `https://download.pytorch.org/whl/cpu`, `gpu` → `https://download.pytorch.org/whl/cu130`
    (both indexes declared with `explicit = true`, so no other package resolves from them).
  - `retrieval` is always installed together with `cpu` or `gpu`.
  - Local development (WSL2, RTX 5070, sm_120) uses `uv sync --extra retrieval --extra gpu`.
    CI (SPEC-08.1) and the Docker image (SPEC-08.4) use `--extra cpu`.
- `ruff` rules: `E,F,I,B,UP,SIM,RUF`; line length 100. `mypy --strict` on `src/esci_search/`.

## SPEC-00.2 Configuration

- File: `src/esci_search/config.py`.
- `class Settings(BaseSettings)` reads environment variables with prefix `ESCI_` and an optional
  `.env` file. It holds **runtime/infrastructure** values only:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `data_dir` | `Path` | `./data` | root for raw/processed data |
| `results_dir` | `Path` | `./results` | root for run outputs |
| `pg_dsn` | `SecretStr` | `postgresql://esci:esci@localhost:5432/esci` | Postgres DSN for local use |
| `pg_secret_json` | `SecretStr \| None` | `None` | cloud: the RDS secret JSON (`host, port, username, password, dbname`); if set, it overrides `pg_dsn` |
| `pg_pool_min` / `pg_pool_max` | `int` | 1 / 10 | connection pool bounds |
| `ddb_table` | `str` | `esci-search-cache` | DynamoDB cache table |
| `ddb_endpoint_url` | `str \| None` | `None` | set to `http://localhost:8001` for DynamoDB Local |
| `aws_region` | `str` | `us-west-2` | |
| `cache_enabled` | `bool` | `True` | |
| `seed` | `int` | 42 | global default seed |
| `log_json` | `bool` | `False` | JSON logs (service sets True) |

- **Experiment configs** are YAML files in `configs/experiments/`, parsed into
  `class ExperimentConfig(BaseModel)` (strict: `extra="forbid"`):

```yaml
name: p4_hybrid            # must equal the file stem
pipeline: hybrid_rrf       # key in the pipeline registry (SPEC-03.7)
tracks: [R, F]
split: dev                 # dev | ci_dev | test (test only via final-eval)
seed: 42
params:                    # pipeline-specific, validated by the pipeline's params model
  lexical: bm25
  n_lex: 100
  n_dense: 100
  k_rrf: 60
  w_dense: 1.0
```

- `configs/base.yaml` holds shared defaults merged *under* each experiment (experiment wins).
- Function: `load_experiment(path: Path, *, base: Path | None = None) -> ExperimentConfig`.
  `base` defaults to `path.parent.parent / "base.yaml"` (i.e. `configs/base.yaml`); a missing default
  base file means no defaults, an explicitly passed missing file raises `ConfigError`.
- Merge rule: mappings merge recursively (experiment wins key by key, so `params` can be partially
  overridden); scalars and lists from the experiment replace the base value.
- Raises `ConfigError` on unknown keys (in the experiment or the base), invalid YAML, a name/file-stem
  mismatch, or an unknown pipeline.
- Known pipelines: `KNOWN_PIPELINES: Final[frozenset[str]]` in `config.py`, equal to the registry keys of
  SPEC-03.7. Config loading does not import `retrieval/`; `unit/test_pipeline_registry.py` asserts
  `set(PIPELINES) == KNOWN_PIPELINES` so the two cannot drift.
- `split: test` passes schema validation; the guard that restricts it is SPEC-04.6.

## SPEC-00.3 Shared types (`src/esci_search/core_types.py`)

All frozen dataclasses (`@dataclass(frozen=True, slots=True)`):

```python
Label = Literal["E", "S", "C", "I"]
GAIN: Final[Mapping[Label, float]] = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}

class Query:      query_id: int; text: str
class Product:    product_id: str; title: str; brand: str | None; color: str | None;
                  bullets: str | None; doc_text: str
class Scored:     product_id: str; score: float
class RankedList: query_id: int; items: tuple[Scored, ...]   # sorted, see invariant below
```

`RankedList` invariant: items are sorted by `score` descending, then by `product_id` ascending,
and contain no duplicate `product_id`. The constructor `RankedList.from_scores(query_id, scores: Iterable[Scored])`
enforces this. Direct construction with unsorted items raises `ValueError`. A NaN score raises `ValueError`
(the order would be undefined).

## SPEC-00.4 Errors (`src/esci_search/errors.py`)

`EsciError` (base) → `ConfigError`, `DataError`, `IndexError_` (name avoids the builtin),
`RetrievalError`, `DependencyTimeout`, `LeakageError`. Library code raises these, never bare
`Exception`. CLIs map them to exit code 2 with a one-line message.

## SPEC-00.5 Logging (`src/esci_search/logs.py`)

- `get_logger(name: str) -> logging.Logger`.
- `configure_logging(json: bool, level: str = "INFO") -> None`. JSON format fields: `ts`, `level`,
  `logger`, `msg`, `request_id` (if bound), plus any `extra=`.
- `bind_request_id(request_id: str)` sets a `contextvars.ContextVar` read by the JSON formatter.

## SPEC-00.6 Determinism and paths

- Every function that samples or shuffles takes an explicit `seed: int` or a `numpy.random.Generator`.
- `src/esci_search/paths.py` defines `raw_dir()`, `processed_dir()`, `index_dir()`, `runs_dir()`
  from `Settings`. No module hard-codes paths.

## SPEC-00.7 Testing conventions

- `tests/unit/`: no network, no Docker, under 60 s total. Marker: none (default).
- `tests/integration/`: needs `make up-local`. Marker `@pytest.mark.integration`; skipped by `make check`.
- Tests that need the real downloaded dataset use marker `@pytest.mark.data` (run with `make test-data`).
- `tests/gpu/`: tests that need a CUDA device (and may download models). Marker `@pytest.mark.gpu`;
  skipped when `torch.cuda.is_available()` is false; excluded from `make check`; run with `make test-gpu`.
- `pytest` runs with `--strict-markers`; the markers `integration`, `data`, `gpu` are registered in `pyproject.toml`.
- `tests/fixtures/mini_esci/`: 200 `ci_dev` queries with their judged products (Apache-2.0 NOTICE
  included) plus a synthetic 20-product set for pure unit tests.
- Property tests use `hypothesis` for metrics and fusion.

### Tests for this spec
- `test_config.py`: unknown key → `ConfigError`; name ≠ stem → `ConfigError`; unknown pipeline → `ConfigError`;
  base merge precedence (experiment wins, `params` merges recursively).
- `test_types.py`: `from_scores` sorts by score desc then id asc; duplicate ids → `ValueError`;
  unsorted direct construction → `ValueError`; NaN score → `ValueError`.
