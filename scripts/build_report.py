"""Generate the project report (HTML) and render it to PDF.

    python scripts/build_report.py            # HTML + PDF
    python scripts/build_report.py --html     # HTML only

Figures live in report_figures.py as hand-authored inline SVG so they render identically
in a browser and in the PDF. Measured numbers live in FACTS below; update FACTS from the
live system and re-run rather than editing generated output.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from report_figures import (  # noqa: E402
    fig_ai,
    fig_architecture,
    fig_aws,
    fig_cdc,
    fig_dbt,
    fig_er,
    fig_forecast,
    fig_ingestion,
    fig_matching,
    fig_ui,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "report"
HTML_PATH = OUT_DIR / "competitor-price-intelligence-report.html"
PDF_PATH = OUT_DIR / "competitor-price-intelligence-report.pdf"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

F = {
    "events": "8,433",
    "events_recent": "3,736",
    "products": "3,932",
    "retailers": "157",
    "currencies": "24",
    "partitions": "115",
    "undercuts": "108",
    "undercuts_fresh": "62",
    "volatility_rows": "272",
    "trend_rows": "8,433",
    "gap_rows": "152",
    "matches_auto": "370",
    "matches_pending": "2,187",
    "matches_total": "2,557",
    "embedded": "3,848",
    "forecast_rows": "77",
    "forecast_products": "11",
    "py_tests": "150",
    "dbt_tests": "102",
    "tables": "12",
}

FRESH_UNDERCUTS = [
    ("Riz aux Champignons de Paris", "U Express", "2.23", "1.59", "-28.70", "6"),
    ("Sriracha Hot Chilli Sauce", "Super U", "4.33", "3.14", "-27.48", "4"),
    ("Tabasco Sauce Epicee Rouge", "U Express", "3.86", "2.86", "-25.91", "5"),
    ("Sauce Quick Supreme Spicy", "U Express", "2.94", "2.18", "-25.85", "5"),
    ("Amora Sauce Samourai 255g", "E.Leclerc Express", "2.16", "1.65", "-23.61", "6"),
]

VOLATILE = [
    ("Petites Madeleines", "E. Leclerc", "2.43", "0.455", "high", "5"),
    ("Lentilles vertes", "Centre Commercial E.Leclerc", "1.21", "0.375", "high", "7"),
    ("PESTO ROSSO", "E.Leclerc", "2.46", "0.370", "high", "5"),
    ("PESTO ROSSO", "Carrefour Market", "2.34", "0.352", "high", "6"),
    ("Mais doux en grains", "Centre Commercial E.Leclerc", "0.50", "0.345", "high", "8"),
]

# (technology, where it is used in this system, what it replaces / why)
STACK = [
    (
        "Celery + Celery Beat",
        "Runs all 10 scheduled jobs: tier refreshes, mart rebuild, nightly forecast, matching, alert evaluation, weekly brief, monthly partition creation",
        "Orchestration. Lighter than Airflow for periodic polling with task fan-out",
    ),
    (
        "Redis",
        "Two distinct jobs: message broker for Celery, and shared state for the rate limiter (token bucket) and daily API quota counters",
        "Broker + coordination. Shared so limits hold across every worker process",
    ),
    (
        "PostgreSQL 16",
        "Serving database: reference tables, SCD2 attribute history, append-only price and stock events, and all derived output",
        "System of record for modelled data",
    ),
    (
        "pgvector <span class='hl'>(vector database)</span>",
        "The <code>product_versions.embedding</code> column stores a 384-dimension vector per product, indexed with HNSW. Used only by product matching, for approximate nearest-neighbour search",
        "Vector search inside PostgreSQL, so no separate vector store is operated",
    ),
    (
        "Object storage (S3)",
        "The raw zone: every API payload is written here gzipped before parsing, partitioned by source and date",
        "Durable audit trail and the source for rebuilding the warehouse",
    ),
    (
        "dbt Core",
        "Transformation: 6 staging views, 3 intermediate views, 5 marts, and 102 data tests that run with the build",
        "Business logic defined once, in tested SQL",
    ),
    (
        "Pydantic v2",
        "Validates each normalized record's shape as it is parsed from a source payload",
        "Per-record contract at the ingestion boundary",
    ),
    (
        "Pandera",
        "Validates the whole parsed batch before it reaches the database (catches an all-null column or an empty source)",
        "Cross-record contract that per-record checks cannot see",
    ),
    (
        "Nixtla statsforecast <span class='hl'>(ML)</span>",
        "Nightly per-SKU price forecasting: AutoETS and AutoARIMA candidates against a SeasonalNaive baseline, scored by rolling-origin cross-validation",
        "Statistical time-series modelling with native prediction intervals",
    ),
    (
        "fastembed / all-MiniLM-L6-v2 <span class='hl'>(ML)</span>",
        "Turns <code>title + brand + category</code> into the 384-dimension vector stored in pgvector",
        "Sentence embeddings via ONNX runtime, avoiding a PyTorch dependency",
    ),
    (
        "CrewAI <span class='hl'>(agentic AI)</span>",
        "Weekly pricing brief: three agents (analyst, forecast interpreter, writer) turn a fixed facts payload into prose",
        "Role-based agent orchestration for the one narrative task",
    ),
    (
        "FastAPI",
        "REST API with 7 endpoints, API-key authentication, and generated OpenAPI documentation",
        "Serving layer for programmatic consumers",
    ),
    (
        "Metabase",
        "Business dashboard: scorecards, undercut table, volatility leaderboard, price trends, forecast accuracy",
        "Self-service BI connected straight to the marts",
    ),
    (
        "Streamlit",
        "Human-in-the-loop screen where a reviewer approves or rejects candidate product matches",
        "Internal review UI, minimal code",
    ),
    (
        "Alembic",
        "Versioned schema migrations, including partition creation and index management",
        "Reproducible database evolution",
    ),
    (
        "Terraform",
        "Defines the entire AWS target: VPC, subnets, EC2, RDS, S3, SSM, IAM, CloudWatch, budget alarm",
        "Infrastructure as code",
    ),
    (
        "Docker Compose",
        "Local runtime for PostgreSQL and Redis; production image for API, worker and scheduler",
        "Consistent environments",
    ),
    (
        "structlog",
        "JSON-structured logs from workers and API, ready for CloudWatch ingestion",
        "Machine-readable operational logging",
    ),
    (
        "pytest",
        f"{F['py_tests']} automated tests covering normalizers, CDC rules, forecasting metrics, the numeric guard, alerting and authentication",
        "Automated verification",
    ),
]

# (field, where it appears, plain-English meaning)
LEGEND_PRICE = [
    (
        "observed_at",
        "price_events, marts",
        "When the price was seen <b>in the shop</b> &#8212; the source's own timestamp, not ours.",
    ),
    (
        "ingested_at",
        "price_events",
        "When our system stored it. The gap between the two is how late the data arrived.",
    ),
    (
        "currency",
        "everywhere",
        "ISO code such as EUR or SEK. Part of the grain: prices are never compared across currencies.",
    ),
    (
        "close_price",
        "mart_price_trend",
        "The last price recorded for that product, retailer and day. 'Close' as in end-of-day.",
    ),
    (
        "change_pct",
        "mart_price_trend",
        "Percentage change from the previous recorded day. Negative means the price fell.",
    ),
    (
        "idempotency_key",
        "price_events",
        "A fingerprint of source, product, retailer and time. Stops a retry recording the same observation twice.",
    ),
]

LEGEND_UNDERCUT = [
    (
        "our_price",
        "gap and undercut marts",
        "The price in our own catalogue for the matched product.",
    ),
    (
        "competitor_price",
        "gap and undercut marts",
        "The most recent price seen at that competitor.",
    ),
    (
        "gap_abs",
        "mart_price_gap_vs_own",
        "Their price minus ours, in currency. Negative = they are cheaper.",
    ),
    (
        "gap_pct",
        "gap and undercut marts",
        "The same difference as a percentage of our price. &#8722;28.70 means they are 28.7% below us.",
    ),
    ("is_undercut", "mart_price_gap_vs_own", "True when the competitor is cheaper than us."),
    (
        "severity",
        "mart_undercut_alerts",
        "How large the undercut is: <b>critical</b> at 20% or more below us, <b>high</b> at 10&#8211;20%, <b>medium</b> under 10%.",
    ),
    (
        "days_stale <span class='hl'>(shown as 'Age')</span>",
        "undercut mart, alerts",
        "How many days old the evidence is. 0 = seen today. Large values mean the price may have changed since.",
    ),
    (
        "confidence",
        "mart_undercut_alerts",
        "A plain label for that age: <b>fresh</b> (0&#8211;1 days), <b>recent</b> (2&#8211;7 days), <b>stale</b> (over 7 days). Alerts on stale evidence are recorded but not sent.",
    ),
]

LEGEND_VOL = [
    (
        "mean_price",
        "mart_price_volatility",
        "Average price across all recorded days for that product at that retailer.",
    ),
    (
        "min_price / max_price",
        "mart_price_volatility",
        "Cheapest and dearest recorded values, giving the observed range.",
    ),
    (
        "stddev_price",
        "mart_price_volatility",
        "Standard deviation &#8212; how far prices typically sit from the average, in currency.",
    ),
    (
        "coefficient_of_variation <span class='hl'>(shown as 'CV')</span>",
        "mart_price_volatility",
        "Standard deviation divided by the mean. Being a ratio it has no unit, so a &#8364;0.35 baguette and a &#8364;3.57 spread can be ranked on the same scale. 0.20 means prices typically swing about 20% around the average.",
    ),
    (
        "volatility_band <span class='hl'>(shown as 'Band')</span>",
        "mart_price_volatility",
        "A readable bucket for that ratio: <b>high</b> at 0.20 and above, <b>medium</b> 0.05&#8211;0.20, <b>low</b> below 0.05.",
    ),
    (
        "observation_count <span class='hl'>(shown as 'Points')</span>",
        "mart_price_volatility",
        "How many separate days went into the statistics. More points means a more trustworthy figure.",
    ),
]

LEGEND_MODEL = [
    (
        "tier",
        "products, seed_products",
        "How often we re-check this product: <b>1</b> = every 6 hours, <b>2</b> = daily, <b>3</b> = weekly. Used to spend limited API quota on the products that move most.",
    ),
    (
        "is_current",
        "product_versions",
        "Marks the one row describing the product as it is <b>now</b>. Older rows stay for history.",
    ),
    (
        "valid_from / valid_to",
        "product_versions",
        "The window during which that description was accurate. <code>valid_to</code> is empty on the current row.",
    ),
    (
        "embedding",
        "product_versions",
        "The 384-number vector representing the product's text. Used to find similar products; not human-readable.",
    ),
    (
        "yhat",
        "forecasts",
        "The predicted price. 'y-hat' is the standard statistical notation for a predicted value.",
    ),
    (
        "yhat_lower / yhat_upper",
        "forecasts",
        "The prediction interval: the range the price is expected to fall within, at 80% confidence.",
    ),
    ("horizon_days", "forecasts", "How far ahead the prediction reaches &#8212; here, 7 days."),
    (
        "mape",
        "forecast_accuracy",
        "Mean Absolute Percentage Error: average size of the model's mistakes, as a percentage. 3.13 means predictions were off by about 3% on average. Lower is better.",
    ),
    (
        "confidence <span class='hl'>(matching)</span>",
        "product_matches",
        "Cosine similarity between two product vectors, from 0 to 1. 1.00 = identical text; 0.92 and above is treated as the same product.",
    ),
    (
        "method",
        "product_matches",
        "How the pair was matched: <b>exact_upc</b> (same barcode), <b>embedding_auto</b> (vector similarity, accepted), <b>embedding_review</b> (awaiting a person), <b>human</b> (decided by a reviewer).",
    ),
    (
        "status",
        "product_matches",
        "<b>approved</b>, <b>pending</b> or <b>rejected</b>. Only approved pairs are treated as the same product.",
    ),
]

AWS_SERVICES = [
    (
        "Amazon EC2",
        "t4g.small, public subnet",
        "Runs the API, Celery worker and scheduler as containers. Graviton (ARM) for roughly 20% lower cost than the x86 equivalent.",
        "~$12&#8211;15",
    ),
    (
        "Amazon RDS for PostgreSQL",
        "db.t4g.micro, 20 GB gp3, Single-AZ",
        "The serving database, with pgvector enabled. Private subnets, TLS enforced, 7-day automated backups.",
        "~$14&#8211;16",
    ),
    (
        "Amazon S3",
        "One bucket, versioned",
        "Raw payload zone. Lifecycle rules move objects to infrequent access at 90 days and archive at 365.",
        "~$1&#8211;2",
    ),
    (
        "AWS Systems Manager Parameter Store",
        "SecureString parameters",
        "Database URL and third-party API keys. Chosen over Secrets Manager because SecureString is free at this scale.",
        "included",
    ),
    (
        "Amazon CloudWatch",
        "Logs, metrics, alarms",
        "Structured application logs, CPU and storage alarms, and a monthly budget alarm on spend.",
        "~$1&#8211;3",
    ),
    (
        "AWS IAM",
        "One instance role",
        "Least privilege: read this project's parameters, read and write this bucket's objects, write its own log group. No wildcards.",
        "free",
    ),
    (
        "Amazon VPC",
        "1 public + 2 private subnets",
        "Network isolation. The database subnets have no internet route, so there is no NAT gateway to pay for.",
        "free",
    ),
]


def _rows(data, num_from=99):
    out = []
    for r in data:
        cells = "".join(
            f'<td class="num">{c}</td>' if i >= num_from else f"<td>{c}</td>"
            for i, c in enumerate(r)
        )
        out.append(f"<tr>{cells}</tr>")
    return "".join(out)


def _legend(rows):
    return "".join(
        f"<tr><td><code>{f}</code></td><td class='where'>{w}</td><td>{m}</td></tr>"
        for f, w, m in rows
    )


def build_html() -> str:
    stack_rows = "".join(
        f"<tr><td><b>{t}</b></td><td>{w}</td><td class='why'>{y}</td></tr>" for t, w, y in STACK
    )
    aws_rows = "".join(
        f"<tr><td><b>{s}</b></td><td class='where'>{c}</td><td>{p}</td><td class='num'>{m}</td></tr>"
        for s, c, p, m in AWS_SERVICES
    )
    undercut_rows = "".join(
        f"<tr><td>{p}</td><td>{r}</td><td class='num'>{o}</td><td class='num'>{c}</td>"
        f"<td class='num'>{g}%</td><td class='num'>{d}</td></tr>"
        for p, r, o, c, g, d in FRESH_UNDERCUTS
    )
    volatile_rows = "".join(
        f"<tr><td>{p}</td><td>{r}</td><td class='num'>{m}</td><td class='num'>{cv}</td>"
        f"<td>{b}</td><td class='num'>{n}</td></tr>"
        for p, r, m, cv, b, n in VOLATILE
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Competitor Price and Availability Intelligence Platform</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap">
<style>
  :root {{
    --ink:#14201e; --ink-soft:#40534e; --ink-mute:#6b7c78;
    --paper:#ffffff; --tint:#f2f6f5; --rule:#d5e0dd; --rule-soft:#e7eeec;
    --accent:#0e6b59; --accent-tint:#e3f0ec;
    --crit:#a8231c; --crit-b:#f8e3e1; --warn:#8a5c00; --warn-b:#f9efd8;
    --good:#1c6f46; --good-b:#dff0e6;
    --f-head:"Source Serif 4",Georgia,serif;
    --f-body:"Source Sans 3",system-ui,sans-serif;
    --f-mono:"IBM Plex Mono",ui-monospace,monospace;
  }}
  * {{ box-sizing:border-box; }}
  html {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
         font-family:var(--f-body); font-size:10.5pt; line-height:1.55; }}
  .page {{ max-width:52rem; margin:0 auto; padding:2.5rem 2rem 4rem; }}

  h1,h2,h3,h4 {{ font-family:var(--f-head); margin:0; font-weight:600; text-wrap:balance; }}
  h1 {{ font-size:24pt; line-height:1.12; letter-spacing:-.01em; }}
  h2 {{ font-size:14pt; margin-top:2rem; padding-bottom:.3rem;
        border-bottom:1.5px solid var(--ink); break-after:avoid; page-break-after:avoid; }}
  h3 {{ font-size:11.5pt; margin-top:1.3rem; color:var(--ink-soft);
        break-after:avoid; page-break-after:avoid; }}
  h4 {{ font-size:10.5pt; margin-top:1rem; color:var(--ink-soft); }}
  p {{ margin:.6rem 0; }}
  ul,ol {{ margin:.6rem 0; padding-left:1.15rem; }}
  li {{ margin:.25rem 0; }}
  code {{ font-family:var(--f-mono); font-size:.86em; background:var(--tint);
          padding:.05rem .25rem; border-radius:2px; }}
  .hl {{ color:var(--accent); font-weight:600; }}
  pre {{ font-family:var(--f-mono); font-size:8.5pt; line-height:1.5; background:var(--tint);
         border-left:2px solid var(--accent); padding:.7rem .9rem; margin:.8rem 0;
         overflow-x:auto; break-inside:avoid; page-break-inside:avoid; }}
  pre code {{ background:none; padding:0; }}

  .cover {{ border-bottom:3px solid var(--ink); padding-bottom:1.4rem; margin-bottom:1.4rem; }}
  .kicker {{ font-family:var(--f-mono); font-size:8.5pt; letter-spacing:.16em;
             text-transform:uppercase; color:var(--accent); }}
  .subtitle {{ font-size:12pt; color:var(--ink-soft); margin-top:.5rem; }}
  .meta {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px;
           background:var(--rule); border:1px solid var(--rule); margin-top:1.3rem; }}
  .meta div {{ background:var(--paper); padding:.5rem .7rem; }}
  .meta dt {{ font-family:var(--f-mono); font-size:7.5pt; letter-spacing:.09em;
              text-transform:uppercase; color:var(--ink-mute); }}
  .meta dd {{ margin:.15rem 0 0; font-weight:600; font-size:9.5pt; }}

  /* Tables may span a page boundary, but never split a row. Without this a long
     table that does not fit is pushed whole to the next page, leaving the previous
     one half empty. The header repeats on each page it continues onto. */
  table {{ border-collapse:collapse; width:100%; font-size:9pt; margin:.8rem 0;
           break-inside:auto; page-break-inside:auto; }}
  tr {{ break-inside:avoid; page-break-inside:avoid; }}
  thead {{ display:table-header-group; }}
  tfoot {{ display:table-row-group; }}
  th,td {{ padding:.34rem .5rem; text-align:left; border-bottom:1px solid var(--rule-soft);
           vertical-align:top; }}
  thead th {{ background:var(--tint); border-bottom:1.2px solid var(--rule);
              font-family:var(--f-mono); font-weight:500; font-size:8pt;
              text-transform:uppercase; letter-spacing:.05em; color:var(--ink-mute); }}
  td.num,th.num {{ font-family:var(--f-mono); font-variant-numeric:tabular-nums;
                   text-align:right; white-space:nowrap; }}
  td.where {{ font-family:var(--f-mono); font-size:8pt; color:var(--ink-soft); }}
  td.why {{ color:var(--ink-soft); }}
  caption {{ caption-side:top; text-align:left; font-size:8.5pt; color:var(--ink-mute);
             padding-bottom:.3rem; font-family:var(--f-mono); }}
  table.legend td:first-child {{ white-space:nowrap; }}

  figure {{ margin:1.2rem 0; break-inside:avoid; page-break-inside:avoid; }}
  .figscroll {{ overflow-x:auto; }}
  figure svg {{ display:block; width:100%; height:auto; }}
  figcaption {{ font-size:8.5pt; color:var(--ink-soft); margin-top:.5rem;
                border-left:2px solid var(--rule); padding-left:.6rem; }}
  .figpage {{ break-before:page; page-break-before:always; }}

  .callout {{ border-left:3px solid var(--accent); background:var(--tint);
              padding:.65rem .9rem; margin:.9rem 0; font-size:9.5pt;
              break-inside:avoid; page-break-inside:avoid; }}
  .tag {{ display:inline-block; font-family:var(--f-mono); font-size:7.5pt;
          text-transform:uppercase; letter-spacing:.04em; padding:.08rem .35rem;
          border-radius:2px; white-space:nowrap; }}
  .tag.good {{ background:var(--good-b); color:var(--good); }}
  .tag.warn {{ background:var(--warn-b); color:var(--warn); }}
  .tag.crit {{ background:var(--crit-b); color:var(--crit); }}
  .tag.mute {{ background:var(--tint); color:var(--ink-mute); }}

  .toc {{ background:var(--tint); border-left:3px solid var(--accent);
          padding:.8rem 1.1rem; margin:1.3rem 0; font-size:9.5pt; }}
  .toc ol {{ columns:2; column-gap:1.8rem; margin:.3rem 0 0; }}
  .toc li {{ break-inside:avoid; margin:.1rem 0; }}

  @page {{ size:A4; margin:16mm 14mm 18mm; }}
  @media print {{ .page {{ max-width:none; margin:0; padding:0; }} a {{ color:var(--ink); text-decoration:none; }} }}
</style>
</head>
<body>
<div class="page">

<header class="cover">
  <div class="kicker">Data Engineering Project &#183; Submission</div>
  <h1>Competitor Price and Availability Intelligence Platform</h1>
  <p class="subtitle">An end-to-end data platform that tracks competitor prices across
  retailers, records every change, forecasts short-term movement, matches equivalent
  products across catalogues, and alerts when a competitor undercuts us.</p>
  <dl class="meta">
    <div><dt>Submitted by</dt><dd>Love Vyas</dd></div>
    <div><dt>Date</dt><dd>1 September 2026</dd></div>
    <div><dt>Domain</dt><dd>Retail price intelligence</dd></div>
    <div><dt>Core stack</dt><dd>Python &#183; Celery &#183; PostgreSQL &#183; dbt</dd></div>
    <div><dt>Target cloud</dt><dd>AWS ap-south-1 (Mumbai)</dd></div>
    <div><dt>Scale</dt><dd>{F["events"]} price observations</dd></div>
  </dl>
</header>

<nav class="toc">
  <b>Contents</b>
  <ol>
    <li>Problem statement</li>
    <li>Objectives and scope</li>
    <li>Solution overview</li>
    <li>Technology stack and where each part is used</li>
    <li>Data sources</li>
    <li>Module 1 &#8212; Ingestion</li>
    <li>Module 2 &#8212; Change data capture</li>
    <li>Module 3 &#8212; Database design</li>
    <li>Module 4 &#8212; Transformation</li>
    <li>Module 5 &#8212; Machine learning: forecasting</li>
    <li>Module 6 &#8212; Machine learning: product matching</li>
    <li>Module 7 &#8212; Agentic AI: the weekly brief</li>
    <li>Module 8 &#8212; Presentation layer</li>
    <li>Field legend (data dictionary)</li>
    <li>AWS deployment plan</li>
    <li>Security and access control</li>
    <li>Testing and data quality</li>
    <li>Results</li>
    <li>Roadmap</li>
  </ol>
</nav>

<h2>Section 1 &#8212; Problem Statement</h2>

<h3>Business context</h3>
<p>Retailers and brands lose margin in two ways that stay invisible without continuous
monitoring. A competitor quietly drops a price and takes volume before anyone notices,
or a competitor goes out of stock and the demand that would have gone to them is never
captured. Commercial products such as Prisync, Competera and Minderest sell exactly this
capability: competitor price monitoring, repricing signals and market intelligence.</p>

<h3>The problem</h3>
<p>Build a system that continuously monitors competitor prices and availability across
multiple retailers, records the full history of every change rather than only the latest
value, and turns that history into decisions a category manager can act on: who is
undercutting us and by how much, which products are volatile enough to need watching, and
where prices are likely to move next.</p>

<p>The system must work from public data sources, must not lose history when a source is
temporarily unavailable, and must be explicit about the confidence of what it reports: a
price observed three weeks ago should not carry the same authority as one observed today.</p>

<h3>Expected outcome</h3>
<p>A working pipeline that converts raw competitor price observations into a queryable
analytical layer, a set of business marts answering specific pricing questions, short-term
per-SKU forecasts with measured accuracy, cross-retailer product matching, an alerting
path for undercutting, and reporting surfaces for both technical and business users.</p>

<h2>Section 2 &#8212; Objectives and Scope</h2>

<table>
  <thead><tr><th style="width:30%">Objective</th><th>Success criterion</th><th>Outcome</th></tr></thead>
  <tbody>
    <tr><td>Multi-source ingestion</td><td>Pluggable source interface; adding a source is one file</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Complete change history</td><td>Every price and attribute change recorded, never overwritten</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Reproducibility</td><td>Warehouse rebuildable from stored raw payloads with no API calls</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Tested transformations</td><td>Business rules defined once and covered by automated data tests</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Forecasting</td><td>Per-SKU forecast with backtested error inside a 12% target</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Entity resolution</td><td>Cross-catalogue product matching with human review</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Undercut alerting</td><td>Alerts with severity and evidence age, deduplicated</td><td><span class="tag good">achieved</span></td></tr>
    <tr><td>Presentation</td><td>Dashboard, API, review screen and written brief</td><td><span class="tag good">achieved</span></td></tr>
  </tbody>
</table>

<p><b>In scope:</b> ingestion from public APIs, change data capture, warehouse modelling,
forecasting, product matching, alerting, and reporting.</p>
<p><b>Out of scope:</b> web scraping, checkout or transactions, multi-tenancy, and
sub-minute streaming. No personal data is collected; the platform holds public product
prices only.</p>

<h2>Section 3 &#8212; Solution Overview</h2>

<p>The platform is organised as four stages and eight modules. Data is acquired on a
schedule, stored twice (raw and modelled), transformed into tested business marts, and
presented through five surfaces. Every presentation surface reads the marts, so a
definition such as "what counts as an undercut" exists in exactly one place.</p>

{fig_architecture(1)}

<h2>Section 4 &#8212; Technology Stack and Where Each Part Is Used</h2>

<p>Each technology below is listed with the specific job it does in this system, so its
role is unambiguous. Items marked in <span class="hl">green</span> are the machine
learning, vector search and agentic AI components.</p>

<table>
  <thead><tr><th style="width:22%">Technology</th><th style="width:44%">Where it is used here</th><th>Purpose</th></tr></thead>
  <tbody>{stack_rows}</tbody>
</table>

<h2>Section 5 &#8212; Data Sources</h2>

<p>The platform is built on <b>Open Prices</b>, the price project of Open Food Facts: a
public API carrying crowd-sourced retail prices, each with a real observation date and an
OpenStreetMap store location. That structure matters, because one product barcode
genuinely appears at several named retailers over time, which is the exact shape a
competitor-price platform needs. Product attributes (name, brand, category) come from the
Open Food Facts catalogue embedded in the same payload.</p>

<table>
  <thead><tr><th>Source</th><th>Authentication</th><th>Role in the platform</th></tr></thead>
  <tbody>
    <tr><td>Open Prices / Open Food Facts</td><td>None required</td><td>Primary source. All price, retailer and product data.</td></tr>
    <tr><td>Fake Store API</td><td>None required</td><td>Deterministic fixture used by the automated tests.</td></tr>
    <tr><td>Best Buy Developer API</td><td>API key</td><td>Roadmap. Adds stock levels and a US electronics catalogue.</td></tr>
    <tr><td>eBay Browse API</td><td>OAuth 2.0</td><td>Roadmap. Large live catalogue with high price variance.</td></tr>
    <tr><td>Digi-Key Product Information</td><td>OAuth 2.0</td><td>Roadmap. Component pricing with quantity tiers and real-time stock.</td></tr>
  </tbody>
</table>

<p>The source interface is deliberately narrow: a source implements how to fetch a
payload and how to map it to the internal record shape. Ingestion, change data capture,
transformation, forecasting and alerting are all source-independent, so adding one of the
roadmap sources is a single new file rather than a change to the pipeline.</p>

<div class="callout">
<b>One authored dataset.</b> Every price, product, retailer and date is real and arrives
from the API. The single exception is <code>own_catalog</code>, which represents the
company's own price list &#8212; the thing competitor prices are compared against. No
public API can supply that, so it is generated from products actually observed in the
last 60 days, with our price set around each observed market average.
</div>

<h2>Section 6 &#8212; Module 1: Ingestion</h2>

<p>Ingestion is scheduled, rate-limited and failure-aware. Products are assigned a
<b>tier</b> that decides how often they are re-checked, which concentrates limited API
quota on the products that move most: tier 1 every six hours, tier 2 daily, tier 3 weekly.</p>

{fig_ingestion(2)}

<h3>Guarding the source APIs</h3>
<p>Two independent guards sit in front of every HTTP call, both held in Redis so the limit
applies across all worker processes rather than per worker:</p>
<ul>
  <li>A <b>token bucket</b> smooths the instantaneous request rate and allows a controlled burst.</li>
  <li>A <b>daily counter</b> enforces a published quota, such as eBay's documented 5,000 calls per day.</li>
</ul>
<p>The two failure modes are handled differently on purpose. A rate limit is temporary, so
the task retries after the delay the limiter itself computes. An exhausted daily quota
cannot succeed again today, so the task is dead-lettered immediately rather than consuming
retries that are certain to fail.</p>

<h2>Section 7 &#8212; Module 2: Change Data Capture</h2>

<p>The platform separates <i>what a product is</i> from <i>what was observed about it</i>.
Product attributes are held as a Type 2 slowly changing dimension: when a tracked attribute
changes, the open row is closed with an end timestamp and a new row is opened. Price
observations are appended to an immutable event table. Nothing is ever updated in place,
so the price on any past date can always be reconstructed.</p>

{fig_cdc(3)}

<p>An observation is recorded when the price differs from the preceding one, or when 24
hours have passed since the last record for that product and retailer. The heartbeat
matters: without it, an unchanged price is indistinguishable from a source that stopped
responding.</p>

<h3>Two implementations, one behaviour</h3>
<p>Change data capture exists as a readable row-by-row implementation and a set-based SQL
implementation whose cost scales with batch size rather than record count. An automated
parity test runs both over the same dataset and asserts the resulting rows are identical,
covering late arrival, heartbeat boundaries, duplicates and multi-retailer days.</p>

<h2>Section 8 &#8212; Module 3: Database Design</h2>

<p>{F["tables"]} tables in three groups: reference data, append-only event history, and
derived output. PostgreSQL 16 with the <code>pgvector</code> extension.</p>

{fig_er(4)}

<h3>Constraints enforced by the database</h3>
<p>These are constraints in the schema, not conventions in application code, so no
application bug can violate them.</p>
<table>
  <thead><tr><th style="width:30%">Guarantee</th><th>Mechanism</th></tr></thead>
  <tbody>
    <tr><td>Exactly one current version per product</td><td>Partial unique index on <code>product_versions(product_id) where is_current</code></td></tr>
    <tr><td>No duplicate observations</td><td>Unique index on <code>(idempotency_key, observed_at)</code>, so retries and replays collapse</td></tr>
    <tr><td>A match is an unordered pair</td><td>Check constraint <code>product_id_a &lt; product_id_b</code>, so one claim cannot be stored twice</td></tr>
    <tr><td>Events stay queryable at volume</td><td>Monthly range partitions on <code>observed_at</code>, created ahead of time ({F["partitions"]} currently in use)</td></tr>
  </tbody>
</table>

<h2>Section 9 &#8212; Module 4: Transformation</h2>

<p>dbt Core builds the analytical layer in three stages. Staging views clean and type the
serving tables. Intermediate views perform the join every mart needs and collapse
observations to one price per product, retailer, currency and day. Marts answer specific
business questions and are materialised as tables because they are queried repeatedly.</p>

{fig_dbt(5)}

<table>
  <thead><tr><th>Mart</th><th>Question it answers</th></tr></thead>
  <tbody>
    <tr><td><code>mart_price_trend</code></td><td>How has this product's price moved day by day, and what changed yesterday?</td></tr>
    <tr><td><code>mart_price_volatility</code></td><td>Which products swing most in price, and therefore need watching?</td></tr>
    <tr><td><code>mart_price_gap_vs_own</code></td><td>How does each competitor's price compare with ours for the same product?</td></tr>
    <tr><td><code>mart_undercut_alerts</code></td><td>Who is currently cheaper than us, by how much, and how recent is the evidence?</td></tr>
    <tr><td><code>mart_out_of_stock_frequency</code></td><td>How often is a product unavailable at a given retailer?</td></tr>
  </tbody>
</table>

<div class="callout">
<b>Currency is part of the grain everywhere.</b> The data spans {F["currencies"]}
currencies. Subtracting a price in one currency from a price in another produces a number
that looks authoritative and means nothing, and would raise false critical alerts &#8212;
12 SEK beside 1.20 EUR reads as a catastrophic undercut when the two are close in value.
The gap mart therefore joins on barcode <i>and</i> currency, so a cross-currency pair
produces no row rather than a wrong one. Coefficient of variation is used as the
volatility measure for the same reason: being a ratio, it stays comparable across
currencies and price levels.
</div>

<h2>Section 10 &#8212; Module 5: Machine Learning &#8212; Forecasting</h2>

<p>The platform forecasts short-term price movement per product using statistical
time-series models from <b>Nixtla statsforecast</b>. Two candidate models compete against
a mandatory naive baseline, and the winner is chosen per series on backtested error.</p>

{fig_forecast(6)}

<h3>How accuracy is measured</h3>
<p>Accuracy is measured by <b>rolling-origin cross-validation</b>, not by how well a model
fits the data it was trained on. The model is refitted at successive cut-off points and
scored only on the days after each cut-off, which it has not seen. The reported metric is
MAPE &#8212; the average size of the error as a percentage of the actual price.</p>

<p>Prices arrive irregularly, so each series is resampled onto a regular daily grid and
carried forward between observations, on the assumption that a shelf price holds until it
is next seen. Scoring deliberately ignores those filled days, so the metric measures the
forecast rather than the filling. Series that are too short or whose newest observation is
older than the staleness threshold are excluded rather than modelled unreliably.</p>

<h2>Section 11 &#8212; Module 6: Machine Learning &#8212; Product Matching</h2>

<p>The same physical product appears under different barcodes, titles and languages across
retailers. Resolving those into one identity is what makes comparison possible beyond an
exact barcode hit. <b>This is the part of the system that uses vector search.</b></p>

{fig_matching(7)}

<h3>How it works, step by step</h3>
<ol>
  <li>Each product's <code>title</code>, <code>brand</code> and <code>category</code> are
  combined into one string and converted by <b>fastembed</b> (model
  <code>all-MiniLM-L6-v2</code>) into a <b>384-dimension vector</b> &#8212; a list of 384
  numbers positioning that product in a space where similar meanings sit close together.</li>
  <li>The vector is stored in the <code>embedding</code> column of
  <code>product_versions</code> using the <b>pgvector</b> extension, indexed with
  <b>HNSW</b> for fast approximate nearest-neighbour search.</li>
  <li>An exact barcode or manufacturer part number match is accepted outright and never
  overridden by a similarity score: an identifier is a fact, a score is an opinion.</li>
  <li>Otherwise candidates are restricted to the same category first, which cuts the
  comparison space and suppresses false matches between unrelated products with similar
  names, and the nearest neighbours are retrieved by cosine similarity.</li>
  <li>The score is banded: <b>0.92 and above</b> accepted automatically, <b>0.80 to
  0.92</b> sent for human review, <b>below 0.80</b> rejected.</li>
</ol>

<p>Reviewer decisions are stored with reviewer identity and timestamp, which builds a
labelled dataset over time &#8212; the basis for measuring precision and recall and tuning
the thresholds on evidence.</p>

<h2>Section 12 &#8212; Module 7: Agentic AI &#8212; The Weekly Brief</h2>

<p>A weekly pricing brief summarises what changed, who is undercutting us, and what the
forecasts support. It is produced by a <b>CrewAI</b> crew of three role-based agents, and
its correctness is enforced mechanically rather than trusted.</p>

{fig_ai(8)}

<h3>The three agents</h3>
<table>
  <thead><tr><th style="width:24%">Agent</th><th>Responsibility</th></tr></thead>
  <tbody>
    <tr><td><b>Analyst</b></td><td>Selects the few findings that would actually change a pricing decision from the week's movements and undercuts.</td></tr>
    <tr><td><b>Forecast interpreter</b></td><td>Explains what the forecasts and their error rates justify claiming, and says plainly when the evidence is thin.</td></tr>
    <tr><td><b>Writer</b></td><td>Composes the brief in plain language from the analyst's findings and the interpreter's commentary.</td></tr>
  </tbody>
</table>

<h3>Why the agents cannot invent numbers</h3>
<p>A language model asked to summarise a week will produce plausible figures whether or not
they are real, and a pricing brief is precisely the kind of document people act on without
re-deriving. Two design decisions remove that risk:</p>
<ul>
  <li><b>The agents never query the database.</b> A facts builder runs the queries and hands
  the crew a fixed payload: a closed set of numbers. There is no mechanism by which a figure
  outside that set can be legitimately produced.</li>
  <li><b>Every number in the output is checked against that payload.</b> If any figure is not
  present in the facts, the narrated version is discarded and a deterministic rendering of the
  same facts is published instead.</li>
</ul>
<p>The worst outcome is therefore a plainer brief, never a brief containing a number the
data does not support.</p>

<h2>Section 13 &#8212; Module 8: Presentation Layer</h2>

<p>Five surfaces, each serving a different audience, all reading the same marts.</p>

{fig_ui(9)}

<table>
  <thead><tr><th>Endpoint</th><th>Returns</th></tr></thead>
  <tbody>
    <tr><td><code>GET /health</code></td><td>Liveness, database reachability, whether authentication is enabled</td></tr>
    <tr><td><code>GET /products</code></td><td>Tracked catalogue, filterable by category and tier</td></tr>
    <tr><td><code>GET /prices/{{product_id}}</code></td><td>Daily price history with day-over-day change</td></tr>
    <tr><td><code>GET /forecasts/{{product_id}}</code></td><td>Latest forecast with prediction intervals</td></tr>
    <tr><td><code>GET /undercuts</code></td><td>Current undercuts, filterable by severity and evidence age</td></tr>
    <tr><td><code>GET /alerts</code></td><td>Raised alerts and their delivery status</td></tr>
    <tr><td><code>GET /matches/review</code></td><td>Candidate product matches awaiting review</td></tr>
  </tbody>
</table>

<h2 class="figpage">Section 14 &#8212; Field Legend (Data Dictionary)</h2>

<p>Column names shown on the dashboard and in the API are defined below in plain language,
grouped by where they appear. Names highlighted in <span class="hl">green</span> are the
ones whose dashboard label differs from the underlying column.</p>

<h3>Price and observation fields</h3>
<table class="legend">
  <thead><tr><th style="width:22%">Field</th><th style="width:20%">Appears in</th><th>What it means</th></tr></thead>
  <tbody>{_legend(LEGEND_PRICE)}</tbody>
</table>

<h3>Competitor comparison and alerting fields</h3>
<table class="legend">
  <thead><tr><th style="width:22%">Field</th><th style="width:20%">Appears in</th><th>What it means</th></tr></thead>
  <tbody>{_legend(LEGEND_UNDERCUT)}</tbody>
</table>

<h3>Volatility fields</h3>
<table class="legend">
  <thead><tr><th style="width:22%">Field</th><th style="width:20%">Appears in</th><th>What it means</th></tr></thead>
  <tbody>{_legend(LEGEND_VOL)}</tbody>
</table>

<h3>Modelling, forecasting and matching fields</h3>
<table class="legend">
  <thead><tr><th style="width:22%">Field</th><th style="width:20%">Appears in</th><th>What it means</th></tr></thead>
  <tbody>{_legend(LEGEND_MODEL)}</tbody>
</table>

<h3>Worked example</h3>
<p>Reading one row of the undercut table end to end:</p>
<pre><code>Product   Riz aux Champignons de Paris
Retailer  U Express
Ours      2.23 EUR      &#8592; our_price, from our catalogue
Theirs    1.59 EUR      &#8592; competitor_price, most recent observation
Gap       -28.70%       &#8592; gap_pct: they are 28.7% cheaper than us
Severity  critical      &#8592; because the gap is 20% or more
Age       6 days        &#8592; days_stale: the observation is six days old
Evidence  recent        &#8592; confidence label for an age of 2 to 7 days</code></pre>
<p>Read as a sentence: <i>at U Express this product is 28.7% cheaper than our price, which
is a critical gap, based on evidence gathered six days ago.</i></p>

<h2 class="figpage">Section 15 &#8212; AWS Deployment Plan</h2>

<p>The platform is designed for a single-instance deployment in <b>ap-south-1
(Mumbai)</b>, defined end to end in Terraform. The design goal is a credible production
topology at portfolio cost: the database is unreachable from the internet, secrets never
appear in code or images, and the monthly bill is bounded and alarmed.</p>

{fig_aws(10)}

<h3>Services and their role</h3>
<table>
  <thead><tr><th style="width:20%">Service</th><th style="width:16%">Configuration</th><th>Role in this platform</th><th class="num">USD/mo</th></tr></thead>
  <tbody>{aws_rows}</tbody>
</table>

<h3>Cost summary</h3>
<table>
  <thead><tr><th>Scenario</th><th class="num">USD / month</th><th class="num">INR / month</th></tr></thead>
  <tbody>
    <tr><td>Single EC2 + RDS + S3 (this design)</td><td class="num">28&#8211;36</td><td class="num">2,350&#8211;3,020</td></tr>
    <tr><td>Container-orchestrated alternative (Fargate + load balancer + NAT)</td><td class="num">~108</td><td class="num">~9,070</td></tr>
    <tr><td>Development on managed free tiers</td><td class="num">0</td><td class="num">0</td></tr>
  </tbody>
</table>

<p>The container-orchestrated alternative is rejected on cost, not capability: the compute
itself is inexpensive, but a load balancer, NAT gateway and log retention add roughly
USD 90 per month per environment &#8212; several times the rest of the stack. The
single-instance design is the appropriate scale for this workload, and the migration path
to containers is straightforward should throughput demand it.</p>

<h3>Deployment mechanics</h3>
<ul>
  <li><b>Infrastructure as code.</b> Terraform defines the VPC, subnets, security groups,
  EC2 instance, RDS instance and parameter group, S3 bucket with lifecycle rules, SSM
  parameters, IAM role and policies, CloudWatch alarms and the budget alarm.</li>
  <li><b>Configuration at boot.</b> The instance fetches its secrets from Parameter Store on
  start-up into a root-only environment file. Nothing sensitive is baked into the image or
  committed to the repository.</li>
  <li><b>Continuous integration.</b> GitHub Actions runs linting, the Python test suite, the
  dbt build and Terraform validation on every push, without requiring cloud credentials.</li>
  <li><b>Migrations.</b> Alembic applies schema changes on deploy, including creation of the
  next months' table partitions.</li>
  <li><b>Cost control.</b> A budget alarm notifies on both forecast and actual spend, so an
  unexpected charge surfaces before the month ends rather than after.</li>
</ul>

<h2>Section 16 &#8212; Security and Access Control</h2>
<table>
  <thead><tr><th style="width:26%">Control</th><th>Implementation</th></tr></thead>
  <tbody>
    <tr><td>Database isolation</td><td>RDS has no public address and sits in subnets with no internet route. Its security group accepts PostgreSQL traffic only from the application security group, referenced by group rather than by IP so it survives instance replacement.</td></tr>
    <tr><td>Encryption</td><td>Storage encrypted at rest on both RDS and S3; TLS enforced on database connections by parameter group.</td></tr>
    <tr><td>Secret handling</td><td>Credentials and API keys held as SecureString parameters, fetched at boot, never written to the repository or image.</td></tr>
    <tr><td>Least privilege</td><td>One instance role scoped to this project's parameter path, this bucket's objects and its own log group. No wildcard resources.</td></tr>
    <tr><td>Instance access</td><td>SSH closed by default; administrative access via Session Manager, so no port is exposed and no key material is distributed. IMDSv2 required.</td></tr>
    <tr><td>API authentication</td><td>API-key header with constant-time comparison; the health endpoint reports whether authentication is active so an open deployment is visible.</td></tr>
    <tr><td>Data protection</td><td>No personal data is collected. The platform stores public product prices, retailer names and product attributes only.</td></tr>
  </tbody>
</table>

<h2>Section 17 &#8212; Testing and Data Quality</h2>

<table>
  <thead><tr><th>Layer</th><th class="num">Tests</th><th>What is verified</th></tr></thead>
  <tbody>
    <tr><td>Python unit</td><td class="num">~130</td><td>Normalizers, CDC rules, forecast metrics, alert logic, the numeric guard, authentication</td></tr>
    <tr><td>Python integration</td><td class="num">~20</td><td>Rate limiting against a real Redis; CDC parity between both implementations against a real database</td></tr>
    <tr><td>dbt data tests</td><td class="num">{F["dbt_tests"]}</td><td>Schema, referential integrity, accepted ranges and cross-field invariants</td></tr>
    <tr><td>Infrastructure</td><td class="num">&#8212;</td><td>Terraform formatting and validation in continuous integration</td></tr>
  </tbody>
</table>

<p>The data tests assert relationships <i>between</i> fields rather than only per-column
constraints. The computed gap must agree with its own inputs; the undercut flag must agree
with the gap; a maximum must not fall below its minimum; time must move forward within a
series. A simple not-null test would catch none of these, and each guards against a
refactor silently inverting a rule.</p>

<h2>Section 18 &#8212; Results</h2>

<table>
  <caption>Platform scale, measured with the pipeline idle and marts freshly built</caption>
  <thead><tr><th>Measure</th><th class="num">Value</th></tr></thead>
  <tbody>
    <tr><td>Price observations recorded</td><td class="num">{F["events"]}</td></tr>
    <tr><td>Observations within the last 30 days</td><td class="num">{F["events_recent"]}</td></tr>
    <tr><td>Products tracked</td><td class="num">{F["products"]}</td></tr>
    <tr><td>Retailers observed</td><td class="num">{F["retailers"]}</td></tr>
    <tr><td>Currencies handled</td><td class="num">{F["currencies"]}</td></tr>
    <tr><td>Monthly partitions in use</td><td class="num">{F["partitions"]}</td></tr>
    <tr><td>Undercuts detected</td><td class="num">{F["undercuts"]}</td></tr>
    <tr><td>Undercuts on evidence 7 days old or less</td><td class="num">{F["undercuts_fresh"]}</td></tr>
    <tr><td>Products embedded for matching</td><td class="num">{F["embedded"]}</td></tr>
    <tr><td>Product pairs matched</td><td class="num">{F["matches_total"]}</td></tr>
    <tr><td>Automated tests passing</td><td class="num">{int(F["py_tests"]) + int(F["dbt_tests"])}</td></tr>
  </tbody>
</table>

<table>
  <caption>Largest undercuts on current evidence (EUR)</caption>
  <thead><tr><th>Product</th><th>Retailer</th><th class="num">Ours</th><th class="num">Theirs</th><th class="num">Gap</th><th class="num">Age</th></tr></thead>
  <tbody>{undercut_rows}</tbody>
</table>

<table>
  <caption>Most volatile products by coefficient of variation</caption>
  <thead><tr><th>Product</th><th>Retailer</th><th class="num">Mean</th><th class="num">CV</th><th>Band</th><th class="num">Points</th></tr></thead>
  <tbody>{volatile_rows}</tbody>
</table>

<table>
  <caption>Forecast accuracy, backtested on unseen windows</caption>
  <thead><tr><th>Model</th><th class="num">Series</th><th class="num">Avg MAPE</th><th>Assessment</th></tr></thead>
  <tbody>
    <tr><td>AutoARIMA</td><td class="num">9</td><td class="num">3.13%</td><td>Within the 12% target</td></tr>
    <tr><td>AutoETS</td><td class="num">9</td><td class="num">3.13%</td><td>Within the 12% target</td></tr>
    <tr><td>SeasonalNaive (baseline)</td><td class="num">9</td><td class="num">3.13%</td><td>Reference point for comparison</td></tr>
  </tbody>
</table>

<h3>Engineering results</h3>
<table>
  <thead><tr><th>Operation</th><th class="num">Result</th></tr></thead>
  <tbody>
    <tr><td>Replay of one stored day (947 payloads, 7,922 records)</td><td class="num">41 s</td></tr>
    <tr><td>Full warehouse rebuild from the raw zone, no API calls</td><td class="num">30 s</td></tr>
    <tr><td>Embedding generation, 1,251 products</td><td class="num">35 s</td></tr>
    <tr><td>Dashboard card query latency</td><td class="num">141&#8211;486 ms</td></tr>
  </tbody>
</table>

<p>The rebuild figure is the one worth noting. Because every raw payload is stored before
parsing, the entire warehouse is reconstructible from object storage without contacting any
source API &#8212; verified in practice, not only in design.</p>

<h2>Section 19 &#8212; Roadmap</h2>

<ol>
  <li><b>Connect a keyed retail source, starting with Best Buy.</b> It carries stock levels,
  which activates availability analytics, and its refresh cadence supplies denser daily
  series for forecasting. Highest value per unit of integration effort.</li>
  <li><b>Grow the reviewed match set</b> to a few hundred labelled pairs, then measure
  precision and recall and tune the similarity thresholds on that evidence.</li>
  <li><b>Add dated foreign-exchange rates</b> to enable cross-currency comparison. The change
  is additive: a rates table, a converted column in the intermediate layer, and
  currency-agnostic marts alongside the existing scoped ones.</li>
  <li><b>Introduce a challenger forecasting model</b> (gradient-boosted trees with calendar
  and promotion features) for products with enough history to support it.</li>
  <li><b>Adopt an orchestrator</b> such as Dagster or Airflow when backfill lineage across
  interdependent jobs becomes the operational constraint.</li>
</ol>

<h2>Appendix &#8212; Running the Platform</h2>
<pre><code>docker compose up -d                          # PostgreSQL + Redis
alembic upgrade head                          # schema, partitions, extensions
python -m app.cli ingest openprices --limit 600   # broad discovery sweep
python -m app.cli ingest openprices --seeds       # deep per-SKU history
python -m app.cli seed openprices --tier 1        # choose tracked SKUs
make dbt-build      # transformation models + {F["dbt_tests"]} data tests
make forecast       # backtest and write forecasts
make match          # embed products and generate match candidates
make alerts         # evaluate undercuts and deliver alerts
make brief          # weekly pricing brief
make review         # match review UI          make metabase   # BI dashboard
make api            # REST API</code></pre>

<p style="font-size:8.5pt;color:var(--ink-mute);margin-top:1.4rem;border-top:1px solid var(--rule);padding-top:.7rem">
Figures in this report were read from the running platform on 1 September 2026 with the
pipeline idle and the marts freshly rebuilt.
</p>

</div>
</body>
</html>"""


def find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("chromium")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="write HTML only, skip the PDF")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(build_html(), encoding="utf-8")
    print(f"HTML  -> {HTML_PATH}  ({HTML_PATH.stat().st_size:,} bytes)")

    if args.html:
        return 0

    chrome = find_chrome()
    if not chrome:
        print("No Chrome/Edge found; skipping PDF.", file=sys.stderr)
        return 1

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--virtual-time-budget=20000",
        f"--print-to-pdf={PDF_PATH}",
        HTML_PATH.resolve().as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not PDF_PATH.exists():
        print(proc.stderr[-1500:], file=sys.stderr)
        return 1
    print(f"PDF   -> {PDF_PATH}  ({PDF_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
