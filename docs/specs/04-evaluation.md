# SPEC-04: Evaluation harness

Package: `src/esci_search/eval/`. Entry point: `python -m esci_search.eval {run,compare,final,gate}`
(`gate` is specified in SPEC-08.2 and implemented in `eval/gate.py`).
Normative reference: `docs/EVAL_PROTOCOL.md`. If this spec and the protocol disagree, the protocol wins
and this spec is fixed.

## SPEC-04.1 Qrels and query sets (`eval/qrels.py`)

```python
Qrels = Mapping[int, Mapping[str, float]]          # query_id -> {product_id: gain}

def load_queries(processed: Path, split: str) -> list[Query]       # ordered by `order` for dev/ci_dev, else by query_id
def load_qrels(processed: Path, split: str) -> Qrels
def candidates(qrels: Qrels) -> dict[int, list[str]]               # Track R candidate ids, sorted ascending
def excluded_idcg_zero(qrels: Qrels) -> set[int]
def discriminative(qrels: Qrels) -> set[int]                       # ≥ 2 distinct gains
```

- `split == "test"` raises `LeakageError` unless the guard in SPEC-04.6 has set the process-wide
  `_FINAL_EVAL_UNLOCKED` flag. Only `eval/final.py` sets it.

## SPEC-04.2 Metrics (`eval/metrics.py`)

```python
def dcg(gains: Sequence[float], k: int | None = None) -> float
def ndcg(ranked: RankedList, qrel: Mapping[str, float], k: int | None = None, *, condensed: bool = False) -> float
def judged_at_k(ranked: RankedList, qrel: Mapping[str, float], k: int = 10) -> float
def recall_e_at_k(ranked: RankedList, qrel: Mapping[str, float], k: int = 100) -> float | None   # None if no E
def evaluate(runs: Sequence[RankedList], qrels: Qrels, track: Literal["R", "F"]) -> pd.DataFrame
```

- Definitions: EVAL_PROTOCOL §3–§5, exactly. An item is **E** iff its gain is 1.0.
- `condensed=False` with an unjudged item in the list raises `ValueError` (in Track R that would be a bug).
- `evaluate` returns one row per (query_id) with columns:
  - Track R: `ndcg`, `ndcg@10`, `ndcg_exp` (exponential gain $2^g - 1$, robustness only; ADR-0006), `discriminative: bool`
  - Track F: `ndcg_c@10` (condensed), `judged@10`, `recall_e@100`, `discriminative: bool`
  - IDCG=0 queries are dropped; the count goes to `df.attrs["excluded_idcg_zero"]`.

## SPEC-04.3 Statistics (`eval/significance.py`)

```python
@dataclass(frozen=True)
class Comparison: metric: str; mean_a: float; mean_b: float; delta: float; ci_lo: float; ci_hi: float;
                  p_value: float; p_holm: float | None; n: int

def paired_bootstrap(a: np.ndarray, b: np.ndarray, *, n_resamples: int = 10_000, seed: int = 42,
                     alpha: float = 0.05) -> tuple[float, float, float]           # (delta, lo, hi)
def randomization_test(a: np.ndarray, b: np.ndarray, *, n_perm: int = 10_000, seed: int = 42) -> float
def holm(pvals: Mapping[str, float]) -> dict[str, float]
def compare(per_query_a: pd.DataFrame, per_query_b: pd.DataFrame, metric: str, **kw) -> Comparison
```

