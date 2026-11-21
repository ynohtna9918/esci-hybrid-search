# SPEC-02: Indexing (BM25, embeddings, Postgres)

Package: `src/esci_search/index/`. Entry point: `python -m esci_search.index {bm25,embed,pg-load,all,upload-s3}`
(`make index` = `all` = bm25 → embed → pg-load against local Postgres).
Input: `data/processed/products.parquet` (SPEC-01.6). Output root: `data/index/`.

## SPEC-02.1 Lexical tokenization (`index/tokenize.py`)

One tokenizer is used for both documents and queries:
- lowercase → regex split `(?u)\b\w+\b` (single-character tokens are **kept**: "size 5", "2 x 4" matter in product search)
  → English stopword removal → PyStemmer `english` stemmer.
- `make_tokenizer() -> Tokenizer` returns a configured `bm25s` tokenizer (or a thin wrapper with
  the same behavior). `TOKENIZER_CONFIG: Final[dict]` records every setting and is stored in index metadata.

## SPEC-02.2 BM25 index (`index/bm25_index.py`)

```python
@dataclass(frozen=True)
class Bm25Params: k1: float = 1.2; b: float = 0.75; method: Literal["lucene"] = "lucene"

def corpus_sha256(products: pd.DataFrame) -> str
def build_bm25(products: pd.DataFrame, params: Bm25Params, out_dir: Path) -> Path
def load_bm25(index_dir: Path) -> Bm25Index

class Bm25Index:
    product_ids: np.ndarray                         # shape (N,), str, row order of the index
    def search(self, query: str, k: int) -> list[Scored]
    def score_candidates(self, query: str, product_ids: Sequence[str]) -> np.ndarray   # Track R
```

- `corpus_sha256`: sha256 over UTF-8 lines `f"{product_id}\t{doc_text}\n"` in ascending `product_id` order.
- Layout: `data/index/bm25/{corpus_sha[:8]}-k1{k1}-b{b}/` containing the `bm25s` save files, `product_ids.npy`,
  and `meta.json` (`corpus_sha256`, params, `TOKENIZER_CONFIG`, `n_docs`, build seconds).
- `score_candidates` uses the **full-corpus** IDF statistics (it does not re-index the candidates).
  Unknown product ids raise `RetrievalError`. A query with no in-vocabulary tokens returns all zeros.
- Dev tuning grid: `k1 ∈ {0.9, 1.2, 1.5}`, `b ∈ {0.4, 0.75, 0.9}`; one build per point.

## SPEC-02.3 Embeddings (`index/embed.py`)

```python
@dataclass(frozen=True)
class EncoderSpec:
    model_name: str = "intfloat/e5-small-v2"
    dim: int = 384
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    max_len_query: int = 64
    max_len_passage: int = 256

class Encoder:
    def __init__(self, spec: EncoderSpec, device: str | None = None) -> None   # auto: cuda > mps > cpu
    def encode_queries(self, texts: Sequence[str]) -> np.ndarray      # float32, (n, dim), L2-normalized
    def encode_passages(self, texts: Sequence[str], batch_size: int) -> np.ndarray

def embed_corpus(products: pd.DataFrame, spec: EncoderSpec, out_dir: Path, *, shard_size: int = 50_000) -> Path
```

- `embed_corpus` writes `data/index/emb/{model_slug}/{corpus_sha[:8]}/shard_{i:05d}.npy` (float16),
  is **resumable** (it skips complete shards), then writes `embeddings.npy` (float16, (N, dim)),
  `product_ids.npy` (row-aligned), and `meta.json` (spec, device, seconds, corpus hash).
- fp16 inference on CUDA; fp32 on CPU. Embeddings are normalized **before** the fp16 cast.
- The same `Encoder` class is used offline and in the service (SPEC-05.2). Never reimplement the prefix logic elsewhere.

## SPEC-02.4 Postgres schema (`index/pg_schema.sql`)

Target: PostgreSQL 17 with pgvector ≥ 0.8.0 (local image `pgvector/pgvector:pg17`; RDS PG 17.x).

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS products (
  product_id  text PRIMARY KEY,
  title       text NOT NULL DEFAULT '',
  brand       text,
  color       text,
  bullets     text,
  doc_text    text NOT NULL,
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, doc_text)) STORED
);
CREATE INDEX IF NOT EXISTS products_tsv_gin ON products USING gin (tsv);

