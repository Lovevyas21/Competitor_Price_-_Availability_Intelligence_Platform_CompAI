# Infrastructure

Two stacks, split by lifetime rather than by layer. The whole point is that one of them
can be destroyed after every demo and the other never is.

```
infra/
  persistent/   apply once, never destroy   ~$0.30/month
  ephemeral/    apply, demo, destroy        ~$0.035/hour
```

## Why the split

Running this continuously costs roughly $30/month, which against a $50 credit balance is
about six weeks. Running it only while demonstrating it costs a few dollars a year.

That only works if teardown is genuinely repeatable, and the original single stack was
not: `deletion_protection = true` made `terraform destroy` fail outright, and a fixed
`final_snapshot_identifier` meant the *second* destroy failed because the snapshot name
already existed. Both are correct for a production database and wrong for one that
exists for an afternoon.

What makes the database safe to throw away is the bronze layer. Every raw API payload is
in the persistent stack's S3 bucket, so the warehouse is rebuilt with `cpi replay` in
about thirty seconds without a single upstream call. Destroying it between demos is the
disaster-recovery story, performed rather than described.

### What lives where, and why

| Persistent | Reason it must survive |
|---|---|
| S3 bronze bucket | The warehouse is rebuilt from it. Losing it loses the history. |
| ECR repository | Images outlive the host; also the only way to roll back a tag. |
| SSM parameters (API keys) | Typed in by hand. Re-entering a key each demo is how keys end up committed. |
| SNS topic + subscription | Email subscriptions need confirming by clicking a link. |
| Budget alarm | Needs history to forecast, and is the one guard that must never be down. |

| Ephemeral | Reason it can go |
|---|---|
| VPC, subnets, security groups | Free to recreate, nothing stored. |
| EC2 instance | Stateless; rebuilt from the ECR image. |
| RDS instance | Reproducible from bronze. |
| `DATABASE_URL_OVERRIDE` | Contains an endpoint and password regenerated on every apply. |
| CloudWatch alarms | Reference resources that no longer exist once torn down. |

The two stacks are joined by data sources, not a shared state file, so neither needs a
remote backend to find the other. The cost of that is that `project` and `environment`
must match in both.

## First time

```bash
cd persistent
terraform init
terraform apply -var alert_email=you@example.com
```

Then fill in the secrets it created as empty placeholders:

```bash
aws ssm put-parameter --name /cpi/prod/GEMINI_API_KEY --value 'REAL_KEY' \
  --type SecureString --overwrite
```

Confirm the SNS subscription email. This is the part you only do once.

## Each demo

```bash
cd ephemeral
terraform apply          # ~15 minutes, RDS is the slow part
terraform output how_to_reach_the_database
```

Deploy the image, run migrations, replay bronze, demo. Then:

```bash
terraform destroy        # ~10 minutes
```

Spend is now zero until the next apply. Verify with the budget alarm rather than trust:
`aws ce get-cost-and-usage` or the Billing console.

## Reaching the database

RDS has no public address, and the operator's ISP blocks outbound 5432 anyway. Both
problems have one answer — port-forward through SSM, no bastion and no inbound rule:

```bash
terraform -chdir=ephemeral output -raw how_to_reach_the_database
```

Then connect to `localhost:5433`.

## Before this is production

- Move state to S3 with DynamoDB locking (commented in `versions.tf`). Local state on a
  laptop is not infrastructure of record.
- Set `db_deletion_protection = true` and `db_skip_final_snapshot = false` for anything
  holding data that cannot be rebuilt.
- Raise `db_backup_retention_days`; it is 1 here because the warehouse is reproducible.
