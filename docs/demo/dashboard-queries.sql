-- Metabase dashboard cards.
--
-- VERIFIED 2026-09-01: Metabase v0.63.15.7 connected to this database, all cards below
-- executed and rendered. Measured run times: scorecard 486ms, undercuts 212ms,
-- volatility 309ms, forecast accuracy 217ms, matching 141ms, price trend 3.5s.
-- The scorecard returned 1,448 / 96 / 3,561 / 62, matching docs/demo/metrics.md exactly.
--
-- Connection settings that work (from `make metabase`):
--   Host: db      <- the compose service name, NOT localhost. Metabase connects from
--                    inside the Docker network, where localhost is its own container.
--   Port: 5432 · Database: cpi · User: cpi · Password: see .env
--
-- JVM note: cap the heap only (-Xmx512m). Capping metaspace kills Metabase during boot
-- with OutOfMemoryError: Metaspace -- it is Clojure and loads a lot of classes.
--
-- Start Metabase with `make metabase` (opt-in: it is a JVM holding ~1GB), connect it to
-- the `cpi` database, then paste each query as a native question. Every card reads a
-- dbt mart, so the definitions stay identical to the ones the API and alerts use.
--
-- Suggested layout: row 1 the four scorecards, row 2 undercuts + volatility,
-- row 3 the price trend, row 4 forecast accuracy.

-- ---------------------------------------------------------------------------
-- Card 1-4: scorecards
-- ---------------------------------------------------------------------------
-- Products tracked
select count(*) as products_tracked from products;

-- Retailers observed
select count(*) as retailers from retailers;

-- Active undercuts
select count(*) as active_undercuts from analytics_marts.mart_undercut_alerts;

-- Freshness: how recent is the newest observation
select max(observed_at)::date as latest_observation,
       current_date - max(observed_at)::date as days_since
from price_events;


-- ---------------------------------------------------------------------------
-- Card 5: undercut table (the headline card)
-- ---------------------------------------------------------------------------
-- `confidence` is shown deliberately: an undercut computed from three-week-old evidence
-- should not be read with the same weight as one from today.
select
    product_name          as "Product",
    retailer_name         as "Retailer",
    currency              as "Ccy",
    our_price             as "Ours",
    competitor_price      as "Theirs",
    gap_pct               as "Gap %",
    severity              as "Severity",
    confidence            as "Evidence",
    days_stale            as "Age (days)"
from analytics_marts.mart_undercut_alerts
order by gap_pct
limit 25;


-- ---------------------------------------------------------------------------
-- Card 6: volatility leaderboard
-- ---------------------------------------------------------------------------
-- Coefficient of variation rather than stddev: unitless, so it stays comparable across
-- price levels and across the 16 currencies in this data.
select
    title                    as "Product",
    retailer_name            as "Retailer",
    currency                 as "Ccy",
    mean_price               as "Mean",
    coefficient_of_variation as "CV",
    volatility_band          as "Band",
    observation_count        as "Points"
from analytics_marts.mart_price_volatility
where observation_count >= 5
order by coefficient_of_variation desc nulls last
limit 20;


-- ---------------------------------------------------------------------------
-- Card 7: price trend (line chart -- x: observed_date, y: close_price, series: retailer)
-- ---------------------------------------------------------------------------
-- Scoped to one currency: plotting EUR and SEK on one axis would be meaningless.
select
    observed_date  as "Date",
    retailer_name  as "Retailer",
    close_price    as "Price"
from analytics_marts.mart_price_trend
where currency = 'EUR'
  and product_id in (
      select product_id
      from analytics_marts.mart_price_trend
      group by product_id
      having count(*) >= 20
      order by count(*) desc
      limit 5
  )
order by observed_date;


-- ---------------------------------------------------------------------------
-- Card 8: forecast accuracy (bar chart -- x: model, y: avg_mape)
-- ---------------------------------------------------------------------------
-- SeasonalNaive is included on purpose. A champion that cannot beat "tomorrow looks like
-- today" is not earning its cost, and without the baseline on the chart you cannot tell.
select
    model                as "Model",
    count(*)             as "Series",
    round(avg(mape), 2)  as "Avg MAPE %",
    round(max(mape), 2)  as "Worst MAPE %"
from forecast_accuracy
where evaluated_at = (select max(evaluated_at) from forecast_accuracy)
group by model
order by avg(mape);


-- ---------------------------------------------------------------------------
-- Card 9: forecast vs history for one product (line chart with interval band)
-- ---------------------------------------------------------------------------
select
    observed_date        as "Date",
    close_price          as "Actual",
    null::numeric        as "Forecast",
    null::numeric        as "Lower",
    null::numeric        as "Upper"
from analytics_marts.mart_price_trend
where product_id = {{product_id}}
union all
select
    forecast_for, null, yhat, yhat_lower, yhat_upper
from forecasts
where product_id = {{product_id}}
  and trained_at = (select max(trained_at) from forecasts)
order by 1;


-- ---------------------------------------------------------------------------
-- Card 10: ingestion health
-- ---------------------------------------------------------------------------
select
    s.name                                        as "Source",
    count(*)                                      as "Runs",
    count(*) filter (where r.status = 'success')  as "Succeeded",
    count(*) filter (where r.status = 'failed')   as "Failed",
    max(r.started_at)                             as "Last run"
from ingestion_runs r
join sources s on s.source_id = r.source_id
group by s.name
order by max(r.started_at) desc;


-- ---------------------------------------------------------------------------
-- Card 11: match review queue
-- ---------------------------------------------------------------------------
select
    status                     as "Status",
    method                     as "Method",
    count(*)                   as "Pairs",
    round(min(confidence), 3)  as "Min similarity",
    round(max(confidence), 3)  as "Max similarity"
from product_matches
group by status, method
order by status, method;


-- ---------------------------------------------------------------------------
-- Card 12: out-of-stock frequency
-- ---------------------------------------------------------------------------
-- Returns zero rows today: neither keyless source publishes availability. Kept on the
-- dashboard because it starts working the moment Best Buy or Digi-Key is connected, and
-- an empty card that explains itself is better than a card that quietly disappears.
select
    external_id       as "Product",
    retailer_name     as "Retailer",
    days_observed     as "Days observed",
    days_out_of_stock as "Days OOS",
    out_of_stock_pct  as "OOS %"
from analytics_marts.mart_out_of_stock_frequency
order by out_of_stock_pct desc
limit 20;
