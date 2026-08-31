# ADR-007: Add a set-based CDC path for bulk loads

**Status:** Accepted

## Context

`cdc.apply_record` processes one observation at a time, issuing roughly five statements
per record: look up the preceding price, check the current SCD2 version, upsert the
product, resolve the retailer, insert the event.

Against a local Postgres this is fine -- round trips are sub-millisecond, and the
row-by-row form is easy to read and easy to reason about.

Running against a managed database made the hidden assumption visible. Measured round
trip to Neon `us-east-2` was **298 ms**. At that latency:

- replaying one day of bronze (7,922 records) would take about **3.3 hours**
- an ordinary 25-SKU tier-1 refresh would take about **an hour**

The design was not wrong, but it had quietly assumed the database was local. Any
deployment where it is not -- managed Postgres, a different region, a VPN -- made
routine ingestion unusable.

## Decision

Add `ingestion/bulk.py` with `apply_records_bulk`, which applies an entire batch in a
**fixed, small number of round trips regardless of batch size**, by staging the records
in a temp table and expressing the CDC rules as SQL:

- records load in one statement via `unnest` of per-column arrays
- every monthly partition the batch needs is created in a single `DO` block
- products and retailers upsert as grouped set operations
- SCD2 change detection is a join between "latest incoming attributes" and the currently
  open version
- **insert-on-change is a window function** (`lag`) over the union of existing history
  and incoming rows, so each candidate is compared against the observation that
  *precedes it in time* -- preserving correct handling of backfilled and late-arriving
  data, which a "compare against the newest row" shortcut would break

The row-by-row path is kept. It is the readable reference implementation, it is what the
parity test checks against, and it remains appropriate for single-record work.

## Consequences

- Replaying a day went from an estimated 3.3 hours to **41 seconds** -- roughly 290x.
- Correctness is not taken on trust. `tests/integration/test_bulk_matches_rowwise.py`
  runs both paths over the same dataset and asserts the resulting price events and
  product versions are identical, covering the cases most likely to diverge:
  unchanged-within-heartbeat, unchanged-beyond-heartbeat, genuine change, exact
  duplicate, two retailers on one day, and out-of-order arrival. Each path runs in a
  transaction that is rolled back, so the test leaves no trace.
- Two real bugs surfaced while building this, both invisible at row-by-row scale:
  - `ON CONFLICT` rejects a command that proposes the same conflict key twice, so
    retailers must be de-duplicated with `GROUP BY` rather than `SELECT DISTINCT` --
    one retailer name legitimately arrives with differing country values.
  - Batch statistics cannot be accumulated per record; they are derived by counting rows
    before and after.
- Cost: the CDC rules now exist in two places and must be kept in step. The parity test
  is what makes that safe, and it fails loudly if they drift.
- This also pays off locally: fewer statements is faster everywhere, and it is what
  makes ingesting thousands of SKUs realistic rather than theoretical.
