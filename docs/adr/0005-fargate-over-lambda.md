# ADR-0005: ECS Fargate (not Lambda) for the API

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
The API loads two transformer models (~130 MB each) and keeps a Postgres connection pool. The SLO is on p99.

## Options
1. **Lambda (container image)**: scales to zero; cold starts that load models add seconds to tail latency;
   per-invocation connections to RDS need RDS Proxy (extra cost) to avoid connection storms.
2. **ECS Fargate**: a warm process, a long-lived pool, predictable p99; it bills while running.

## Decision
Fargate, with an ephemeral `EsciService` stack (deploy for a session, destroy after) to control cost.

## Consequences
- The cost model (DESIGN §8) charges the fixed hourly cost against the measured throughput Q.
- A Lambda variant is a possible v2 comparison: same image, cold vs warm p99.
