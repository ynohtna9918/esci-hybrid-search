# SPEC-00c: Config, paths, logging, local environment (detailed, normative)

This file replaces the short versions of **SPEC-00.2** (configuration), **SPEC-00.5** (logging),
**SPEC-00.6** (paths) and the fixture part of **SPEC-00.7** in `00-conventions.md`, and gives the exact
W1 content of the files in **SPEC-08.5/08.6** (local environment, Makefile). It is written for someone who
has never seen this codebase. If anything here is ambiguous, the code is wrong until this file is fixed:
ask, then update this file in the same PR.

---

## 0. Files covered, and the order to write them

| # | File | Who writes it | Section |
|---|---|---|---|
| 1 | `configs/base.yaml` | copy from §7.1 | §3.4 |
| 2 | `.env.example` | copy from §7.2 | §2.3 |
| 3 | `src/esci_search/config.py` | **you** | §2, §3 |
| 4 | `tests/unit/test_config.py` | **you** (write before step 3's code is finished) | §8.1 |
| 5 | `tests/conftest.py` | copy from §6 (only after `config.py` exists: it imports it) | §6 |
| 6 | `src/esci_search/paths.py` + `tests/unit/test_paths.py` | **you** | §4, §8.2 |
| 7 | `src/esci_search/logs.py` + `tests/unit/test_logs.py` | **you** | §5, §8.3 |
| 8 | `docker-compose.yml`, `Makefile` | copy from §7.3, §7.4 | §7 |

Work in small loops: write a few tests → run them, see them fail → write code → run
`uv run pytest <file> -q` and `uv run mypy` → repeat. Do not write a whole file before running anything.

Dependencies already in `pyproject.toml`: `pydantic`, `pydantic-settings`, `pyyaml`, `types-PyYAML`.
Nothing new to install.

---

## 1. Concepts to read first

### 1.1 Pydantic in 60 seconds (and how it differs from a dataclass)

A dataclass **does not check types** at runtime. A pydantic model **checks and converts** them:

```python
from dataclasses import dataclass
from pydantic import BaseModel

@dataclass
class D:
    seed: int

class P(BaseModel):
    seed: int

D("7").seed          # '7'  (a str! no error)
P(seed="7").seed     # 7    (converted to int)
P(seed="abc")        # pydantic.ValidationError: Input should be a valid integer
```

That is why configs (which come from YAML files and environment variables, i.e. untrusted text) use
pydantic, while `core_types.py` (built by our own code) uses dataclasses.

Pydantic models are created with **keyword arguments**: `P(seed=7)`, not `P(7)`.

### 1.2 Reading list

| Feature | Official docs | Used in |
|---|---|---|
| `BaseModel`, `Field(default=..., ge=..., pattern=...)` | <https://docs.pydantic.dev/latest/concepts/models/>, <https://docs.pydantic.dev/latest/concepts/fields/> | §2, §3 |
| `ConfigDict(extra="forbid", frozen=True)` | <https://docs.pydantic.dev/latest/api/config/> | §2, §3 |
| `@field_validator`, `@model_validator(mode="after")` | <https://docs.pydantic.dev/latest/concepts/validators/> | §2, §3 |
| `SecretStr` | <https://docs.pydantic.dev/latest/api/types/#pydantic.types.SecretStr> | §2 |
| `BaseSettings`, `SettingsConfigDict(env_prefix=..., env_file=...)` | <https://docs.pydantic.dev/latest/concepts/pydantic_settings/> | §2 |
| `functools.lru_cache` | <https://docs.python.org/3/library/functools.html#functools.lru_cache> | §2.5 |
| `yaml.safe_load` | <https://pyyaml.org/wiki/PyYAMLDocumentation> | §3 |
| `copy.deepcopy` | <https://docs.python.org/3/library/copy.html> | §3.3 |
| `pathlib.Path` | <https://docs.python.org/3/library/pathlib.html> | §4 |
| `logging` (Logger, Handler, Formatter, LogRecord) | <https://docs.python.org/3/howto/logging.html> | §5 |
| `contextvars.ContextVar` | <https://docs.python.org/3/library/contextvars.html> | §5 |
| `json.dumps(default=..., ensure_ascii=...)` | <https://docs.python.org/3/library/json.html> | §5 |
| `urllib.parse.quote` | <https://docs.python.org/3/library/urllib.parse.html#urllib.parse.quote> | §2.4 |
| pytest fixtures, `monkeypatch`, `tmp_path`, `capsys` | <https://docs.pytest.org/en/stable/how-to/fixtures.html> | §6, §8 |

---

## 2. `config.py` part A: `Settings` (runtime settings)

### 2.1 Why

Some values differ between your laptop, CI, and AWS: where the data lives, how to reach Postgres, which
DynamoDB endpoint to use. These must **not** be hard-coded and must **not** be in experiment YAML files
(an experiment must give the same result on every machine). They come from **environment variables**.

### 2.2 Fields

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESCI_", env_file=".env", env_file_encoding="utf-8",
        extra="forbid", frozen=True,
    )
