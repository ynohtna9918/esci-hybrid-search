# SPEC-00b: Core types and errors (detailed, normative)

This file replaces the short versions of **SPEC-00.3** (shared types) and **SPEC-00.4** (errors) in
`00-conventions.md`. It is written for someone who has never seen this codebase. If anything here is
ambiguous, the code is wrong until this file is fixed. Ask, then update this file in the same PR.

Files covered:

| File | What it is |
|---|---|
| `src/esci_search/__init__.py` | marks the folder as a Python package; holds the version |
| `src/esci_search/errors.py` | the project's exception classes |
| `src/esci_search/core_types.py` | the small data objects every other module passes around |
| `tests/unit/test_errors.py` | tests for `errors.py` |
| `tests/unit/test_types.py` | tests for `core_types.py` |

---

## SPEC-00.2a `__init__.py`

Exactly one statement:

```python
__version__ = "0.1.0"
```

**Do not** import submodules here (no `from esci_search.core_types import *`). Importing the package
should stay cheap and must never create import cycles. Every caller imports what it needs from the
submodule directly: `from esci_search.core_types import RankedList`.

---

## SPEC-00.4 `errors.py`: exception classes

### Why this file exists

Later modules fail in predictable ways: a config file has a typo, the downloaded data is corrupt, someone
tries to read the test split. We want **one family** of exceptions so that:

1. a command-line tool can catch `EsciError` once and print a clean one-line message instead of a long
   traceback (SPEC-00.4: exit code 2);
2. a reader of the code can tell *what kind* of failure happened from the class name alone;
3. tests can assert the exact failure type (`pytest.raises(ConfigError)`), which is more precise than
   `pytest.raises(Exception)`.

### What goes in it

```
Exception                      (Python built-in)
└── EsciError                  base class for every error this project raises on purpose
    ├── ConfigError            a config file or setting is invalid
    ├── DataError              input data is missing, corrupt, or fails validation
    ├── IndexBuildError        building or loading an index failed
    ├── RetrievalError         a retriever or reranker cannot produce a result
    ├── DependencyTimeout      an external dependency (Postgres, DynamoDB, Bedrock) did not answer in time
    └── LeakageError           code tried to touch the test split outside the final evaluation
```

Rules:

- Each class is a plain subclass with a **one-line docstring** saying when it is raised. No `__init__`,
  no extra fields. Python's `Exception` already stores the message.
- Define `__all__` at the top listing all seven names, in the order above.
- The name is `IndexBuildError`, **not** `IndexError_`. (Python already has a built-in `IndexError` for list
  indexing; a near-identical name would be confusing.)
- `DependencyTimeout` subclasses `EsciError` only. Do not also inherit from the built-in `TimeoutError`;
  callers catch it by the project name.

### Message convention (for everyone who raises these later)

A message states **what failed**, **the offending value**, and **where**, in one sentence:

```python
raise ConfigError(f"unknown key 'k_rff' in {path}")             # good
raise ConfigError("bad config")                                  # bad: which key? which file?
```

### Example of how it will be used later (not part of this PR)

```python
try:
    run()
except EsciError as e:          # catches every subclass
    print(f"error: {e}", file=sys.stderr)
    raise SystemExit(2)
```

### Tests: `tests/unit/test_errors.py`

| # | Test name | Checks |
|---|---|---|
| E1 | `test_base_is_exception` | `issubclass(EsciError, Exception)` |
| E2 | `test_all_subclasses_of_base` | each of the six subclasses satisfies `issubclass(X, EsciError)` (loop over them, or use `@pytest.mark.parametrize`) |
| E3 | `test_catch_as_base` | `raise DataError("x")` inside `pytest.raises(EsciError)` is caught |
| E4 | `test_message_preserved` | `str(ConfigError("unknown key 'a'")) == "unknown key 'a'"` |
| E5 | `test_all_exports` | `errors.__all__` equals the seven names in the order above |
| E6 | `test_docstrings` | every class in `__all__` has a non-empty `__doc__` |

---

## SPEC-00.3 `core_types.py`: shared data objects

### Why this file exists

Data loading, retrieval, evaluation, and the web service all talk about the same things: a query, a product,
a product with a score, and a ranked list of scored products. If each module invented its own representation
(a dict here, a tuple there), every hand-off would be a chance for bugs. This file defines them **once**.

