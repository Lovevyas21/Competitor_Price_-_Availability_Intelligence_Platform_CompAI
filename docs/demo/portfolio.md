# Portfolio assets

Every number below is measured (see `metrics.md`). Nothing here is aspirational — if a
claim could not be reproduced from the running system, it is not in this file.

## Résumé bullets

Pick three or four. The first two carry the most weight for data-engineering roles.

- Built a competitor price-intelligence platform (Python, Celery, PostgreSQL/pgvector,
  dbt, S3 lakehouse) ingesting **1,300+ products across 92 retailers and 16 currencies**
  with SCD2 change data capture, append-only event tables and monthly partitioning.
- Diagnosed a latency-bound CDC path against managed Postgres (298 ms RTT) and replaced
  it with a **set-based SQL implementation — a day's backfill fell from an estimated 3.3
  hours to 41 seconds** — proving equivalence with a parity test over both paths.
- Designed **raw-first ingestion**: every API payload is persisted before parsing, so the
  warehouse is reproducible. Rebuilt the full warehouse in **30 seconds with no upstream
  API calls** after losing the database to a storage fault.
- Modelled the warehouse in **dbt (staging → intermediate → marts) with 87 data tests**,
  including cross-field invariants that catch sign-flips and broken arithmetic, not just
  null checks.
- Implemented per-SKU forecasting with **Nixtla statsforecast** against a naive baseline,
  and **corrected an evaluation flaw that reported a flattering 0.15% MAPE** — scoring
  forward-filled days rather than real observations — to a truthful ~3.16%.
- Built cross-retailer product matching with **pgvector HNSW + 384-dim embeddings**,
  UPC-first precedence and banded thresholds (auto / review / reject), with a Streamlit
  human-review UI producing the labels for precision-recall measurement.
- Shipped an **LLM guardrail that rejects any generated number absent from a validated
  facts payload**, with automatic fallback to a deterministic brief — the guard caught two
  real bugs on its first run.
- Authored **11 ADRs** and Terraform for the full AWS stack (private RDS, Graviton EC2,
  S3 lifecycle, SSM secrets, least-privilege IAM), with CI running lint, tests, dbt and
  `terraform validate` without AWS credentials.

## LinkedIn post

> I spent the last stretch building a competitor price & availability intelligence
> platform — the kind of thing Prisync and Minderest sell — end to end.
>
> The parts I expected to be interesting were the pipeline: Celery Beat scheduling,
> SCD2 change data capture, dbt marts, per-SKU forecasting, pgvector product matching.
>
> The parts that actually taught me something were the mistakes I caught:
>
> **A forecast that looked excellent and wasn't.** My first run reported 0.15% MAPE,
> comfortably inside target. It was measuring my own forward-fill: I resample irregular
> prices onto a daily grid so the models see a regular frequency, and on a near-constant
> series "predict the last value" is trivially right. Scoring only genuinely observed days
> moved it to ~3.16%. Every model got worse. That was the point.
>
> **A CDC path that assumed a local database.** Row-by-row it issued ~5 statements per
> record — fine at sub-millisecond latency, pathological at 298 ms. A day's backfill would
> have taken 3.3 hours. Rewritten set-based: 41 seconds. I kept both and wrote a parity
> test, because the fast one is only worth having if it is provably identical.
>
> **A guardrail that failed its own author.** The weekly brief only states numbers present
> in a validated facts payload. Run against my own deterministic output it immediately
> flagged six — exposing that my number regex split "1309" into 130 and 9. A guard that
> cries wolf is a guard someone switches off.
>
> Also: my database was destroyed mid-project by a Docker storage fault. Because every raw
> payload is written to bronze before parsing, I rebuilt the entire warehouse in 30 seconds
> with zero API calls. That design choice stopped being theoretical.
>
> Repo, 11 ADRs and the measured numbers in the comments.

## Demo script (5 minutes)

1. **The problem** (30s) — retailers lose margin to undercuts they notice late.
2. **Show the undercut table** (60s) — real retailers, real gaps, −53.95% at the top.
   Point at the `confidence` column: every row is stale evidence, and the alerting layer
   knows it and withholds delivery. Surfacing that beats hiding it.
3. **Show the architecture diagram** (60s) — raw-first bronze, CDC, dbt marts, and the
   fact that every consumer reads marts rather than raw tables.
4. **Tell the replay story** (60s) — database destroyed by a storage fault, rebuilt in 30
   seconds from bronze. Explain why raw-before-parse is the reason.
5. **Show the brief and its guard** (60s) — 69 numbers checked, 0 unsupported, and the
   fallback that makes an LLM safe to use in a pricing context.
6. **Close on limitations** (30s) — name them. It reads as judgement, not as gaps.

## Interview questions to expect

**Why SCD2 rather than daily snapshots?**
Exact change history at a fraction of the storage. A snapshot of 1,300 products daily
stores 1,300 rows a day whether or not anything changed; insert-on-change stores a row
only when the price actually moves, plus a heartbeat to prove liveness. The cost is more
complex queries — `is_current` predicates and validity windows everywhere.

**At-least-once or exactly-once?**
At-least-once, deliberately. `acks_late=True` plus `task_reject_on_worker_lost` means a
crashed worker's task re-runs rather than vanishing. Duplicate work is harmless because
every event carries an idempotency key hashed from source, product, retailer and a time
bucket, uniquely indexed. Exactly-once across a network boundary is a much more expensive
promise, and idempotency buys the same outcome.

**How do you stop the LLM inventing numbers?**
It never sees the database. It receives a closed facts payload built from tested marts,
and its output is checked number-by-number against that payload. Anything unsupported
discards the LLM version for a deterministic render. The worst case is a plainer brief,
never a wrong one — and I know it works because it caught two bugs in my own code.

**Redis or SQS for the broker?**
Redis here: it supports Flower and remote control, and on a single host it is one
container. SQS would be the managed-AWS answer — infinite retention, native DLQ via
redrive — at the cost of losing Flower. The abstraction is Celery either way, so it is a
config change, not a rewrite.

**How would you scale to 100k SKUs?**
The set-based CDC path already scales with batch size rather than record count, so
ingestion is not the bottleneck. I would move the broker to SQS, run workers on Fargate to
scale out horizontally, partition more aggressively with BRIN indexes on `observed_at`,
and move bronze to Iceberg for ACID and time travel. The forecasting step is the real
problem: per-SKU model fitting is linear in SKUs, so it would need mlforecast with a
single global LightGBM model rather than 100k individual fits.

**Why Celery Beat instead of Airflow?**
For periodic polling with fan-out, Beat is enough and far lighter. I would move to
Dagster or Airflow when I needed DAG lineage, asset-aware orchestration and managed
backfills across interdependent jobs — my backfill is currently a parametrised task, which
works but is not lineage-aware.

**What went wrong?**
Best question to be ready for. Three real ones: a forecast metric that measured my own
data preparation; a CDC design that silently assumed a local database; and a guard whose
regex split long integers and reported phantom violations. Each was found by checking
output against expectations rather than by a test failing.