```

| Field | Type | Default | Env var | Meaning |
|---|---|---|---|---|
| `data_dir` | `Path` | `Path("data")` | `ESCI_DATA_DIR` | root for downloaded and processed data |
| `results_dir` | `Path` | `Path("results")` | `ESCI_RESULTS_DIR` | root for run outputs |
| `pg_dsn` | `SecretStr` | `SecretStr("postgresql://esci:esci@localhost:5432/esci")` | `ESCI_PG_DSN` | local Postgres connection string |
| `pg_secret_json` | `SecretStr \| None` | `None` | `ESCI_PG_SECRET_JSON` | cloud only: the RDS secret as JSON; overrides `pg_dsn` (§2.4) |
| `pg_pool_min` | `int`, ≥ 1 | `1` | `ESCI_PG_POOL_MIN` | connection pool lower bound |
| `pg_pool_max` | `int`, ≥ 1 | `10` | `ESCI_PG_POOL_MAX` | connection pool upper bound |
| `ddb_table` | `str` | `"esci-search-cache"` | `ESCI_DDB_TABLE` | DynamoDB cache table |
| `ddb_endpoint_url` | `str \| None` | `None` | `ESCI_DDB_ENDPOINT_URL` | `http://localhost:8001` for DynamoDB Local; `None` = real AWS |
| `aws_region` | `str` | `"us-west-2"` | `ESCI_AWS_REGION` | |
| `cache_enabled` | `bool` | `True` | `ESCI_CACHE_ENABLED` | |
| `seed` | `int`, ≥ 0 | `42` | `ESCI_SEED` | default seed for code that has no experiment config |
| `log_json` | `bool` | `False` | `ESCI_LOG_JSON` | JSON logs (the service sets `true`) |

Constraints like "≥ 1" are written with `Field(default=1, ge=1)`.

Behaviors (all verified with pydantic-settings 2.x):

| Situation | Result |
|---|---|
| `ESCI_SEED=7` in the environment | `Settings().seed == 7` (converted from text) |
| `ESCI_CACHE_ENABLED=false` | `False` (`true/false/1/0/yes/no` all work) |
| `ESCI_SEED=abc` | `ValidationError` |
| an **unknown** `ESCI_FOO=1` in the environment | ignored |
| an **unknown key in the `.env` file** (e.g. typo `ESCI_PG_DNS`) | `ValidationError` (because of `extra="forbid"`) |
| a **non-`ESCI_` key in the `.env` file** (e.g. `AWS_PROFILE=x`) | also `ValidationError`, so **`.env` may contain only `ESCI_*` lines** |
| `settings.seed = 1` | `ValidationError` (frozen) |
| `repr(settings)` / `print(settings)` | secrets show as `SecretStr('**********')` |

**Precedence** (highest wins): keyword arguments `Settings(seed=3)` > environment variables > `.env` file > defaults.

**Cross-field rule:** add a `@model_validator(mode="after")` method that raises
`ValueError(f"pg_pool_min ({min}) > pg_pool_max ({max})")` when `pg_pool_min > pg_pool_max`, and otherwise
returns `self`.

Why `SecretStr`: a password must never appear in a log line, an error message, or a traceback. With
`SecretStr` the real value is only available through `.get_secret_value()`, so leaking it takes a deliberate call.

### 2.3 The `.env` file

- `.env` is git-ignored. `.env.example` (committed, §7.2) shows every key with a safe local value.
- Developers copy it: `cp .env.example .env`.
- A test (C5) loads `.env.example` with `extra="forbid"`, so the example can never drift out of sync with the fields.

### 2.4 `effective_pg_dsn()`: the one place that decides how to reach Postgres

```python
def effective_pg_dsn(self) -> str:
```

1. If `pg_secret_json is None` → return `self.pg_dsn.get_secret_value()`.
2. Otherwise parse `pg_secret_json.get_secret_value()` with `json.loads`:
   - invalid JSON → `ConfigError("ESCI_PG_SECRET_JSON is not valid JSON")` (use `raise ... from e`);
   - not a JSON object (dict) → `ConfigError("ESCI_PG_SECRET_JSON must be a JSON object")`;
   - missing any of `host`, `port`, `username`, `password` → `ConfigError` listing the **missing key names**.
     The message must **never** contain the password.
3. `dbname` is optional; default `"esci"`. (Check the real RDS secret in W4 and update this line if needed.)
4. Return `f"postgresql://{user}:{pw}@{host}:{port}/{dbname}"` where `user` and `pw` are passed through
   `urllib.parse.quote(value, safe="")`.

Why `quote`: a password like `p@ss/w:rd` contains `@`, `/` and `:`, which have special meanings in a URL.
Without encoding, `@` would end the password early and the host would be wrong.

| `pg_secret_json` | Result |
|---|---|
| `None` | `"postgresql://esci:esci@localhost:5432/esci"` |
| `{"host":"h","port":5432,"username":"u","password":"p@ss/w:rd"}` | `"postgresql://u:p%40ss%2Fw%3Ard@h:5432/esci"` |
| `{"host":"h","port":1,"password":"topsecret"}` | `ConfigError` mentioning `username`, not `topsecret` |
| `"{nope"` | `ConfigError` |

