# SPEC-06: AWS infrastructure (CDK, Python)

Directory: `infra/`. Region `us-west-2`. Tool: AWS CDK v2 (Python) with `cdk-nag` (AwsSolutions pack).
Every stack is tagged `project=esci-hybrid-search`.

## SPEC-06.1 App and context (`infra/app.py`, `infra/cdk.json`)

| Context key | Default | Meaning |
|---|---|---|
| `ingress_cidr` | **required** | CIDR allowed to reach the ALB (your IP /32; `cloud_up.sh` fills it in) |
| `alarm_email` | **required** | SNS subscription for alarms and budget alerts |
| `db_instance_class` | `db.t4g.medium` | final value per ADR-0003 |
| `service_cpu` / `service_memory` | `2048` / `4096` | Fargate task size (ARM64) |
| `desired_count` | `1` | fixed; no autoscaling in v1 |
| `image_tag` | git sha7 | ECR tag to deploy |
| `github_repo` | `ynohtna9918/esci-hybrid-search` | OIDC trust subject |
| `loadtest_session` | `false` | if true: deploy the `loadgen` task definition and set `ESCI_ALLOW_CACHE_BYPASS=true` on the API (SPEC-07.0) |

Stacks and lifetimes:

| Stack | Contents | Lifetime |
|---|---|---|
| `EsciAccount` | GitHub OIDC provider + deploy role; AWS Budget | deploy once |
| `EsciNetwork` | VPC, subnets, gateway endpoints, security groups | persistent (free) |
| `EsciData` | RDS, DynamoDB, S3 artifacts bucket, ECR repo, DB secret | persistent; RDS **stopped** between sessions |
| `EsciService` | ECS cluster, task definitions (api, loader), ALB, log groups | **ephemeral**: per test session |
| `EsciMonitoring` | dashboard, alarms, SNS topic | ephemeral with Service |

## SPEC-06.2 Network (`infra/stacks/network.py`)

- VPC across 2 AZs: 2 public /24 + 2 isolated /24 subnets. **`nat_gateways=0`** (ADR-0004).
- Gateway endpoints (no hourly charge): S3 and DynamoDB, attached to all route tables.
- Security groups:
  - `alb_sg`: ingress TCP 80 from `ingress_cidr` only.
  - `svc_sg`: ingress TCP 8000 from `alb_sg`.
  - `loader_sg`: no ingress.
  - `db_sg`: ingress TCP 5432 from `svc_sg` and `loader_sg` only.
- Fargate tasks run in **public** subnets with `assign_public_ip=True`, so they can reach Bedrock, ECR, and
  CloudWatch without a NAT. Their inbound path is only the ALB (via `svc_sg`).
- TLS: deferred (no domain in v1). Exposure is limited to one /32 during test windows. This is documented in the README.

## SPEC-06.3 Data (`infra/stacks/data.py`)

- **RDS PostgreSQL 17** (latest 17.x minor at W4, pinned explicitly), single-AZ, gp3 20 GiB, isolated subnets,
  `publicly_accessible=False`, credentials generated into Secrets Manager (`esci/db`), backup retention 1 day,
  `removal_policy=SNAPSHOT`, deletion protection off.
  Parameter group: `maintenance_work_mem=1048576` (KB, for the HNSW build), `log_min_duration_statement=200`,
  `shared_preload_libraries=pg_stat_statements`.
- **DynamoDB** `esci-search-cache`: on-demand, PK `ck` (S), TTL attribute `ttl`, `removal_policy=DESTROY`.
- **S3** `esci-artifacts-<account>`: block public access, enforce SSL, `auto_delete_objects`, lifecycle that expires `index/` versions after 30 days except the active one (tagged).
- **ECR** `esci-search`: scan on push, keep the last 10 images.

## SPEC-06.4 Service (`infra/stacks/service.py`)

- ECS cluster with Container Insights **off** (cost); the EMF metrics cover the needs.
- Task definition `api`: ARM64, `service_cpu`/`service_memory`, container port 8000, image `esci-search:<image_tag>`.
  Env: `ESCI_LOG_JSON=true`, `ESCI_DDB_TABLE`, `ESCI_AWS_REGION`, `AWS_EMF_ENVIRONMENT=Local`, `ESCI_TORCH_THREADS=<vCPU>`.
  Secret: `ESCI_PG_SECRET_JSON` ← the whole `esci/db` secret (Settings builds the DSN from it; SPEC-00.2).
  Log driver awslogs, retention 14 days.
- Fargate service: `desired_count`, public subnets, `svc_sg`, health-check grace period 90 s, circuit breaker with rollback.
- ALB internet-facing, listener HTTP:80 → target group :8000; health check `GET /readyz`, interval 15 s,
  healthy 2 / unhealthy 3, deregistration delay 10 s.
