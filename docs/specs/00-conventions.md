# SPEC-00: Conventions, configuration, shared types

Applies to every module. Section IDs (`SPEC-00.x`) are referenced from code comments and PRs.

## SPEC-00.1 Environment

- Python **3.12**, managed with **uv** (`uv sync`, `uv run`). Lockfile `uv.lock` is committed.
- `pyproject.toml` defines the package `esci-search` (import name `esci_search`) with `src/` layout.
- Dependency groups:

| Group | Packages (lower-bounded, resolved in `uv.lock`) |
|---|---|
| core | `pandas>=2.2`, `pyarrow>=16`, `numpy>=1.26`, `pydantic>=2.7`, `pydantic-settings>=2.3`, `pyyaml>=6` |
| retrieval | `bm25s>=0.2`, `PyStemmer>=2.2`, `sentence-transformers>=3.0`, `torch>=2.3`, `psycopg[binary,pool]>=3.2`, `pgvector>=0.3` |
| service | `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `boto3>=1.35`, `aws-embedded-metrics>=3.2` |
| infra | `aws-cdk-lib>=2.150`, `constructs>=10`, `cdk-nag>=2.28` |
| dev | `pytest>=8`, `pytest-asyncio>=0.23`, `hypothesis>=6`, `scikit-learn>=1.5` (metric oracle only), `ruff>=0.6`, `mypy>=1.11`, `moto>=5` |

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
- Function: `load_experiment(path: Path) -> ExperimentConfig`. Raises `ConfigError` on unknown
  keys, a name/file-stem mismatch, or an unknown pipeline.

## SPEC-00.3 Shared types (`src/esci_search/types.py`)

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
enforces this. Direct construction with unsorted items raises `ValueError`.

## SPEC-00.4 Errors (`src/esci_search/errors.py`)

`EsciError` (base) → `ConfigError`, `DataError`, `IndexError_` (name avoids the builtin),
`RetrievalError`, `DependencyTimeout`, `LeakageError`. Library code raises these, never bare
`Exception`. CLIs map them to exit code 2 with a one-line message.

## SPEC-00.5 Logging (`src/esci_search/logging.py`)

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
- `tests/fixtures/mini_esci/`: 200 `ci_dev` queries with their judged products (Apache-2.0 NOTICE
  included) plus a synthetic 20-product set for pure unit tests.
- Property tests use `hypothesis` for metrics and fusion.

### Tests for this spec
- `test_config.py`: unknown key → `ConfigError`; name ≠ stem → `ConfigError`; base merge precedence.
- `test_types.py`: `from_scores` sorts by score desc then id asc; duplicate ids → `ValueError`.