### 2.5 `get_settings()`

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
```

- Builds `Settings()` once and returns **the same object** on every later call (`lru_cache`).
  Reading the environment and `.env` once per process is enough, and every module sees identical settings.
- Wraps `ValidationError` into `ConfigError(f"invalid settings: {e}")` (with `from e`), so CLIs can print one clean line.
- Tests call `get_settings.cache_clear()` to start fresh (the conftest in §6 does this automatically).
- Library code calls `get_settings()`; it never constructs `Settings()` itself. Tests construct `Settings(...)` directly.

---

## 3. `config.py` part B: experiment configs

### 3.1 Why

An **experiment** is one named, reproducible run: which pipeline, which tracks, which split, which
parameters. It lives in a YAML file under `configs/experiments/`, so the exact setting of every reported
number is in git.

```yaml
# configs/experiments/p4_hybrid.yaml
name: p4_hybrid
pipeline: hybrid_rrf
tracks: [R, F]
split: dev
seed: 42
params:
  lexical: bm25
  n_lex: 100
  k_rrf: 60
```

### 3.2 `ExperimentConfig`

```python
KNOWN_PIPELINES: Final[frozenset[str]] = frozenset(
    {"random", "bm25", "pgfts", "dense", "hybrid_rrf", "hybrid_ce", "hybrid_bedrock"}
)
Track = Literal["R", "F"]
Split = Literal["dev", "ci_dev"]

