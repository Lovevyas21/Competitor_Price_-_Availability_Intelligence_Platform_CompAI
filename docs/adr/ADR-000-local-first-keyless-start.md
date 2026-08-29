# ADR-000: Build local-first, starting from keyless data sources

**Status:** Accepted

## Context
The build document nominates Best Buy, eBay Browse, and Digi-Key as primary sources.
All three require registration and approval; eBay in particular needs Developers Program
approval (~1 business day) plus acceptance of a separate Buy API license, and the source
document itself rates India-based registration only "moderate-high confidence".

Deploying to AWS from day one would also incur ~$28-36/month before any data flows.

## Decision
1. Build the ingestion pipeline against **keyless sources first** (Fake Store API,
   Open Food Facts). They exercise the same code path -- client -> validation -> bronze
   write -> CDC upsert -- with zero approval latency.
2. Real sources plug in behind a common `SourceClient` interface once keys arrive.
3. Bronze raw-payload storage goes behind a **storage backend interface** with a local
   filesystem implementation. Switching to S3 is a config change, not a rewrite.
4. AWS deployment (Terraform, RDS, EC2, S3) is deferred to the final phase.

## Consequences
- The pipeline is provably working before any API key is a blocker.
- Phases 0-5 cost nothing and need no AWS account.
- Cost: one extra abstraction (the bronze backend) that a single-target build would not need.
  That abstraction is cheap and is also what makes the local -> S3 migration a one-liner.
- Risk: the keyless sources are less price-volatile than real retail, so forecasting
  quality can only be judged properly once a real source is connected.