Every object here is a **value object**:
- **immutable**: you cannot change it after creating it (`frozen=True`). A ranked list that the evaluator
  scored cannot be quietly modified by someone else afterwards.
- **light**: `slots=True` uses less memory, and assigning a misspelled attribute raises an error instead of
  silently creating a new one.
- **validated when it is created**: an invalid object cannot exist, so code that receives one never has to
  re-check it.

### Python features you need (read these first)

| Feature | Official docs | Used for |
|---|---|---|
| `@dataclass(frozen=True, slots=True)` | <https://docs.python.org/3/library/dataclasses.html> | every class here |
| `__post_init__` | same page, "Post-init processing" | validation |
| `object.__setattr__(self, name, value)` | same page, "Frozen instances" | normalizing a field inside a frozen dataclass |
| `typing.Literal`, `typing.Final` | <https://docs.python.org/3/library/typing.html> | `Label`, `GAIN` |
| `types.MappingProxyType` | <https://docs.python.org/3/library/types.html> | read-only `GAIN` |
| `@classmethod` | <https://docs.python.org/3/library/functions.html#classmethod> | `RankedList.from_scores` |
| `math.isnan` | <https://docs.python.org/3/library/math.html> | rejecting NaN |

Put `from __future__ import annotations` as the first line, so type hints can refer to classes defined
later in the same file.

---

### SPEC-00.3.1 `Label` and `GAIN`

```python
Label = Literal["E", "S", "C", "I"]
GAIN: Final[Mapping[Label, float]] = MappingProxyType({"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0})
```

- `Label` is a **type alias**. It only helps `mypy` catch typos like `"X"`; it does nothing at runtime.
- `GAIN` maps an ESCI label to its relevance gain (EVAL_PROTOCOL §3, ADR-0006):

| Label | Meaning (ESCI) | Gain |
|---|---|---|
| `E` | Exact: matches every part of the query | 1.0 |
| `S` | Substitute: not exact, but could replace the product | 0.1 |
| `C` | Complement: not what was asked, but used with it | 0.01 |
| `I` | Irrelevant | 0.0 |

- `GAIN` **must be read-only.** `Final` only stops you from writing `GAIN = {...}` again; it does **not**
  stop `GAIN["E"] = 2.0`. Wrapping the dict in `MappingProxyType` makes item assignment raise `TypeError`.
  Why it matters: if any module could change a gain value, every metric computed afterwards would be wrong,
  and nothing would warn us.

---

### SPEC-00.3.2 `Query`

```python
@dataclass(frozen=True, slots=True)
class Query:
    query_id: int    # ESCI query_id, e.g. 12345
    text: str        # the query string as typed by the shopper, e.g. "iphone 13 case clear"
```

- **No validation here.** The data layer (SPEC-01.2) validates queries when it loads them. Keep `Query` a plain container.

### SPEC-00.3.3 `Product`

```python
@dataclass(frozen=True, slots=True)
class Product:
    product_id: str        # ESCI product_id (an ASIN), e.g. "B07XKZJ8TM"
    title: str             # from product_title; "" if missing
    brand: str | None      # from product_brand; None if missing in the source
    color: str | None      # from product_color; None if missing
    bullets: str | None    # from product_bullet_point; None if missing
    doc_text: str          # the cleaned text used for search (SPEC-01.4); always a str, may be ""
```

- `None` means **the source had no value**. `""` is never used for `brand/color/bullets`.
  This distinction lets the data card count missing brands correctly.
- **No validation here** either (SPEC-01.2 does it).

---

### SPEC-00.3.4 `Scored`

One product with a score from some retriever or reranker.

```python
@dataclass(frozen=True, slots=True)
class Scored:
    product_id: str
    score: float
```

`__post_init__` must do exactly these three things, in this order:

1. If `product_id` is an empty string → raise `ValueError(f"empty product_id")`.
2. Convert `score` to a **built-in Python `float`**: `object.__setattr__(self, "score", float(self.score))`.
   - *Why:* retrievers compute scores with numpy, so they arrive as `numpy.float32` or `numpy.float64`.
     Those sort fine, but `json.dumps` fails on `numpy.float32`, and the service must return JSON.
     Converting once here fixes it everywhere.
   - *Why `object.__setattr__`:* a frozen dataclass blocks `self.score = ...`, even inside `__post_init__`.
     `object.__setattr__` is the documented way around that, and it is only allowed inside `__post_init__`.