class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
```

| Field | Type | Default | Rule |
|---|---|---|---|
| `name` | `str` | required | regex `^[a-z0-9_]+$` (`Field(pattern=...)`), must equal the file name without `.yaml` (§3.5) |
| `pipeline` | `str` | required | must be in `KNOWN_PIPELINES` (`@field_validator`) |
| `tracks` | `tuple[Track, ...]` | `("R", "F")` | at least one (`min_length=1`); no duplicates (`@field_validator`) |
| `split` | `Split` | `"dev"` | **`"test"` is not allowed here** |
| `seed` | `int`, ≥ 0 | `42` | |
| `params` | `dict[str, Any]` | `{}` (`Field(default_factory=dict)`) | not validated here; each pipeline validates its own params later (SPEC-03.7) |

Notes:

- **Why `name` has a regex:** the name becomes part of file names and run ids (`results/runs/<time>-<name>-...`).
  Spaces, capitals or `/` would break paths.
- **Why `split: test` is rejected:** the test split may only be read by `make final-eval` (EVAL_PROTOCOL §11).
  If a YAML file could say `split: test`, an ordinary `make eval` could leak it. The final evaluation passes
  the split to the runner as an argument instead (SPEC-04.6), so no config file ever needs `"test"`.
- `KNOWN_PIPELINES` is a temporary list. When the pipeline registry exists (SPEC-03.7, W1 PR 5), a test will
  assert `KNOWN_PIPELINES == set(PIPELINES)` so the two can never disagree.
- YAML gives `tracks` as a list; pydantic converts it to a tuple.
- `frozen=True` stops `cfg.seed = 1`, but `cfg.params["k"] = 2` still works (the dict itself is mutable,
  same lesson as a list inside a frozen dataclass). Rule: **never mutate `params`**; copy it if you need a variant.
- A field validator in pydantic v2 is written as:
  ```python
  @field_validator("pipeline")
  @classmethod
  def _known_pipeline(cls, v: str) -> str:
      if v not in KNOWN_PIPELINES:
          raise ValueError(f"unknown pipeline {v!r}; known: {sorted(KNOWN_PIPELINES)}")
      return v          # a validator must return the (possibly changed) value
  ```
  Inside validators, raise `ValueError`; pydantic turns it into a `ValidationError`.

### 3.3 `deep_merge(base, override) -> dict[str, Any]`

Merges two mappings. **`override` wins.** Used to put `base.yaml` under each experiment file.

Rules:
1. Returns a **new** dict. Neither input is modified, and the result shares **no nested objects** with the inputs
   (use `copy.deepcopy`). Otherwise appending to a list in the result could silently change `base`.
2. If a key's value is a mapping in **both** inputs → merge those two recursively.
3. Otherwise (including lists) → `override`'s value replaces `base`'s value. Lists are **not** concatenated.

| `base` | `override` | Result |
|---|---|---|
| `{"params": {"a": 1, "b": 2}}` | `{"params": {"b": 3}}` | `{"params": {"a": 1, "b": 3}}` |
| `{"tracks": ["R", "F"]}` | `{"tracks": ["R"]}` | `{"tracks": ["R"]}` |
| `{"p": {"a": 1}}` | `{"p": 5}` | `{"p": 5}` |
| `{"p": 5}` | `{"p": {"a": 1}}` | `{"p": {"a": 1}}` |
| `{"seed": 42}` | `{}` | `{"seed": 42}` |

### 3.4 `base.yaml` and `_read_yaml(path) -> dict[str, Any]`

`configs/base.yaml` holds shared defaults. Only these top-level keys are allowed in it:
`BASE_ALLOWED_KEYS = frozenset({"tracks", "split", "seed", "params"})`.
`name` and `pipeline` are per-experiment, so a base file containing them is a mistake.

`_read_yaml` (private helper) reads one YAML file:

| Case | Result |
|---|---|
| file does not exist | `ConfigError(f"config file not found: {path}")` |
| YAML syntax error | `ConfigError(f"invalid YAML in {path}: {e}")`, with `from e` |
| empty file | `{}` (`safe_load` returns `None` for an empty file) |
| top level is not a mapping (e.g. a list) | `ConfigError(f"top level of {path} must be a mapping, got list")` |
| otherwise | the dict |

**Always `yaml.safe_load`, never `yaml.load`.** `yaml.load` can construct arbitrary Python objects from tags in
the file, which turns a config file into code execution. `safe_load` only builds plain dicts, lists, strings and numbers.

### 3.5 `load_experiment(path, *, base_path=None) -> ExperimentConfig`

The `*` makes `base_path` keyword-only: `load_experiment(p, base_path=b)`.

Algorithm (in this order):
1. **Find the base file.**
   - `base_path is None` → use `path.parent.parent / "base.yaml"` (experiments are in `configs/experiments/`,
     base is in `configs/`). If that default file does not exist, use `{}`.
   - `base_path` given explicitly but missing → `ConfigError` (an explicit path that does not exist is a mistake).
2. If the base has keys outside `BASE_ALLOWED_KEYS` → `ConfigError(f"keys {bad} are not allowed in {base_file}")`.
3. `merged = deep_merge(base, _read_yaml(path))`.
4. `ExperimentConfig.model_validate(merged)`; on `ValidationError` raise
   `ConfigError(f"invalid experiment config {path}:\n{e}")` from it. Pydantic's message already names the bad
   field (e.g. `pipline: Extra inputs are not permitted`), so keep it.
5. If `cfg.name != path.stem` → `ConfigError(f"name {cfg.name!r} does not match file name {path.stem!r} ({path})")`.
6. Return `cfg`.

Precedence for experiments: experiment file > `base.yaml` > model defaults. `Settings.seed` is **not** used here.

---

## 4. `paths.py`: canonical directories

### 4.1 Why

Every module needs "where is the processed data?". If each one wrote `Path("data/processed")` itself, moving
the data would mean editing many files, and tests would write into your real `data/` folder.

### 4.2 Functions

```python
def raw_dir(settings: Settings | None = None) -> Path:        # <data_dir>/raw
def processed_dir(settings: Settings | None = None) -> Path:  # <data_dir>/processed
def index_dir(settings: Settings | None = None) -> Path:      # <data_dir>/index
def runs_dir(settings: Settings | None = None) -> Path:       # <results_dir>/runs
def ensure_dir(path: Path) -> Path:                           # mkdir -p; returns path
```

Rules:
- `settings is None` → use `get_settings()`. Tests pass their own `Settings` so they never touch real folders.
- Use `if settings is None`, **not** `settings or get_settings()`. Here `None` is the only "missing" value, so
  `is None` is exactly right. (Contrast with `Scored`, where `""` was also invalid, so `not` was right.)
  Write a tiny private helper `_s(settings)` so the `None` check exists once.
- The four `*_dir` functions are **pure**: they compute a path and **do not create anything**. Creating
  directories is a side effect, so it happens only when a caller explicitly calls `ensure_dir(...)`.
- `ensure_dir` = `path.mkdir(parents=True, exist_ok=True)`; calling it twice is fine; it returns `path` so you can
  write `out = ensure_dir(runs_dir() / run_id)`.
- Paths are returned as configured (a relative `data_dir` stays relative to the current directory).
  Commands are always run from the repo root.

---

## 5. `logs.py`: logging

### 5.1 Why

`print` is fine for a script you watch. A service running on AWS needs logs that a machine can search:
"all requests slower than 500 ms", "everything for request `01JD...`". So the service logs **one JSON object
per line**, and every line produced while handling a request carries that request's id.

The module is named `logs.py`, not `logging.py`, so it does not shadow the standard library `logging` (AI_USAGE #3).

### 5.2 Three logging words you need

| Word | What it is |
|---|---|
| **Logger** | the object you call: `log = get_logger(__name__)`; `log.info("rows=%d", n)`. Named after the module. |
| **Handler** | decides **where** a record goes (here: `stderr`). Attached to the root logger, so every module's logs pass through it. |
| **Formatter** | decides **what a record looks like** as text (JSON or plain). Each handler has one. |

Call style: `log.info("loaded %d rows from %s", n, path)`, not an f-string. The `%` formatting happens only if
the record is actually emitted, and `extra={"rows": n}` attaches structured fields.

### 5.3 Request ids with `contextvars`

```python
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

