# ADR-0007: Bedrock Rerank usage, limits, and truncation

- **Status:** Proposed. Facts to be filled in from AWS docs at W3, before the first call.
- **Date:** 2026-11-21

## Known facts (from AWS docs, Nov 2026)
- Rerank is called via `bedrock-agent-runtime` `Rerank` with `BEDROCK_RERANKING_MODEL`.
- Models: `amazon.rerank-v1:0` (us-west-2 among others; **not** us-east-1) and `cohere.rerank-v3-5:0`
  (us-west-2 and us-east-1 among others). Region `us-west-2` supports both.

## To fill in before use
| Item | Value | Source URL | Checked on |
|---|---|---|---|
| max documents per request | | | |
| max characters/tokens per document | | | |
| price per request (at our document count) | | | |
| account TPS quota in us-west-2 | | | |

## Decision
- E1 runs on at most 500 dev queries (`max_queries`, enforced by code).
- `doc_text` is truncated to the documented per-document limit (or 2,000 chars, whichever is lower).
- Bedrock ships in the service only if E1 shows a CI-excluding-0 gain over P5 **and** its cost per 1M queries is reported.
