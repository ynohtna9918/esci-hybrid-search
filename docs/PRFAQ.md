# PR/FAQ: esci-hybrid-search

_Working Backwards document. Written before implementation; the press release describes the
intended end state. Bracketed values are filled only from measured results._

## Press release

**A product search service that shows its receipts.**

SEATTLE — Today we release `esci-hybrid-search`, an open-source product search service that
combines keyword search, semantic vector search, and neural reranking, and reports, layer by
layer, what each one costs and what it buys.

On Amazon's human-labeled Shopping Queries Dataset (US test split, [n] scored queries), hybrid retrieval
with reranking reaches nDCG [Y] against [X] for the BM25 baseline. The service holds p99 latency
at [Z] ms at [R] requests per second on a single Fargate task, at [$C] per million queries.

"Most search demos show one good-looking query," said the author. "This one shows thousands of them,
scored by human annotators, with confidence intervals, a latency budget, and a bill."

The service runs on AWS (ECS Fargate, RDS for PostgreSQL with pgvector, DynamoDB, Bedrock).
It is deployed with AWS CDK and GitHub Actions, and anyone can reproduce every number with
`make final-eval`.

## External FAQ

**Q: Who is the customer?**
A shopper typing a short, messy query ("iphone 13 case clear magsafe") who wants an exact match
on the first screen. The secondary customer is an engineer deciding whether a reranker is worth
its latency.

**Q: What does "better" mean?**
More Exact products ranked higher, measured by nDCG with ESCI's gain mapping
(E=1.0, S=0.1, C=0.01, I=0.0), within a fixed latency budget. See `EVAL_PROTOCOL.md`.

**Q: Why should I trust the numbers?**
- The labels are Amazon's human annotations, not ours.
- The test split is untouched until one final, scripted run (`make final-eval`).
- Our metric code is cross-checked against `sklearn.metrics.ndcg_score`.
- Improvements come with paired-bootstrap 95% confidence intervals.
- Load-test and billing artifacts are committed under `results/`.

## Internal FAQ

**Q: Why not just fine-tune a big model and report the top leaderboard number?**
KDD Cup 2022 winners reached about 0.90 nDCG with large ensembles. That is not the goal. The
goal is an *engineered system* with explicit trade-offs: quality versus p99 versus cost. A single
fine-tuned model is an optional v2 extension.

**Q: Why PostgreSQL + pgvector instead of OpenSearch?**
One database for products, full-text, and vectors keeps the operational surface small and
showcases SQL plus query-planning work. See ADR-0001.

**Q: What is the AWS budget?**
At most $60 total for the project. The cloud runs in ephemeral sessions (`make cloud-up` /
`make cloud-down`); all experiments run locally. AWS Budgets alerts at $30/month. See DESIGN §8.

**Q: What are the biggest risks?**
1. **Incomplete judgments** in full-corpus retrieval: most retrieved products have no label.
   Mitigated by condensed-list metrics and a Judged@10 report (EVAL_PROTOCOL §5).
2. **RDS memory:** an HNSW index over about 1M vectors may not fit small instances. Mitigated
   with `halfvec` and measured sizing (DESIGN §6).
3. **Scope creep:** v1 is fixed in ROADMAP; everything else goes to "v2 candidates".

**Q: What would make us stop or change direction?**
If hybrid retrieval gives no significant gain over BM25 on dev (95% CI includes 0), we report
the null result and refocus the project on latency and cost engineering rather than relevance.
