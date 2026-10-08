select count(*) as products_tracked from products;

select count(*) as retailers from retailers;

select count(*) as active_undercuts from analytics_marts.mart_undercut_alerts;

select max(observed_at)::date as latest_observation,
       current_date - max(observed_at)::date as days_since
from price_events;


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


select
    model                as "Model",
    count(*)             as "Series",
    round(avg(mape), 2)  as "Avg MAPE %",
    round(max(mape), 2)  as "Worst MAPE %"
from forecast_accuracy
where evaluated_at = (select max(evaluated_at) from forecast_accuracy)
group by model
order by avg(mape);


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


select
    status                     as "Status",
    method                     as "Method",
    count(*)                   as "Pairs",
    round(min(confidence), 3)  as "Min similarity",
    round(max(confidence), 3)  as "Max similarity"
from product_matches
group by status, method
order by status, method;


select
    external_id       as "Product",
    retailer_name     as "Retailer",
    days_observed     as "Days observed",
    days_out_of_stock as "Days OOS",
    out_of_stock_pct  as "OOS %"
from analytics_marts.mart_out_of_stock_frequency
order by out_of_stock_pct desc
limit 20;