3. If the converted score is NaN (`math.isnan`) → raise `ValueError(f"NaN score for product {product_id}")`.
   - *Why:* NaN compares as "not less, not greater, not equal" to everything, so sorting a list that contains
     NaN produces an order that is silently wrong. A NaN score is always an upstream bug.
   - `float("inf")` and `float("-inf")` are **allowed**. They sort correctly and are useful as sentinels.

| Input | Result |
|---|---|
| `Scored("B01", 0.5)` | ok, `score == 0.5` |
| `Scored("B01", numpy.float32(0.5))` | ok, and `type(s.score) is float` |
| `Scored("B01", 3)` (an int) | ok, `score == 3.0` and is a `float` |
| `Scored("B01", float("-inf"))` | ok |
| `Scored("", 0.5)` | `ValueError` |
| `Scored("B01", float("nan"))` | `ValueError` |

---

### SPEC-00.3.5 `RankedList`

The output of a retriever, reranker, or pipeline for **one** query: products in ranked order, best first.

```python
@dataclass(frozen=True, slots=True)
class RankedList:
    query_id: int
    items: tuple[Scored, ...]
```

#### The invariant (the most important rule in this file)

A `RankedList` is valid only if all of these hold:

1. **Unique ids:** no two items have the same `product_id`.
2. **Sorted:** items are ordered by **score from high to low**; when two scores are equal, by **`product_id`
   in alphabetical (ascending) order**.
3. `items` is a **tuple**, not a list. (A list inside a frozen dataclass can still be changed with `.append`.)

An **empty** `RankedList` (`items == ()`) is valid. Example: a full-text search where no product matches.

Example with ties:

| Input scores | Valid order |
|---|---|
| `B:0.9, A:0.5, C:0.5, D:0.1` | `B (0.9), A (0.5), C (0.5), D (0.1)`: A before C because `"A" < "C"` |

Why fix the tie order? Without it, two runs of the same experiment could rank tied products differently, and
nDCG would change between runs for no real reason. A fixed rule makes every ranking a **deterministic** function
of the scores.

#### The sort key

Write one private helper and use it **everywhere** ordering matters:

```python
def _rank_key(s: Scored) -> tuple[float, str]:
    return (-s.score, s.product_id)
```

Python compares tuples element by element. Negating the score turns "high to low" into "low to high", so a
plain ascending sort on `(-score, product_id)` gives score descending, then id ascending.

> ⚠️ Classic mistake: `sorted(items, key=lambda s: (s.score, s.product_id), reverse=True)`.
> `reverse=True` flips **both** parts, so tied ids come out **Z to A**. The tie-break test (T6 below) catches this.

#### `__post_init__` (validation)

1. Uniqueness: if the number of distinct `product_id`s is smaller than `len(items)`, raise
   `ValueError(f"duplicate product_id in RankedList for query {query_id}")`.
2. Order: walk adjacent pairs `(items[i], items[i+1])`. If `_rank_key(items[i]) >= _rank_key(items[i+1])`
   for any `i`, raise `ValueError(f"items not in rank order at position {i} for query {query_id}")`.
   (`>=`, because ids are unique, so equal keys can only mean a duplicate.)
   - Do **not** sort inside `__post_init__`. Its job is to **check**, not to fix. Silently fixing would hide bugs.
3. Type: if `items` is not a `tuple`, raise `TypeError("items must be a tuple")`.

NaN does not need a check here: `Scored` already makes NaN impossible.

#### Constructors and methods

```python
@classmethod
def from_scores(cls, query_id: int, scores: Iterable[Scored]) -> RankedList:
    """Sort scores into rank order and build a RankedList. Duplicates raise ValueError."""

def __len__(self) -> int:                     # number of items
def product_ids(self) -> tuple[str, ...]:     # ids in rank order
def top(self, k: int) -> RankedList:          # first k items, same query_id
```