CREATE TABLE IF NOT EXISTS product_embeddings (
  product_id  text PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
  model       text NOT NULL,
  emb         halfvec(384) NOT NULL
);
-- created AFTER bulk load (SPEC-02.5):
-- CREATE INDEX product_embeddings_hnsw ON product_embeddings
--   USING hnsw (emb halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS index_meta (
  index_version  text PRIMARY KEY,         -- '{corpus_sha[:8]}-{model_slug}-{YYYYMMDD}'
  corpus_sha256  text NOT NULL,
  encoder        text NOT NULL,
  n_products     integer NOT NULL,
  params         jsonb NOT NULL,           -- HNSW m/ef_construction, tokenizer config, etc.
  created_at     timestamptz NOT NULL DEFAULT now(),
  is_active      boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_index ON index_meta (is_active) WHERE is_active;
```

Canonical queries are constants in `src/esci_search/index/sql.py`, imported by SPEC-03 (sync, offline)
and SPEC-05 (async, online). Nobody writes these queries inline. Reference copy:

```sql
-- PGFTS_RETRIEVE (Track F)
SELECT product_id, ts_rank_cd(tsv, q) AS score
FROM products, websearch_to_tsquery('english', %(query)s) q
WHERE tsv @@ q ORDER BY score DESC, product_id ASC LIMIT %(k)s;

-- PGFTS_SCORE (Track R)
SELECT product_id, ts_rank_cd(tsv, q) AS score
FROM products, websearch_to_tsquery('english', %(query)s) q
WHERE product_id = ANY(%(ids)s);

-- DENSE_RETRIEVE (Track F); run inside a transaction after: SET LOCAL hnsw.ef_search = <int>
SELECT product_id, 1 - (emb <=> %(qvec)s::halfvec) AS score
FROM product_embeddings ORDER BY emb <=> %(qvec)s::halfvec LIMIT %(k)s;

-- HYDRATE (service)
SELECT product_id, title, brand FROM products WHERE product_id = ANY(%(ids)s);
```

Note: `websearch_to_tsquery` ANDs the terms, so recall on long queries may be low. That cost is
measured by comparison C4, not hidden (EVAL_PROTOCOL §7).

## SPEC-02.5 Loader (`index/pg_load.py`)

```python
def apply_schema(conn: psycopg.Connection) -> None
def load(conn: psycopg.Connection, source: str, *, activate: bool = True) -> str   # returns index_version
```

- `source` is a local directory or an `s3://bucket/prefix/`. Both contain `products.parquet`,
  `embeddings.npy`, `product_ids.npy`, `meta.json`.
- If `index_meta` already holds the same (`corpus_sha256`, `encoder`), log "up to date" and return the existing version.
- Steps: `COPY` products into `products_stage` → `INSERT ... ON CONFLICT (product_id) DO UPDATE` →
  `COPY` embeddings (text format `[v1,...,v384]`) → `SET maintenance_work_mem` (configurable, default `'1GB'`) →
  build HNSW → `ANALYZE` → insert `index_meta` → if `activate`, flip `is_active` in one transaction.
- Log rows/sec per phase and the final `pg_total_relation_size` of `product_embeddings` (an input to ADR-0003).
- `make index` runs `build_bm25` → `embed_corpus` → `load` against local Docker Postgres.
  `python -m esci_search.index upload-s3 --bucket ...` copies the artifacts for the cloud loader (SPEC-06.6).

## Tests

| Test | Asserts |
|---|---|
| `unit/test_tokenize.py` | single-char tokens kept; stemming `running→run`; stopwords removed; same output for query and doc paths |
| `unit/test_bm25.py` | on the synthetic 20-product fixture: exact-title query ranks its product 1st; `score_candidates` equals `search` scores for the same ids; OOV query → zeros; corpus hash stable under row shuffles |
| `unit/test_embed.py` | prefixes applied; output L2 norm = 1 ± 1e-3; resumable sharding (kill after shard 1, rerun, identical final array). Uses a tiny model from `sentence-transformers` test fixtures, or mocks |
| `gpu/test_embed_precision.py` (SPEC-02.3, marker `gpu`, skipped without CUDA) | CPU fp32 vs GPU fp16 encodings of the same 1,000 passages: min cosine >= 0.999 |
| `integration/test_pg_load.py` | load the fixture twice → second run is a no-op; HNSW index exists; exactly one active `index_meta` row; canonical queries return ≤ k rows sorted correctly |
