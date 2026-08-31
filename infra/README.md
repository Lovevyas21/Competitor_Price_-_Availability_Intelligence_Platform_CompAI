# Infrastructure

Terraform for the AWS deployment described in the build document: a single EC2 host
running the compose stack, RDS PostgreSQL in private subnets, S3 for the bronze layer,
and secrets in SSM Parameter Store.

**Nothing here has been applied.** See `docs/adr/ADR-011`. The configuration is checked
with `fmt`, `init -backend=false` and `validate`, which need no AWS account and run in CI.

## Check it without an AWS account

```bash
cd infra
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

## What it creates

| Resource | Choice | Why |
|---|---|---|
| EC2 | `t4g.small`, Graviton | ~20% cheaper than x86; ECS Fargate's ALB+NAT+logs overhead is ~$90/mo |
| RDS | `db.t4g.micro`, Single-AZ, private | Portfolio budget; no public address, TLS forced via `rds.force_ssl` |
| Network | Public subnet + 2 private, **no NAT** | NAT is ~$32/mo — more than everything else combined |
| S3 | Versioned, encrypted, tiered | Bronze is the DR source; IA at 90d, Glacier IR at 365d |
| Secrets | SSM SecureString | Free at this scale; Secrets Manager is ~$0.40/secret/mo |
| Access | SSM Session Manager | No open port 22, no key material |
| Alarms | Budget (forecast + actual), CPU, RDS storage | An unnoticed bill is the real risk |

## Before a first apply

1. Set a **budget alarm in the console first**, not just in Terraform — the Terraform one
   only exists after the apply it is meant to protect you from.
2. Move state to S3 + DynamoDB: uncomment the `backend "s3"` block in `versions.tf`.
   Local state on a laptop is not infrastructure of record.
3. `cp terraform.tfvars.example terraform.tfvars` and set `alert_email`.
4. Run `terraform plan` and read it. This configuration has never been planned against a
   real account, so expect to resolve genuine issues on the first pass.
5. Costs begin at apply. `terraform destroy` requires disabling `deletion_protection` on
   the RDS instance first — deliberate friction.

## Deploying

`.github/workflows/deploy.yml` is `workflow_dispatch` only and requires typing `deploy`
to confirm. It assumes an AWS role via OIDC (no stored keys) and rolls out with SSM Run
Command (no SSH). Configure repository variables `AWS_ROLE_ARN`, `AWS_REGION`,
`ECR_REPOSITORY` and `APP_INSTANCE_ID` first.
