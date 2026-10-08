# ADR-008: Never compare prices across currencies

**Status:** Accepted

## Context

The warehouse holds prices in at least five currencies, because Open Prices is
crowd-sourced across countries:

| currency | events | products | retailers |
|---|---|---|---|
| EUR | 3,105 | 997 | 78 |
| SEK | 146 | 145 | 1 |
| USD | 97 | 97 | 2 |
| PLN | 33 | 32 | 2 |
| NOK | 22 | 22 | 2 |

This is easy to miss. A naive `min(price)` per product, or a price-gap mart that
subtracts our EUR price from a competitor's SEK price, produces a number that looks
authoritative, renders fine on a dashboard, and is meaningless. Worse, it would fire
undercut alerts: 12 SEK next to 1.20 EUR reads as a catastrophic undercut when the two
are roughly equal in value.

Converting is not a free fix. Correct conversion needs an FX rate *as of the observation
date*, which means a rate source, a rates table, and a policy for missing days. Prices
here span 2010 to 2026, so this is a real historical-FX problem, not a lookup.

## Decision

**Currency is a grain column everywhere, and every comparison is scoped to a single
currency.** No conversion is performed in v1.

- `stg_price_events` uppercases and always retains `currency`. It is never dropped.
- The daily/latest grain is `(product_id, retailer_id, currency, date)`, enforced by
  `unique_combination_of_columns` tests.
- `mart_price_volatility` groups by currency. Coefficient of variation is the headline
  metric precisely because it is unitless -- it stays comparable across currencies and
  across price levels, so a 0.35 EUR baguette can be ranked against a 3.57 EUR spread.
- `mart_price_gap_vs_own` joins `own_catalog` on **both** UPC and currency. A
  cross-currency pair produces no row at all, rather than a wrong one.

## Consequences

- Every number a mart emits is arithmetically meaningful. Comparisons are only ever
  within one currency.
- Coverage is reduced rather than falsified: a product sold in EUR and SEK yields two
  independent series instead of one merged (and wrong) one. Given EUR is 93% of events,
  little of substance is lost.
- Cross-currency questions ("cheapest across all of Europe") cannot be answered yet.
  That is the correct outcome -- they cannot be answered *correctly* without dated FX.
- The upgrade path is additive: add an `fx_rates` table keyed by `(currency, date)`, a
  `price_in_base_currency` column in the intermediate layer, and currency-agnostic marts
  alongside the scoped ones. No existing model needs rewriting.
- Related decision: matching in `mart_price_gap_vs_own` is on UPC only, never on product
  name. Fuzzy matching is handled separately with embeddings and human review, where a
  confidence score and an audit trail make it defensible.
