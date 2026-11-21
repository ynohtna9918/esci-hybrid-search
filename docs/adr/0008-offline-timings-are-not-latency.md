# ADR-0008: Offline timings are not service latency

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
Offline evaluation runs on the development machine (WSL2, RTX 5070, GPU encoding via `--extra gpu`, SPEC-00.1),
while the service runs CPU-only on Fargate arm64 (`--extra cpu`, SPEC-08.4). Every run directory writes
`timings.json` (SPEC-04.4). Without an explicit rule, these GPU wall-clock numbers could be quoted next to,
or instead of, the service latencies defined in EVAL_PROTOCOL §10, and they are not comparable.
No experiment has been run yet; this is a clarification, not a reaction to a result.

## Options
1. Leave the protocol silent and rely on judgement when writing up.
2. Add one sentence to EVAL_PROTOCOL §10 that scopes `timings.json` to evaluation throughput.

## Decision
Option 2. EVAL_PROTOCOL §10 gains: "Offline timings (`timings.json`) measure evaluation throughput on the
development GPU and are never reported as service latency." Recorded in §12 Amendments.

## Consequences
Latency claims come only from k6 and EMF (§10). CPU latency curves needed before W4 (e.g. the cross-encoder
`n_rerank` curve in ROADMAP G3) must be measured explicitly on CPU and labelled as such.
