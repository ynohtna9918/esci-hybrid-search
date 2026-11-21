# SPEC-01: Data acquisition, loading, splits, text, data card

Package: `src/esci_search/data/`. Entry point: `python -m esci_search.data` (`make data`).

## SPEC-01.1 Download (`data/download.py`)

```python
ESCI_REPO: Final = "amazon-science/esci-data"
ESCI_COMMIT: Final[str]   # pinned 40-char SHA, set in W1 via `git ls-remote` and never floated
FILES: Final = ("shopping_queries_dataset_examples.parquet",
                "shopping_queries_dataset_products.parquet",
                "shopping_queries_dataset_sources.csv")

def download_all(dest: Path, *, force: bool = False) -> dict[str, str]:
    """Download FILES to dest; return {filename: sha256}."""
```

Behavior:
- URL: `https://github.com/{ESCI_REPO}/raw/{ESCI_COMMIT}/shopping_queries_dataset/{file}`.
- Stream to `dest/{file}.part`, then rename atomically. Skip a file if it exists, unless `force`.
- **LFS guard:** parquet files must start and end with the magic bytes `PAR1`. A small text file
  starting with `version https://git-lfs` raises `DataError("got LFS pointer, not data")`.
- **Checksums:** `configs/data_checksums.json` (committed) maps filename → sha256.
  If an entry exists and differs → `DataError`. If it is missing (the first run), write it and log a
  warning telling the user to commit it (trust on first use).

## SPEC-01.2 Load and validate (`data/load.py`)

```python
def load_examples(raw: Path, *, locale: str = "us", small_version: bool = True) -> pd.DataFrame
def load_products(raw: Path, *, locale: str = "us") -> pd.DataFrame
```

- `load_examples` returns columns `example_id:int64, query:string, query_id:int64,
  product_id:string, product_locale:string, esci_label:category{E,S,C,I}, split:category{train,test}`,
  filtered by locale and, if `small_version`, by `small_version == 1`.
- `load_products` returns `product_id, product_title, product_description, product_bullet_point,
  product_brand, product_color, product_locale`, filtered by locale.
- Validation (raises `DataError` with a count and 5 example rows):
  - `esci_label` outside {E,S,C,I}; null `query_id` / `product_id` / `query`;
  - duplicate (`query_id`, `product_id`) pairs;
  - a `query_id` mapped to more than one distinct `query` string;
  - an example `product_id` missing from the products table for the same locale.

## SPEC-01.3 Splits (`data/splits.py`)

```python
DEV_SIZE: Final = 1500
CI_DEV_SIZE: Final = 200

def make_splits(examples: pd.DataFrame, *, seed: int) -> pd.DataFrame:
    """Return DataFrame[query_id:int64, split:{train,dev,ci_dev,test}, order:int32]."""
```

Algorithm (deterministic, must not change after W1):
1. `train_ids = sorted(unique query_id where split == "train")` (ascending ints).
2. `perm = np.random.default_rng(seed).permutation(len(train_ids))`.
3. `dev = [train_ids[i] for i in perm[:DEV_SIZE]]`. The `order` column is the position in this list.
4. The first `CI_DEV_SIZE` of `dev` are **also** members of `ci_dev`. Output one row per (query_id, split)
   membership, so `ci_dev` queries appear twice: once as `dev`, once as `ci_dev`.
5. The remaining train ids → `train`. Official test ids → `test` (unchanged).

## SPEC-01.4 Text normalization (`data/text.py`)

```python
DEFAULT_FIELDS: Final = ("title", "brand", "color", "bullets")

def clean_field(x: str | None, *, max_chars: int | None = None) -> str
def build_doc_text(p: Mapping[str, str | None], fields: Sequence[str] = DEFAULT_FIELDS) -> str
def normalize_query(q: str) -> str
```

- `clean_field`: `None` → `""`; strip HTML tags (`<[^>]+>` → space); `html.unescape`; NFKC;
  replace `\r`, `\n`, `\t` with a space; collapse runs of whitespace; strip; truncate to `max_chars`
  at a word boundary if given.
- `build_doc_text`: fields map to `product_title`, `product_brand`, `product_color`,
  `product_bullet_point`; bullets use `max_chars=1000`; join the **non-empty** cleaned fields with `" | "`.
- `normalize_query`: NFKC → lowercase → collapse whitespace → strip. Used for cache keys and
  logging. Retrievers tokenize independently (SPEC-02.1).

## SPEC-01.5 Data card (`data/datacard.py`)

`write_data_card(processed: Path, out: Path = Path("docs/DATA_CARD.md")) -> None` writes:
- the source commit SHA and file sha256s;
- per split: #queries, #judgments, label distribution (counts and %), judged products per query (min/median/p95/max);
- the number of IDCG=0 queries and the size of the discriminative subset (EVAL_PROTOCOL §3);
- corpus size, #products with an empty title, `doc_text` length in chars (p50/p95/max);
- the share of `test` queries whose exact normalized string also appears in `train`/`dev` (leakage signal, reported only).

## SPEC-01.6 Processed outputs and CLI (`data/__main__.py`)

`python -m esci_search.data [--force]` runs download → load → validate → splits → text → write:

| File (`data/processed/`) | Columns |
|---|---|
| `queries.parquet` | `query_id, query, split, order` |
| `qrels.parquet` | `query_id, product_id, esci_label, gain` (US, small_version) |
| `products.parquet` | `product_id, title, brand, color, bullets, doc_text` (US corpus) |
| `manifest.json` | input sha256s, row counts, `seed`, `ESCI_COMMIT`, creation time |

The step is idempotent: if `manifest.json` matches the inputs and the seed, it exits 0 with "up to date".

## Tests

| Test | Asserts |
|---|---|
| `unit/test_text.py` | HTML stripped; `None` handled; bullets truncated at a word boundary; empty fields skipped in the join; `normalize_query("  IPhone 13 ")` → `"iphone 13"` |
| `unit/test_splits.py` | same seed → identical output; dev ∩ train = ∅; dev ∩ test = ∅; \|dev\| = 1500; ci_dev ⊂ dev and equals the first 200 by `order`; train + dev = official train |
| `unit/test_load_validation.py` | each validation rule fires on a crafted bad frame |
| `unit/test_download.py` | LFS pointer detected; checksum mismatch raises (network mocked) |
| `data/test_counts.py` (marker `data`) | on real data: US small = 29,844 q / 601,354 j; train 20,888 / 419,653; test 8,956 / 181,701 |
