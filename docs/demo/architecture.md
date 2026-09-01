# Architecture

This describes what is **built and running**, not the original plan. Where the two
differ, the reason is noted — those differences are the interesting part.

## System

```mermaid
flowchart LR
  subgraph SRC[Sources]
    OP[Open Prices<br/>keyless, real prices]
    FS[Fake Store<br/>keyless, dev/tests]
    RET[Best Buy / eBay / Digi-Key<br/>interface ready, keys pending]
  end

  subgraph SCHED[Celery Beat · 10 schedules]
    T1[tier-1 refresh · 6h]
    T2[tier-2 daily · tier-3 weekly]
    NB[marts · forecasts · matches · brief]
  end

  SCHED --> Q[(Redis broker<br/>3 queues)]
  Q --> W[Celery workers<br/>token-bucket rate limit<br/>+ daily quota guard]

  SRC --> W
  W -->|raw first| BR[(Bronze<br/>gzipped JSON<br/>local / S3)]
  W -->|set-based CDC| PG[(PostgreSQL + pgvector<br/>SCD2 · append-only events<br/>monthly partitions)]
  W -.->|exhausted retries| DLQ[(Dead letter)]
  BR -.->|cpi replay<br/>no upstream calls| PG

  PG --> DBT[dbt<br/>staging → intermediate → marts<br/>87 data tests]
  DBT --> MARTS[(5 marts)]

  MARTS --> FC[statsforecast<br/>AutoETS · AutoARIMA<br/>vs naive baseline]
  FC --> PG
  MARTS --> API[FastAPI<br/>X-API-Key]
  MARTS --> ALERT[Undercut alerts<br/>dedupe + staleness gate]
  ALERT --> SLACK[Slack webhook]
  MARTS --> BI[Metabase<br/>opt-in profile]

  PG --> EMB[fastembed 384-dim<br/>HNSW + blocking]
  EMB --> MATCH[(product_matches)]
  MATCH --> UI[Streamlit review]
  UI --> MATCH

  MARTS --> FACTS[Facts payload<br/>closed set of numbers]
  FACTS --> GUARD{Numeric guard}
  FACTS --> CREW[CrewAI crew<br/>optional]
  CREW --> GUARD
  GUARD -->|all numbers grounded| BRIEF[Weekly brief]
  GUARD -->|any unsupported| DET[Deterministic brief]
```

## Data flow

Beat enqueues per-source fetches → workers rate-limit, fetch, and write **raw to bronze
before parsing** → normalized rows land in Postgres through a set-based CDC path → dbt
builds marts and tests them → forecasts, alerts, matching and the weekly brief all read
marts, never raw tables.

## Deviations from the original plan, and why

| Planned | Built | Reason |
|---|---|---|
| Best Buy first | Open Prices + Fake Store first | Keyless sources prove the pipeline with zero approval latency; real sources drop into the same `SourceClient` interface |
| Open Food Facts | Open **Prices** | OFF has product attributes but no prices. Open Prices carries real observed prices, dates and store locations — actual multi-retailer competitor data |
| Row-by-row CDC | Row-by-row **plus** set-based | Row-by-row assumed a local DB. At 298 ms RTT a day's replay took an estimated 3.3 h; the set-based path does it in 41 s. Both kept, with a parity test |
| sentence-transformers | **fastembed** (ONNX) | Same `all-MiniLM-L6-v2` 384-dim model without torch (~2.5 GB) on a 7.4 GB machine |
| CrewAI writes the brief | Deterministic brief; CrewAI optional and gated | An unvalidated LLM brief is a liability in a pricing context. The guard is a hard gate, so the worst case is a plainer brief, never a wrong one |
| Deploy to AWS | Terraform written, **not applied** | Only phase that costs money (~$28–36/mo); nothing needs AWS to be demonstrated |

## Ingestion sequence

```mermaid
sequenceDiagram
    participant B as Beat
    participant W as Worker
    participant R as Redis
    participant S as Source API
    participant BR as Bronze
    participant PG as Postgres

    B->>R: enqueue_tier(1)
    R->>W: fetch_sku × N
    W->>R: token bucket + daily quota
    alt limit exceeded
        R-->>W: retry after N seconds
    else quota exhausted
        W->>BR: dead-letter (no retry — resets tomorrow)
    end
    W->>S: GET product
    S-->>W: raw JSON
    W->>BR: persist raw (before parsing)
    W->>W: normalize + validate batch
    W->>PG: set-based CDC (idempotent)
    Note over BR,PG: A normalizer bug is replayable from bronze<br/>with no upstream traffic and no quota spend
```

## Reliability properties

- **History is never overwritten.** Price and stock tables are append-only; a late or
  corrected observation adds a row.
- **Exactly one current product version**, enforced by a partial unique index.
- **Idempotent ingestion.** Every event carries a key hashed from source, product,
  retailer and a time bucket, uniquely indexed — replays collapse instead of duplicating.
- **The database is disposable.** Losing it is survivable because bronze holds every raw
  payload. This was proven under real failure: the Postgres volume was lost to a Docker
  storage fault and rebuilt in 30 seconds.