def bind_request_id(request_id: str) -> Token[str | None]:   # set it; return a token
def reset_request_id(token: Token[str | None]) -> None:       # undo exactly that set
def current_request_id() -> str | None:                       # read it
```

A `ContextVar` is like a global variable, except that each concurrent task (each web request in the async
service) sees **its own** value. A normal global would mix up ids between requests handled at the same time.
`set` returns a `Token`; `reset(token)` restores the value from before that `set`. (`Token` is imported from `contextvars`.)

### 5.4 `JsonFormatter(logging.Formatter)`

Override one method: `def format(self, record: logging.LogRecord) -> str`. It returns **one line** of JSON:

```json
{"ts": "2026-11-25T04:12:03.123Z", "level": "INFO", "logger": "esci_search.data.load", "msg": "loaded 601354 rows", "request_id": "01JD...", "rows": 601354}
```

| Key | Value | Notes |
|---|---|---|
| `ts` | `record.created` (a Unix timestamp) as UTC ISO-8601 with milliseconds, ending in `Z` | `datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")`, then replace `+00:00` with `Z` (`from datetime import UTC, datetime`) |
| `level` | `record.levelname` | |
| `logger` | `record.name` | |
| `msg` | `record.getMessage()` | this applies the `%` arguments: `"rows=%d", 5` → `"rows=5"` |
| `request_id` | `current_request_id()` | **only present when bound** |
| *extras* | every key passed via `extra={...}` | see below |
| `exc` | `self.formatException(record.exc_info)` | only when the record has `exc_info` (e.g. `log.exception(...)`) |

**Finding the extras.** `extra={"rows": 5}` simply becomes an attribute `record.rows`. To find them, compare
`record.__dict__` against the attributes **every** record has. Build that set once, at import time, from a dummy
record, so it is correct on every Python version:

```python
_STD_ATTRS: Final[frozenset[str]] = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}       # these two are added later, during formatting
```

Then: every `key, value` in `record.__dict__` with `key not in _STD_ATTRS` is an extra.
**Core keys win:** if an extra has the same name as a key already in the payload (e.g. `level`), skip the extra.

`json.dumps(payload, default=str, ensure_ascii=False)`:
- `default=str`: values JSON cannot encode (a `Path`, a `datetime`) are written with `str(value)` instead of crashing.
  A log call must never crash the program.
- `ensure_ascii=False`: Chinese query text stays readable (`"耳机"`, not `"耳机"`).

### 5.5 `configure_logging(*, json_format: bool, level: str = "INFO") -> None`

The parameter is `json_format`, not `json`: a parameter named `json` would shadow the `json` module inside the
function (the same shadowing problem as `types.py` / `logging.py`). Both parameters are keyword-only (`*`).

Steps:
1. `level.upper()` must be one of `DEBUG, INFO, WARNING, ERROR, CRITICAL`, else
   `ValueError(f"unknown log level {level!r}; ...")`. (`"debug"` is accepted.)
2. Get the root logger: `logging.getLogger()`.
3. Remove **only** handlers whose `.name == HANDLER_NAME` (`HANDLER_NAME: Final = "esci"`). Leave every other
   handler alone (pytest attaches its own handlers; removing them breaks test output).
4. Create `logging.StreamHandler(sys.stderr)`, set `handler.name = HANDLER_NAME`, and set the formatter:
   `JsonFormatter()` if `json_format`, else `logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")`.
5. Add it to the root logger and `root.setLevel(level.upper())`.

Consequences:
- **Idempotent:** calling it twice leaves exactly one `esci` handler (no duplicated lines).
- **stderr, not stdout:** stdout is reserved for a program's real output (a CLI that prints JSON results can be piped
  into another tool without log lines mixed in).
- Call it **once**, at program start (CLI `main`, service startup). Library modules only call `get_logger`.

`get_logger(name: str) -> logging.Logger` just returns `logging.getLogger(name)`. It exists so every module imports
logging the same way and we can change the behavior in one place later.

---

## 6. `tests/conftest.py` (copy this; read the comments)

```python
"""Shared pytest fixtures (SPEC-00c §6)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from esci_search.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Every test: no ESCI_* env vars, empty working dir, fresh settings cache."""
    for key in list(os.environ):
        if key.upper().startswith("ESCI_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", results_dir=tmp_path / "results")
```

| Piece | Why |
|---|---|
| `autouse=True` | runs around **every** test automatically |
| delete `ESCI_*` env vars | your shell's settings must not change test results |
| `monkeypatch.chdir(tmp_path)` | each test runs in a fresh empty folder, so your real `.env` is not read and nothing is written into the repo |
| `cache_clear()` before and after | one test's `get_settings()` result must not leak into the next |
| `monkeypatch` | every change it makes is undone automatically after the test |
| `REPO_ROOT` / `repo_root` | because of the `chdir`, tests that need real repo files (`.env.example`, `configs/base.yaml`) use absolute paths from here |
| `Settings(_env_file=None, ...)` | builds settings without reading any `.env` file |

Add this file **after** `config.py` exists: it imports `get_settings`, so until then every test would fail to import.

---

## 7. Provided files (copy exactly; understand every line)

