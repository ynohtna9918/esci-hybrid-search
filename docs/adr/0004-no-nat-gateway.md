# ADR-0004: No NAT Gateway; Fargate in public subnets

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
A NAT Gateway bills per hour plus per GB processed, even when idle. It is the classic surprise line item
on small AWS projects. The tasks need outbound access to ECR, CloudWatch Logs, Secrets Manager, Bedrock,
DynamoDB, and S3.

## Options
1. Private subnets + NAT Gateway: the conventional layout; ongoing cost.
2. Private subnets + interface VPC endpoints for every service: each interface endpoint is also billed per AZ-hour.
3. **Public subnets with public IPs for tasks; inbound restricted by security groups; free gateway endpoints for S3 and DynamoDB.**

## Decision
Option 3. RDS stays in isolated subnets with no internet route. The only inbound path to the API is
`alb_sg → svc_sg` (and `loadgen_sg → svc_sg` during load-test sessions).

## Consequences
- Tasks have public IPs, so the security group is the only inbound barrier. A CDK test asserts its exact rules.
- If the project later needs private subnets, option 2 for just the endpoints actually used is the path.