- Task definition `loader`: same image, command `python -m esci_search.index pg-load --source <s3 uri>`,
  2 vCPU / 8 GB, `loader_sg`. It is not a service; it runs via `RunTask` (SPEC-06.6).
- **Task role (least privilege):** `dynamodb:GetItem, PutItem` on the cache table ARN; `bedrock:Rerank` and
  `bedrock:InvokeModel` on the two rerank model ARNs; `s3:GetObject, ListBucket` on `artifacts/index/*` (loader only);
  no wildcard resources. Execution role: ECR pull, logs, `secretsmanager:GetSecretValue` on `esci/db`.

## SPEC-06.5 Monitoring and cost guard (`infra/stacks/monitoring.py`, `infra/stacks/account.py`)

- Dashboard `EsciSearch`: widgets per DESIGN §10 (p50/p99 `LatencyMs` per stage for each pipeline, RPS, 5xx rate,
  cache hit ratio = sum(CacheHit)/sample count, RDS CPU, DatabaseConnections, FreeableMemory).
- Alarms → SNS topic → `alarm_email`:
  1. p99 `LatencyMs{Stage=total, Pipeline=hybrid_rrf}` > 250 for 5 of 5 one-minute periods;
  2. 5xx share > 1% for 5 minutes (metric math on `Requests`);
  3. RDS `FreeableMemory` < 200 MB for 5 minutes.
- `EsciAccount`: AWS Budget, monthly cost limit **$30**, notifications at 80% actual and 100% forecasted.
  GitHub OIDC provider + role `esci-deploy` trusted for `repo:<github_repo>:environment:aws-dev`.
  Its permissions: CDK bootstrap roles (`sts:AssumeRole` on `cdk-*`), ECR push to `esci-search`, and
  `ec2:AuthorizeSecurityGroupIngress` / `RevokeSecurityGroupIngress` conditioned on the `alb_sg` ARN (SPEC-08.3).

## SPEC-06.6 Cloud index load (`scripts/cloud_load_index.sh`)

1. `python -m esci_search.index upload-s3 --bucket <artifacts>` (from the local machine).
2. `aws ecs run-task` for the `loader` task definition in a public subnet, with `loader_sg`.
3. Wait for the stop, print the exit code and the last 50 log lines, and fail if the exit code ≠ 0.
4. Verify by calling `/readyz` and checking the reported `index_version`.

## SPEC-06.7 Session scripts (`scripts/cloud_up.sh`, `scripts/cloud_down.sh`, `scripts/cost_snapshot.sh`)

- `make cloud-up`: start the RDS instance if stopped (wait for `available`) → build and push the `linux/arm64` image →
  `cdk deploy EsciNetwork EsciData EsciService EsciMonitoring -c ingress_cidr=<your ip>/32 -c image_tag=<sha7>` →
  wait for `/readyz` → run the golden-query smoke test (SPEC-08.3). It prints the ALB URL and a reminder to run `cloud-down`.
- `make cloud-down`: `cdk destroy EsciMonitoring EsciService` → `aws rds stop-db-instance` → list the remaining ECS services
  and ALBs and fail loudly if any remain. It warns that AWS restarts a stopped RDS instance automatically after 7 days.
- `make cloud-down PURGE=1`: also destroys `EsciData` (a final snapshot is kept).
- `make cost-snapshot FROM=YYYY-MM-DD TO=YYYY-MM-DD`: Cost Explorer `get-cost-and-usage`, grouped by service →
  `results/cost/<from>_<to>.json`, plus the unit prices used in DESIGN §8 (entered once, with source URL and date).

## Tests (`infra/tests/test_stacks.py`, `aws_cdk.assertions.Template`)

- 0 resources of type `AWS::EC2::NatGateway`.
- RDS `PubliclyAccessible` false; `db_sg` ingress sources are exactly {`svc_sg`, `loader_sg`}.
- The DynamoDB table has TTL on `ttl`; on-demand billing.
- Task-role policies: no `"Resource": "*"` for dynamodb, bedrock, s3, or secretsmanager actions.
- 3 CloudWatch alarms; Budget amount 30 USD.
- `alb_sg` ingress CIDR equals the `ingress_cidr` context.
- With `loadtest_session=true`: a `loadgen` task definition exists and `svc_sg` admits 8000 from `loadgen_sg`;
  with `false`: neither exists and `ESCI_ALLOW_CACHE_BYPASS` is absent from the API task.
- `cdk synth` passes `cdk-nag` AwsSolutions with every suppression carrying a written reason.