### 7.1 `configs/base.yaml`

```yaml
# Shared defaults merged UNDER every experiment file (SPEC-00c §3.4).
# Allowed keys: tracks, split, seed, params. On conflict, the experiment file wins.
seed: 42
```

### 7.2 `.env.example`

```bash
# Copy to .env and edit. .env is git-ignored and is read by Settings (SPEC-00c §2.3).
# Only ESCI_* lines are allowed here: any other key makes Settings fail on purpose,
# so typos like ESCI_PG_DNS are caught instead of silently ignored.

ESCI_DATA_DIR=./data
ESCI_RESULTS_DIR=./results
ESCI_PG_DSN=postgresql://esci:esci@localhost:5432/esci
ESCI_PG_POOL_MIN=1
ESCI_PG_POOL_MAX=10
ESCI_DDB_TABLE=esci-search-cache
ESCI_DDB_ENDPOINT_URL=http://localhost:8001
ESCI_AWS_REGION=us-west-2
ESCI_CACHE_ENABLED=true
ESCI_SEED=42
ESCI_LOG_JSON=false
```

### 7.3 `docker-compose.yml`

```yaml
# Local services for development and integration tests (SPEC-08.5).
# Start: make up-local    Stop: make down-local    Wipe the database: docker compose down -v
name: esci-hybrid-search

services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: esci
      POSTGRES_PASSWORD: esci          # local only; never reuse in the cloud
      POSTGRES_DB: esci
    command: ["postgres", "-c", "shared_buffers=1GB", "-c", "maintenance_work_mem=2GB"]
    shm_size: 1g                       # parallel index builds use /dev/shm (Docker default: 64 MB)
    ports:
      - "127.0.0.1:5432:5432"          # bind to localhost only, not your whole network
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U esci -d esci"]
      interval: 2s
      timeout: 3s
      retries: 30

  dynamodb:
    image: amazon/dynamodb-local
    command: ["-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb"]
    ports:
      - "127.0.0.1:8001:8000"

volumes:
  pgdata:
```

| Line | Why |
|---|---|
| `pgvector/pgvector:pg17` | official Postgres 17 image with the `vector` extension already installed |
| `command: ... shared_buffers ... maintenance_work_mem` | more memory for caching and for building the HNSW index in W2 |
| `shm_size: 1g` | Postgres parallel workers share memory through `/dev/shm`; Docker's 64 MB default can make large index builds fail |
| `127.0.0.1:` in ports | the database (password `esci`) is reachable only from your machine, not from other devices on your Wi-Fi |
| `volumes: pgdata` | the database survives `docker compose down`; `down -v` deletes it |
| `healthcheck` | `docker compose up --wait` waits until `pg_isready` says Postgres accepts connections |
| DynamoDB has **no** healthcheck | `--wait` then waits only until the container is *running*. That is enough in W1: nothing uses DynamoDB until W4, where the cache CLI connects with retries. (This corrects an earlier review note that said both services need a healthcheck.) |
| `-inMemory -sharedDb` | data is lost on restart (fine for a cache); one shared database regardless of the credentials or region the client sends |

### 7.4 `Makefile`

```make
.DEFAULT_GOAL := help

# Unit tests only: no Docker, no dataset, no GPU (SPEC-00.7).
PYTEST_UNIT := uv run pytest -m "not integration and not data and not gpu"

STUBS := data index eval final-eval results ci-baseline serve \
         cloud-up cloud-down cloud-load-index loadtest cost-snapshot

.PHONY: help check test test-data up-local down-local $(STUBS)

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

check: ## lint + format check + types + unit tests (must pass before every commit)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	$(PYTEST_UNIT)

test: check ## check + integration tests (run make up-local first)
	uv run pytest -m integration || [ $$? -eq 5 ]

test-data: ## tests that need the real ESCI download
	uv run pytest -m data || [ $$? -eq 5 ]

up-local: ## start local Postgres+pgvector and DynamoDB Local
	docker compose up -d --wait

down-local: ## stop local services (the Postgres volume is kept)
	docker compose down

$(STUBS):
	@echo "make $@: not implemented yet (see docs/ROADMAP.md)" >&2; exit 1
```

| Gotcha | Explanation |
|---|---|
| **Recipe lines start with a TAB** | spaces give `*** missing separator`. In VS Code, the status bar shows "Spaces"/"Tab Size": click it and choose "Indent Using Tabs" for this file. Check with `cat -A Makefile` (tabs show as `^I`). |
| `|| [ $$? -eq 5 ]` | pytest exits with code **5** when no tests are selected (true for `-m integration` until W2). Make treats any non-zero exit as failure, so we turn exactly 5 into success. Any real failure (exit 1) still fails. |
| `$$` | inside a Makefile, `$` belongs to make; `$$` passes one literal `$` to the shell. |
| `.PHONY` | these names are commands, not files; without it, a file named `test` would make `make test` do nothing. |
| `test: check` | `make test` runs `check` first. |
| `## comment` | `make help` (also plain `make`) lists every target that has one. |
| stubs | `make data` prints a clear "not implemented yet" and exits 1, instead of a confusing "No rule to make target". |