- `a` and `b` are aligned on `query_id` (inner join; a mismatch in query sets raises `ValueError`).
- Bootstrap: resample query indices with replacement; percentile CI.
- Randomization: flip the sign of each $\delta_q$ with probability 0.5;
  $p = (1 + \#\{|\bar\delta^*| \ge |\bar\delta|\}) / (1 + n_{\text{perm}})$.
- Holm: sort ascending, adjust $p_{(i)} \cdot (m - i + 1)$, enforce monotonicity, cap at 1.

## SPEC-04.4 Runner (`eval/runner.py`, `eval/__main__.py`)

```
python -m esci_search.eval run --exp configs/experiments/<name>.yaml [--split dev|ci_dev] [--tracks R,F] [--limit N]
python -m esci_search.eval compare --a <run_id> --b <run_id> --track R --metric ndcg
```

- `run_id = f"{utc:%Y%m%dT%H%M%SZ}-{exp.name}-{split}-{git_sha7}{'-dirty' if dirty else ''}"`.
- Run directory `results/runs/<run_id>/`:

| File | Content |
|---|---|
| `config.resolved.yaml` | the merged config actually used |
| `metrics.json` | per track: mean of each metric, bootstrap 95% CI of the mean, n_queries, excluded counts, discriminative-subset means |
| `per_query.parquet` | `query_id, track, <metric columns>` |
| `rankings.parquet` | `query_id, track, rank, product_id, score` (Track R: full list; Track F: top 100) |
| `timings.json` | wall seconds per stage, queries/sec, peak RSS |
| `env.json` | git sha + dirty flag, Python and package versions (`importlib.metadata`), CPU/GPU model, `ESCI_COMMIT`, data manifest hash |

- `--limit` is allowed only for `dev`, and the run is tagged `-limit{N}` so it can never be mistaken for a full run.
- `compare` writes `results/comparisons/{a}__vs__{b}__{track}__{metric}.json` (a `Comparison` as JSON).

## SPEC-04.5 Reporting (`scripts/make_results_table.py`)

- Reads `results/final/*/summary.json` (confirmatory) and the latest full dev run per experiment (exploratory).
- Writes `results/RESULTS.md`: one table per track, with metric ± CI half-width, C1–C4 with Holm p-values,
  the random floor (mean ± std over 5 seeds), and the external anchors (EVAL_PROTOCOL §9) with their caveat.
- Rewrites only the README region between `<!-- RESULTS:START -->` and `<!-- RESULTS:END -->`.
- Numbers use 3 decimals; latency is an integer in ms; cost uses 2 decimals.
- The script fails if any number it would print does not come from a file it read (no hard-coded values).

## SPEC-04.6 Final evaluation guard (`eval/final.py`)

`FINAL_EVAL=1 python -m esci_search.eval final [--allow-rerun "reason"]` (`make final-eval`):
1. Require `FINAL_EVAL=1`, a clean `git status --porcelain`, and `configs/frozen.txt`, whose lines are
   `<sha256>  configs/experiments/<name>.yaml`; every hash must match the current file content.
2. `frozen_hash = sha256(frozen.txt)`. If `results/final/<frozen_hash>/` exists, abort unless
   `--allow-rerun` is given; the reason is appended to EVAL_PROTOCOL §12 by the script.
3. Unlock the test split, run every frozen config on Tracks R and F (run directories go to
   `results/final/<frozen_hash>/runs/<run_id>/`), run C1–C4 (EVAL_PROTOCOL §7) with Holm, and write
   `results/final/<frozen_hash>/summary.json`.
- Any failed check raises `LeakageError` (exit 2).

## Tests

| Test | Asserts |
|---|---|
| `unit/test_metrics.py` | vs `sklearn.metrics.ndcg_score` within 1e-9 on 1,000 random tie-free cases (k ∈ {None, 10}); oracle = 1.0; reversed < 1; condensed drops unjudged; unjudged in non-condensed → `ValueError`; `recall_e` None without E |
| `unit/test_significance.py` | a == b → delta 0, CI [0, 0], p = 1; constant +0.1 shift on 200 queries → CI ⊂ (0, ∞) and p < 0.001; Holm matches a hand example; seeds reproducible |
| `unit/test_leakage_guard.py` | `load_qrels(split="test")` raises without the unlock; `final` refuses dirty tree / hash mismatch / missing env var / an existing result |
| `unit/test_runner_smoke.py` | the `random` pipeline on the synthetic fixture produces every file in the run-directory table |
