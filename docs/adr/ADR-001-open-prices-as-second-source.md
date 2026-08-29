# ADR-001: Open Prices as the keyless price source, seeded for depth

**Status:** Accepted

## Context
Phase 1 needed a keyless source that produces *real* price history. Two candidates:

- **Fake Store API** -- keyless, but payloads are static upstream. It exercises the code
  path and is ideal for tests, yet its prices never move, so it can never produce a
  change event or a forecastable series.
- **Open Food Facts** -- keyless and real, but the product API carries no prices.

**Open Prices** (the Open Food Facts price project) carries crowd-sourced observed
prices, each with an observation date and an OpenStreetMap store location. One barcode
genuinely appears at several retailers over time -- exactly the competitor-price shape
this platform models -- with no API key.

Two things had to be measured rather than assumed:

1. **Ordering.** The API's default order returns the earliest bulk import: 100 rows from
   one store on one day. `-created` returns 22 stores across 11 dates for the same page
   size. `-date` sorts NULLs first and yields rows with no date or currency.
2. **Breadth vs depth.** The broad feed gave 892 events but only *one* product with more
   than one observation -- useless for per-SKU forecasting. Querying the per-barcode
   endpoint for well-tracked products gave ~100 dated observations each.

## Decision
1. Use Open Prices as the keyless real-data source; keep Fake Store for tests and for
   verifying the pipeline without network variability.
2. Default `discover` to `order_by=-created`.
3. Add a **seed-driven deep path**: rank barcodes by upstream `price_count`, store them
   in `seed_products`, then fetch each one's full history. Result: 25 SKUs, 2,124 events,
   avg 85 observations each, 67 retailers, spanning 2010-2026.
4. Prefer the canonical `product.product_name` over the row-level one. The row-level
   field is contributor free text -- one barcode carried 25 spellings, which churned a
   new SCD2 version per observation (808 versions for 25 products). Using the canonical
   name gives exactly 25, with identical price history.

## Consequences
- Real, forecastable, multi-retailer history exists before any API key is approved.
- The broad/deep split maps onto the tiering the build doc already calls for: broad
  discovery is cheap and wide, seeded fetches are quota-hungry and reserved for tier 1.
- Open Prices carries **no availability data**, so `stock_events` stays empty until a
  source with real stock (Best Buy, Digi-Key) is connected. Availability-derived marts
  are therefore deferred, not faked.
- The data is grocery/EUR-weighted and European. Category mix will shift once the retail
  APIs land.