---

## 8. Tests

Write each table as its own test file. One test checks one rule. Use the fixtures from §6.
Helper for the config tests: write YAML into `tmp_path / "configs" / "experiments" / "<name>.yaml"` with
`yaml.safe_dump(dict)` (and `tmp_path / "configs" / "base.yaml"` for the base).

### 8.1 `tests/unit/test_config.py`

**Settings**

| # | Test name | Checks |
|---|---|---|
| C1 | `test_settings_defaults` | `Settings(_env_file=None)`: seed 42, region `us-west-2`, `cache_enabled` True, `data_dir == Path("data")`, pool max 10 |
| C2 | `test_settings_from_env` | `monkeypatch.setenv("ESCI_SEED", "7")`, `("ESCI_CACHE_ENABLED", "false")` → 7 and `False` |
| C3 | `test_kwarg_beats_env` | env `ESCI_SEED=7`, `Settings(_env_file=None, seed=3).seed == 3` |
| C4 | `test_env_file_typo_rejected` | `.env` in `tmp_path` with `ESCI_PG_DNS=x` → `Settings(_env_file=that_path)` raises `ValidationError`; `get_settings()` raises `ConfigError` (cwd is `tmp_path`) |
| C5 | `test_env_example_is_valid` | `Settings(_env_file=repo_root / ".env.example")` raises nothing |
| C6 | `test_secret_not_in_repr` | `"esci:esci"` appears in neither `repr(s)` nor `str(s)` |
| C7 | `test_pool_min_gt_max_rejected` | `pg_pool_min=5, pg_pool_max=2` → `ValidationError` |
| C8 | `test_effective_dsn_default` | equals the default DSN string |
| C9 | `test_effective_dsn_from_secret_json` | the `p@ss/w:rd` row of the §2.4 table |
| C10 | `test_secret_json_missing_key` | `ConfigError`; message contains `username`, does not contain `topsecret` |
| C11 | `test_secret_json_invalid` | `"{nope"` → `ConfigError` |
| C12 | `test_get_settings_cached` | two calls return the same object (`is`); after `cache_clear()` a different one |
| C13 | `test_settings_frozen` | `s.seed = 1` raises `ValidationError` |

**deep_merge**

| # | Test name | Checks |
|---|---|---|
| M1 | `test_merge_nested` | row 1 of the §3.3 table |
| M2 | `test_merge_lists_replaced` | row 2 |
| M3 | `test_merge_no_mutation_no_sharing` | after merging, append to a nested list in the result; `base` and `override` are unchanged |
| M4 | `test_merge_type_change` | rows 3 and 4 |

**load_experiment**

| # | Test name | Checks |
|---|---|---|
| L1 | `test_load_valid` | returns an `ExperimentConfig`; `tracks == ("R", "F")` (a tuple); `split == "dev"` |
| L2 | `test_base_merged_under` | base `seed: 7, params {a:1, b:2}` + experiment `params {b:3}` → seed 7, params `{a:1, b:3}`; an experiment with `seed: 9` gets 9 |
| L3 | `test_default_base_missing_ok` | no `base.yaml` → loads fine |
| L4 | `test_explicit_base_missing_raises` | `base_path=tmp_path / "nope.yaml"` → `ConfigError` |
| L5 | `test_name_must_match_file` | file `a.yaml` with `name: b` → `ConfigError` matching `"does not match"` |
| L6 | `test_unknown_key_rejected` | key `pipline` → `ConfigError` whose message contains `pipline` |
| L7 | `test_unknown_pipeline_rejected` | `pipeline: bm52` → `ConfigError` matching `"unknown pipeline"` |
| L8 | `test_test_split_rejected` | `split: test` → `ConfigError` |
| L9 | `test_bad_tracks` (parametrize) | `[]`, `["R", "R"]`, `["X"]` → each `ConfigError` |
| L10 | `test_bad_yaml` (parametrize) + `test_missing_file` | `"name: [unclosed"` and a top-level list → `ConfigError`; a missing file → `ConfigError` matching `"not found"` |
| L11 | `test_base_disallowed_key` (parametrize) | base containing `name`, `pipeline`, or typo `sead` → `ConfigError` matching `"not allowed"` |
| L12 | `test_experiment_frozen` | `cfg.seed = 1` raises `ValidationError` |
| L13 | `test_repo_base_yaml_valid` | loading a temp experiment with `base_path=repo_root / "configs" / "base.yaml"` works |
| L14 | `test_name_pattern` (parametrize) | `ExperimentConfig(name=n, pipeline="bm25")` for `"P1"`, `"p-1"`, `"p 1"`, `""` → `ValidationError` |
| L15 | `test_negative_seed_rejected` | `seed: -1` → `ConfigError` |

### 8.2 `tests/unit/test_paths.py`