| Method | Behavior | Edge cases |
|---|---|---|
| `from_scores` | sort with `_rank_key`, convert to a tuple, return `cls(query_id, ...)` so `__post_init__` validates | accepts any iterable, including a generator; empty input → empty list; duplicates → `ValueError` (**never** de-duplicate silently: duplicates mean an upstream bug) |
| `__len__` | `len(self.items)` | 0 for empty |
| `product_ids` | `tuple(s.product_id for s in self.items)` | `()` for empty |
| `top(k)` | `RankedList(self.query_id, self.items[:k])` | `k > len` → all items; `k == 0` → empty; `k < 0` → `ValueError` (Python's `[:-1]` would silently drop the last item) |

**Two ways to build one, and when to use which:**
- Code that computed scores in arbitrary order (almost every retriever) calls `RankedList.from_scores(...)`.
- `RankedList(query_id, items)` directly is for code that already has items in rank order (for example,
  `top(k)`). If the order is wrong, it raises.

#### Cost

`__post_init__` is O(n) (one pass). `from_scores` is O(n log n) (the sort). Lists in this project hold at most
a few hundred items, so this is negligible. Correctness matters more than speed here.

---

### Tests: `tests/unit/test_types.py`

Write these **before** the implementation. Run them once, see them fail, then implement.
Each test checks one thing. Names matter: a failing test name should tell you what broke.

| # | Test name | Arrange → Act → Assert |
|---|---|---|
| T1 | `test_gain_values` | `GAIN == {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}` (comparing a MappingProxyType to a dict works) |
| T2 | `test_gain_is_read_only` | `GAIN["E"] = 2.0` inside `pytest.raises(TypeError)` |
| T3 | `test_scored_converts_numpy_to_float` | `Scored("a", np.float32(0.5))` → `type(s.score) is float` and `s.score == 0.5` |
| T4 | `test_scored_rejects_nan_and_empty_id` | `Scored("a", float("nan"))` and `Scored("", 1.0)` each raise `ValueError` |
| T5 | `test_from_scores_sorts_by_score_desc` | scores a:0.1, b:0.9, c:0.5 → ids `("b", "c", "a")` |
| T6 | `test_ties_broken_by_product_id_asc` | B:0.9, C:0.5, A:0.5, D:0.1 → `("B", "A", "C", "D")` |
| T7 | `test_from_scores_accepts_generator` | pass `(Scored(i, s) for i, s in pairs)` → works |
| T8 | `test_empty_is_valid` | `RankedList.from_scores(1, [])` → `len(rl) == 0` |
| T9 | `test_duplicate_ids_raise` | two items with id `"a"` → `ValueError` |
| T10 | `test_unsorted_direct_construction_raises` | `RankedList(1, (Scored("a", 0.1), Scored("b", 0.9)))` → `ValueError` |
| T11 | `test_list_items_raise` | `RankedList(1, [Scored("a", 1.0)])` (a list) → `TypeError` |
| T12 | `test_frozen` | assigning `rl.query_id = 2` raises `dataclasses.FrozenInstanceError` |
| T13 | `test_top_k` | on 4 items: `top(2)` has 2 items and the same `query_id`; `top(10)` has 4; `top(0)` has 0; `top(-1)` → `ValueError` |
| T14 | `test_product_ids_in_order` | `product_ids()` equals the ids in rank order |
| T15 *(bonus)* | `test_from_scores_property` | with `hypothesis`: for any list of unique ids and finite floats, `from_scores` returns every input id exactly once and passes the invariant |

> `mypy` note: T10, T11, and T12 deliberately break types. Put `# type: ignore[...]` on those lines with the
> specific error code `mypy` reports. Never use a bare `# type: ignore`.

---

## Definition of done (for this PR step)

All of these must pass, run by you, in this order:

```bash
uv run pytest tests/unit/test_errors.py tests/unit/test_types.py -q    # all pass
uv run mypy                                                             # Success: no issues found
uv run ruff check . && uv run ruff format --check .                     # no output / "already formatted"
```

And these facts must be true when you read your own code:

- [ ] `core_types.py` has no imports from other `esci_search` modules (it is the bottom layer).
- [ ] The only place ordering is defined is `_rank_key`.
- [ ] Every `raise` message names the offending value or query.
- [ ] `docs/FILE_MANIFEST.md` lists `tests/unit/test_errors.py`, and SPEC-00.3/00.4 in `00-conventions.md`
      point to this file.