| # | Test name | Checks |
|---|---|---|
| P1 | `test_dirs_from_settings` | with the `settings` fixture: each of the four functions returns the expected path under `tmp_path` |
| P2 | `test_dirs_have_no_side_effects` | after calling all four, `list(tmp_path.iterdir()) == []` |
| P3 | `test_dirs_default_to_get_settings` | env `ESCI_DATA_DIR=<tmp>/d` → `raw_dir() == <tmp>/d/raw` |
| P4 | `test_ensure_dir` | creates nested dirs, returns the same path, a second call does not fail |

### 8.3 `tests/unit/test_logs.py`

Add a module-level `autouse` fixture that, after each test, removes any root handler named `logs.HANDLER_NAME` and
restores the root logger's level. Test the formatter **directly** by building a record:
`logging.getLogger("t").makeRecord("t", logging.INFO, "f.py", 1, "hello %s", ("x",), None, extra={...})` and
passing it to `JsonFormatter().format(record)`.

| # | Test name | Checks |
|---|---|---|
| G1 | `test_get_logger` | returns a `logging.Logger` with the given name |
| G2 | `test_json_core_fields` | output has no `\n`; parses with `json.loads`; `level`, `logger`, `msg` correct; `ts` ends with `Z` and parses with `datetime.fromisoformat(ts.replace("Z", "+00:00"))` |
| G3 | `test_json_args_interpolated` | `"rows=%d", (5,)` → `msg == "rows=5"` |
| G4 | `test_json_extras` | `extra={"rows": 5, "path": Path("/x")}` → `rows == 5`, `path == "/x"` |
| G5 | `test_extra_cannot_overwrite_core` | `extra={"level": "FAKE"}` → `level == "INFO"` |
| G6 | `test_request_id_bound_and_reset` | absent before; present after `bind_request_id("r-1")`; absent again after `reset_request_id(token)` |
| G7 | `test_exception_included` | a record built with `exc_info=sys.exc_info()` inside `except ZeroDivisionError` → `"ZeroDivisionError" in d["exc"]` |
| G8 | `test_unicode_not_escaped` | `"耳机"` appears literally in the output string |
| G9 | `test_configure_idempotent` | call `configure_logging` twice → exactly one root handler named `esci`; the other root handlers are the same objects as before |
| G10 | `test_configure_bad_level` | `level="LOUD"` → `ValueError` |
| G11 | `test_configure_json_end_to_end` | with `capsys`: `configure_logging(json_format=True, level="debug")`, log one line with an extra, the last line of `capsys.readouterr().err` parses as JSON with the right `msg` and extra |
| G12 | `test_configure_text_format` | `json_format=False`, `warning("careful")` on logger `txt` → stderr contains `WARNING` and `txt: careful` |
| G13 | `test_level_filters` | `level="WARNING"`, an `info(...)` call → not in stderr |

`capsys` note: call `configure_logging` **inside** the test. The handler grabs `sys.stderr` when it is created,
and pytest swaps `sys.stderr` for its capture object only while the test runs.

---

## 9. Changes to other files in the same PR

| File | Change |
|---|---|
| `docs/specs/00-conventions.md` | SPEC-00.2, 00.5, 00.6: replace the body with "See `00c-config-paths-logging-local-env.md` (normative)." SPEC-00.7: point the fixture part here. |
| `docs/specs/00b-core-types-and-errors.md` | §SPEC-00.4 "Define `__all__` … in the order above" → "**sorted alphabetically** (ruff rule RUF022)". E5 → `list(errors.__all__) == sorted(EXPECTED)`. |
| `docs/specs/04-evaluation.md` | SPEC-04.4/04.6: the runner takes `split` as an argument (default `cfg.split`); `final` passes `"test"`. Experiment YAML never contains `test`. |
| `docs/FILE_MANIFEST.md` | add `docs/specs/00c-…md`, `tests/unit/test_paths.py`, `tests/unit/test_logs.py`; `Makefile` row: W1 (stubs for later targets) |
| `docs/AI_USAGE.md` | entry #4: SPEC-00b required `__all__` in hierarchy order, which contradicts ruff RUF022; caught by running the spec's own tests under the project's ruff config before the human hit it; fixed by sorting and updating E5. |

---

## 10. Definition of done

Run by you, in this order:

```bash
uv run pytest tests/unit -q          # all pass (core types + errors + config + paths + logs)
make check                           # ruff, format, mypy strict, unit tests
make test                            # same + "no integration tests yet" (exit 5 → success)
make up-local && docker compose ps   # postgres "healthy", dynamodb "running"
make data                            # prints "not implemented yet", exit 1 (expected)
make down-local
```

And these facts must be true when you read your own code:

- [ ] `config.py` imports only from the standard library, pydantic, pydantic-settings, yaml and `esci_search.errors`.
- [ ] `paths.py` and `logs.py` never create files or directories at import time.
- [ ] No function prints a password, even in an error message.
- [ ] `yaml.load` appears nowhere (only `yaml.safe_load`).
- [ ] Every `raise ConfigError(...)` message names the file or key that is wrong.
- [ ] `git status` shows no `.env` (it is git-ignored) and no `data/` or `results/runs/` files created by tests.
