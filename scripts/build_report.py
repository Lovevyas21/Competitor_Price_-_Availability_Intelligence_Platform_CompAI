"""Generate the project report (HTML) and render it to PDF.

The report is written as a project document answering a stated problem, not as a
handover note. Figures are hand-authored inline SVG so they survive both browser
viewing and PDF rendering -- mermaid renders only inside a published artifact.

    python scripts/build_report.py            # HTML + PDF
    python scripts/build_report.py --html     # HTML only

Numbers are passed in from FACTS below, which is filled from live queries. Update
FACTS and re-run rather than editing the HTML by hand.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

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

# --------------------------------------------------------------------------- #
# measured facts (from the running system)
# --------------------------------------------------------------------------- #
FACTS = {
    "events": "8,433",
    "events_recent": "3,736",
    "products": "3,932",
    "retailers": "157",
    "currencies": "24",
    "partitions": "115",
    "span": "2010-07-08 to 2026-09-01",
    "undercuts": "108",
    "undercuts_fresh": "62",
    "volatility_rows": "272",
    "trend_rows": "8,433",
    "gap_rows": "152",
    "matches_auto": "370",
    "matches_pending": "2,187",
    "forecast_rows": "77",
    "forecast_products": "11",
    "py_tests": "150",
    "dbt_tests": "102",
}

FRESH_UNDERCUTS = [
    ("Riz aux Champignons de Paris", "U Express", "2.23", "1.59", "-28.70", "6"),
    ("Sriracha Hot Chilli Sauce", "Super U", "4.33", "3.14", "-27.48", "4"),
    ("Tabasco Sauce Epicee Rouge", "U Express", "3.86", "2.86", "-25.91", "5"),
    ("Sauce Quick Supreme Spicy", "U Express", "2.94", "2.18", "-25.85", "5"),
    ("Amora Sauce Samourai 255g", "E.Leclerc Express", "2.16", "1.65", "-23.61", "6"),
    ("Amora", "U Express", "1.57", "1.20", "-23.57", "6"),
]

VOLATILE = [
    ("Petites Madeleines", "E. Leclerc", "2.43", "0.455", "high", "5"),
    ("Lentilles vertes", "Centre Commercial E.Leclerc", "1.21", "0.375", "high", "7"),
    ("PESTO ROSSO", "E.Leclerc", "2.46", "0.370", "high", "5"),
    ("PESTO ROSSO", "Carrefour Market", "2.34", "0.352", "high", "6"),
    ("Mais doux en grains", "Centre Commercial E.Leclerc", "0.50", "0.345", "high", "8"),
]

# --------------------------------------------------------------------------- #
# entity relationship diagram
# --------------------------------------------------------------------------- #
ENTITIES = {
    "SOURCES": (14, 96, [("source_id", "PK"), ("name", "UK"), ("auth_type", "")]),
    "RETAILERS": (
        14,
        260,
        [("retailer_id", "PK"), ("source_id", "FK"), ("name", ""), ("country", "")],
    ),
    "INGESTION_RUNS": (
        14,
        450,
        [("run_id", "PK"), ("source_id", "FK"), ("status", ""), ("records_ok", "")],
    ),
    "SEED_PRODUCTS": (
        14,
        640,
        [("seed_id", "PK"), ("source_name", ""), ("tier", ""), ("active", "")],
    ),
    "PRODUCTS": (
        300,
        150,
        [
            ("product_id", "PK"),
            ("source_id", "FK"),
            ("external_id", "UK"),
            ("upc", ""),
            ("tier", ""),
        ],
    ),
    "PRODUCT_VERSIONS": (
        300,
        420,
        [
            ("version_id", "PK"),
            ("product_id", "FK"),
            ("title", ""),
            ("embedding", ""),
            ("is_current", ""),
        ],
    ),
    "PRODUCT_MATCHES": (
        300,
        680,
        [
            ("match_id", "PK"),
            ("product_id_a", "FK"),
            ("product_id_b", "FK"),
            ("confidence", ""),
            ("status", ""),
        ],
    ),
    "PRICE_EVENTS": (
        620,
        60,
        [
            ("event_id", "PK"),
            ("product_id", "FK"),
            ("retailer_id", "FK"),
            ("price", ""),
            ("currency", ""),
            ("observed_at", "PK"),
        ],
    ),
    "STOCK_EVENTS": (
        620,
        300,
        [
            ("event_id", "PK"),
            ("product_id", "FK"),
            ("retailer_id", "FK"),
            ("in_stock", ""),
            ("observed_at", "PK"),
        ],
    ),
    "FORECASTS": (
        620,
        520,
        [("forecast_id", "PK"), ("product_id", "FK"), ("yhat", ""), ("forecast_for", "")],
    ),
    "FORECAST_ACCURACY": (
        620,
        690,
        [("id", "PK"), ("product_id", "FK"), ("model", ""), ("mape", "")],
    ),
    "ALERTS": (
        620,
        860,
        [("alert_id", "PK"), ("product_id", "FK"), ("severity", ""), ("sent_at", "")],
    ),
}
BW, TITLE_H, LINE_H = 232, 30, 22
ACCENT = "#0e6b59"


def _entity(name, x, y, fields):
    h = TITLE_H + len(fields) * LINE_H + 8
    hub = name == "PRODUCTS"
    col, sw = (ACCENT, "2") if hub else ("currentColor", "1.2")
    out = [
        f'<rect x="{x}" y="{y}" width="{BW}" height="{h}" rx="4" fill="none" stroke="{col}" stroke-width="{sw}"/>',
        f'<line x1="{x}" y1="{y + TITLE_H}" x2="{x + BW}" y2="{y + TITLE_H}" stroke="{col}" stroke-width="{sw}"/>',
        f'<text x="{x + 10}" y="{y + 20}" font-size="14" font-weight="600" fill="{col}">{name}</text>',
    ]
    for i, (f, m) in enumerate(fields):
        ty = y + TITLE_H + 17 + i * LINE_H
        out.append(f'<text x="{x + 10}" y="{ty}" font-size="13" opacity=".85">{f}</text>')
        if m:
            out.append(
                f'<text x="{x + BW - 10}" y="{ty}" font-size="11" text-anchor="end" opacity=".55">{m}</text>'
            )
    return "".join(out), h


def er_diagram() -> str:
    boxes, heights = [], {}
    for n, (x, y, f) in ENTITIES.items():
        svg, h = _entity(n, x, y, f)
        boxes.append(svg)
        heights[n] = h

    def cy(n):
        return ENTITIES[n][1] + heights[n] / 2

    def bot(n):
        return ENTITIES[n][1] + heights[n]

    e = []

    def seg(d, w="1.1", dash=""):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        e.append(
            f'<path d="{d}" fill="none" stroke="currentColor" stroke-width="{w}" opacity=".5"{da}/>'
        )

    def arrow(d, dash=""):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        e.append(
            f'<path d="{d}" fill="none" stroke="currentColor" stroke-width="1.1" opacity=".5"{da} marker-end="url(#er)"/>'
        )

    def label(x, y, t, anchor="start"):
        e.append(
            f'<text x="{x}" y="{y}" font-size="11" opacity=".6" text-anchor="{anchor}">{t}</text>'
        )

    # sources -> products / retailers / ingestion_runs
    arrow(f"M 246 {cy('SOURCES')} H 273 V {cy('PRODUCTS')} H 300")
    label(250, cy("SOURCES") - 7, "1:N")
    arrow(f"M 130 {bot('SOURCES')} V {ENTITIES['RETAILERS'][1]}")
    label(136, bot("SOURCES") + 34, "1:N")
    arrow(f"M 130 {bot('RETAILERS')} V {ENTITIES['INGESTION_RUNS'][1]}")
    label(136, bot("RETAILERS") + 34, "1:N")

    # products -> versions -> matches (vertical, same column)
    arrow(f"M 416 {bot('PRODUCTS')} V {ENTITIES['PRODUCT_VERSIONS'][1]}")
    label(422, bot("PRODUCTS") + 42, "1:N")
    arrow(f"M 416 {bot('PRODUCT_VERSIONS')} V {ENTITIES['PRODUCT_MATCHES'][1]}")
    label(422, bot("PRODUCT_VERSIONS") + 42, "1:N x2 (a, b)")

    # one bus carrying every product_id foreign key into the right-hand column
    BUS = 556
    targets = ["PRICE_EVENTS", "STOCK_EVENTS", "FORECASTS", "FORECAST_ACCURACY", "ALERTS"]
    top_y, bot_y = cy(targets[0]), cy(targets[-1])
    seg(f"M 532 {cy('PRODUCTS')} H {BUS}")
    seg(f"M {BUS} {top_y} V {bot_y}", w="1.4")
    for t in targets:
        arrow(f"M {BUS} {cy(t)} H 620")
    # Above the bus and left of the right-hand column, so it collides with neither.
    e.append(
        f'<text x="{BUS}" y="96" font-size="11" opacity=".6" text-anchor="middle">'
        f"product_id 1:N</text>"
    )

    # retailers also reference both event tables; routed in the gap below products
    RB = 590
    seg(f"M 246 {cy('RETAILERS')} H {RB}", dash="5 3")
    seg(f"M {RB} {cy('PRICE_EVENTS') + 26} V {cy('STOCK_EVENTS') + 26}", dash="5 3")
    arrow(f"M {RB} {cy('PRICE_EVENTS') + 26} H 620", dash="5 3")
    arrow(f"M {RB} {cy('STOCK_EVENTS') + 26} H 620", dash="5 3")
    label(300, cy("RETAILERS") - 7, "retailer_id  1:N (dashed)")

    return f"""<figure class="figpage">
<div class="figscroll">
<svg viewBox="0 0 900 1020" role="img" aria-label="Entity relationship diagram of twelve tables. SOURCES supplies PRODUCTS, RETAILERS and INGESTION_RUNS. PRODUCTS is the hub: it owns PRODUCT_VERSIONS which in turn relates to PRODUCT_MATCHES, and a single bus carries the product_id foreign key into PRICE_EVENTS, STOCK_EVENTS, FORECASTS, FORECAST_ACCURACY and ALERTS. RETAILERS is referenced by both event tables, shown dashed. SEED_PRODUCTS is standalone ingestion configuration.">
  <defs>
    <marker id="er" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" opacity=".5"/>
    </marker>
  </defs>
  <g font-family="IBM Plex Mono, monospace" fill="currentColor">
    <text x="14" y="34" font-size="12" opacity=".6">REFERENCE</text>
    <text x="300" y="34" font-size="12" opacity=".6">CORE AND HISTORY</text>
    <text x="620" y="34" font-size="12" opacity=".6">EVENTS AND DERIVED</text>
    <line x1="14" y1="44" x2="886" y2="44" stroke="currentColor" stroke-width=".7" opacity=".25"/>
    {"".join(e)}
    {"".join(boxes)}
    <text x="14" y="994" font-size="11" opacity=".6">PK primary key &#183; FK foreign key &#183; UK unique &#183; dashed = retailer_id foreign key</text>
    <text x="14" y="1010" font-size="11" opacity=".6">price_events and stock_events are range-partitioned by month, so observed_at forms part of their primary key</text>
  </g>
</svg>
</div>
<figcaption><b>Figure 3.</b> Database structure. <code>products</code> is the hub: every table in the right-hand column carries <code>product_id</code> as a foreign key, drawn here as a single bus rather than five crossing lines. The two event tables are append-only and partitioned; <code>product_versions</code> holds slowly-changing attribute history with exactly one open row per product.</figcaption>
</figure>"""


def system_map() -> str:
    return """<figure>
<div class="figscroll">
<svg viewBox="0 0 900 300" role="img" aria-label="Six stage pipeline: sources feed ingestion, which writes raw payloads to bronze storage and normalized rows to PostgreSQL. dbt builds marts from PostgreSQL, and forecasting, the API, alerts and the AI layer read those marts. Bronze can replay back into PostgreSQL without contacting the sources.">
  <defs>
    <marker id="a1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker>
    <marker id="a2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#0e6b59"/></marker>
  </defs>
  <g font-family="IBM Plex Mono, monospace" font-size="12" fill="currentColor">
    <rect x="10" y="60" width="122" height="54" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="71" y="83" text-anchor="middle" font-size="13">Sources</text>
    <text x="71" y="100" text-anchor="middle" font-size="11" opacity=".7">public APIs</text>
    <rect x="186" y="60" width="122" height="54" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="247" y="83" text-anchor="middle" font-size="13">Ingestion</text>
    <text x="247" y="100" text-anchor="middle" font-size="11" opacity=".7">Celery workers</text>
    <rect x="362" y="60" width="122" height="54" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="423" y="83" text-anchor="middle" font-size="13">PostgreSQL</text>
    <text x="423" y="100" text-anchor="middle" font-size="11" opacity=".7">CDC + history</text>
    <rect x="538" y="60" width="122" height="54" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="599" y="83" text-anchor="middle" font-size="13">dbt marts</text>
    <text x="599" y="100" text-anchor="middle" font-size="11" opacity=".7">tested</text>
    <rect x="714" y="60" width="122" height="54" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="775" y="83" text-anchor="middle" font-size="13">Consumers</text>
    <text x="775" y="100" text-anchor="middle" font-size="11" opacity=".7">API / BI / brief</text>
    <line x1="132" y1="87" x2="181" y2="87" stroke="currentColor" stroke-width="1.2" marker-end="url(#a1)"/>
    <line x1="308" y1="87" x2="357" y2="87" stroke="currentColor" stroke-width="1.2" marker-end="url(#a1)"/>
    <line x1="484" y1="87" x2="533" y2="87" stroke="currentColor" stroke-width="1.2" marker-end="url(#a1)"/>
    <line x1="660" y1="87" x2="709" y2="87" stroke="currentColor" stroke-width="1.2" marker-end="url(#a1)"/>
    <text x="156" y="79" text-anchor="middle" font-size="10" opacity=".75">fetch</text>
    <text x="332" y="79" text-anchor="middle" font-size="10" opacity=".75">upsert</text>
    <text x="508" y="79" text-anchor="middle" font-size="10" opacity=".75">build</text>
    <text x="684" y="79" text-anchor="middle" font-size="10" opacity=".75">read</text>
    <rect x="186" y="188" width="298" height="54" rx="4" fill="none" stroke="#0e6b59" stroke-width="1.8"/>
    <text x="335" y="211" text-anchor="middle" font-size="13" fill="#0e6b59">Bronze: raw payloads, stored before parsing</text>
    <text x="335" y="228" text-anchor="middle" font-size="11" fill="#0e6b59" opacity=".85">local filesystem now, S3 in production</text>
    <line x1="247" y1="114" x2="247" y2="185" stroke="#0e6b59" stroke-width="1.8" marker-end="url(#a2)"/>
    <text x="255" y="152" font-size="11" fill="#0e6b59">write raw first</text>
    <path d="M 423 188 L 423 116" fill="none" stroke="#0e6b59" stroke-width="1.8" stroke-dasharray="5 3" marker-end="url(#a2)"/>
    <text x="431" y="152" font-size="11" fill="#0e6b59">replay, no API calls</text>
    <text x="775" y="152" text-anchor="middle" font-size="11" opacity=".75">forecasts / undercut alerts</text>
    <text x="775" y="169" text-anchor="middle" font-size="11" opacity=".75">matching / weekly brief</text>
    <line x1="775" y1="114" x2="775" y2="138" stroke="currentColor" stroke-width="1" opacity=".5"/>
    <text x="10" y="278" font-size="11" opacity=".7">Solid = normal flow. Dashed = recovery path.</text>
  </g>
</svg>
</div>
<figcaption><b>Figure 1.</b> Solution architecture in six stages. Raw payloads are written before parsing, so the warehouse can be rebuilt from them without contacting any source API.</figcaption>
</figure>"""


def cdc_diagram() -> str:
    return """<figure>
<div class="figscroll">
<svg viewBox="0 0 900 215" role="img" aria-label="Change data capture decision: an incoming observation is compared with the preceding observation for the same product and retailer. If the price differs, or the twenty-four hour heartbeat has elapsed, a row is appended. Otherwise it is skipped. History is never updated in place.">
  <defs><marker id="a3" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>
  <g font-family="IBM Plex Mono, monospace" font-size="12" fill="currentColor">
    <rect x="10" y="82" width="136" height="48" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="78" y="103" text-anchor="middle" font-size="12">observation</text>
    <text x="78" y="119" text-anchor="middle" font-size="11" opacity=".7">price + time</text>
    <polygon points="232,106 324,68 416,106 324,144" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="324" y="102" text-anchor="middle" font-size="11">price changed</text>
    <text x="324" y="117" text-anchor="middle" font-size="11">vs previous?</text>
    <polygon points="474,106 566,68 658,106 566,144" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="566" y="102" text-anchor="middle" font-size="11">24h heartbeat</text>
    <text x="566" y="117" text-anchor="middle" font-size="11">elapsed?</text>
    <rect x="722" y="40" width="168" height="46" rx="4" fill="none" stroke="#0e6b59" stroke-width="1.8"/>
    <text x="806" y="61" text-anchor="middle" font-size="12" fill="#0e6b59">append new row</text>
    <text x="806" y="77" text-anchor="middle" font-size="11" fill="#0e6b59" opacity=".85">idempotency key set</text>
    <rect x="722" y="130" width="168" height="46" rx="4" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="5 3"/>
    <text x="806" y="151" text-anchor="middle" font-size="12">skip</text>
    <text x="806" y="167" text-anchor="middle" font-size="11" opacity=".7">counted, not stored</text>
    <line x1="146" y1="106" x2="227" y2="106" stroke="currentColor" stroke-width="1.2" marker-end="url(#a3)"/>
    <line x1="416" y1="106" x2="469" y2="106" stroke="currentColor" stroke-width="1.2" marker-end="url(#a3)"/>
    <text x="442" y="98" text-anchor="middle" font-size="11" opacity=".75">no</text>
    <path d="M 324 68 L 324 40 L 717 40" fill="none" stroke="currentColor" stroke-width="1.2" marker-end="url(#a3)"/>
    <text x="350" y="33" font-size="11" opacity=".75">yes</text>
    <path d="M 566 68 L 566 48 L 717 48" fill="none" stroke="currentColor" stroke-width="1.2" marker-end="url(#a3)"/>
    <text x="592" y="41" font-size="11" opacity=".75">yes, prove liveness</text>
    <path d="M 566 144 L 566 153 L 717 153" fill="none" stroke="currentColor" stroke-width="1.2" marker-end="url(#a3)"/>
    <text x="592" y="168" font-size="11" opacity=".75">no</text>
    <text x="10" y="203" font-size="11" opacity=".7">The comparison is against the observation preceding this one in time, not the newest row, so backfilled history is judged correctly.</text>
  </g>
</svg>
</div>
<figcaption><b>Figure 2.</b> Insert-on-change with a heartbeat. Unchanged prices are not re-recorded, which keeps the event tables lean; the 24-hour heartbeat still records that the system looked and found no change.</figcaption>
</figure>"""


def rows(data, cls_last=""):
    out = []
    for r in data:
        cells = "".join(
            f'<td class="num">{c}</td>' if i >= 2 else f"<td>{c}</td>" for i, c in enumerate(r)
        )
        out.append(f"<tr>{cells}</tr>")
    return "".join(out)


def build_html() -> str:
    f = FACTS
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

  h1,h2,h3 {{ font-family:var(--f-head); margin:0; font-weight:600; text-wrap:balance; }}
  h1 {{ font-size:24pt; line-height:1.12; letter-spacing:-.01em; }}
  h2 {{ font-size:14pt; margin-top:1.9rem; padding-bottom:.3rem;
        border-bottom:1.5px solid var(--ink); break-after:avoid; page-break-after:avoid; }}
  h3 {{ font-size:11.5pt; margin-top:1.2rem; color:var(--ink-soft);
        break-after:avoid; page-break-after:avoid; }}
  p {{ margin:.6rem 0; }}
  ul,ol {{ margin:.6rem 0; padding-left:1.15rem; }}
  li {{ margin:.25rem 0; }}
  code {{ font-family:var(--f-mono); font-size:.88em; background:var(--tint);
          padding:.05rem .25rem; border-radius:2px; }}
  pre {{ font-family:var(--f-mono); font-size:8.5pt; line-height:1.5; background:var(--tint);
         border-left:2px solid var(--accent); padding:.7rem .9rem; margin:.8rem 0;
         overflow-x:auto; break-inside:avoid; page-break-inside:avoid; }}
  pre code {{ background:none; padding:0; }}

  /* cover */
  .cover {{ border-bottom:3px solid var(--ink); padding-bottom:1.4rem; margin-bottom:1.6rem; }}
  .kicker {{ font-family:var(--f-mono); font-size:8.5pt; letter-spacing:.16em;
             text-transform:uppercase; color:var(--accent); }}
  .subtitle {{ font-size:12pt; color:var(--ink-soft); margin-top:.5rem; }}
  .meta {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px;
           background:var(--rule); border:1px solid var(--rule); margin-top:1.3rem; }}
  .meta div {{ background:var(--paper); padding:.5rem .7rem; }}
  .meta dt {{ font-family:var(--f-mono); font-size:7.5pt; letter-spacing:.09em;
              text-transform:uppercase; color:var(--ink-mute); }}
  .meta dd {{ margin:.15rem 0 0; font-weight:600; font-size:9.5pt; }}

  table {{ border-collapse:collapse; width:100%; font-size:9pt; margin:.8rem 0;
           break-inside:avoid; page-break-inside:avoid; }}
  th,td {{ padding:.34rem .5rem; text-align:left; border-bottom:1px solid var(--rule-soft);
           vertical-align:top; }}
  thead th {{ background:var(--tint); border-bottom:1.2px solid var(--rule);
              font-family:var(--f-mono); font-weight:500; font-size:8pt;
              text-transform:uppercase; letter-spacing:.05em; color:var(--ink-mute); }}
  td.num,th.num {{ font-family:var(--f-mono); font-variant-numeric:tabular-nums;
                   text-align:right; white-space:nowrap; }}
  caption {{ caption-side:top; text-align:left; font-size:8.5pt; color:var(--ink-mute);
             padding-bottom:.3rem; font-family:var(--f-mono); }}

  figure {{ margin:1.2rem 0; break-inside:avoid; page-break-inside:avoid; }}
  .figscroll {{ overflow-x:auto; }}
  figure svg {{ display:block; width:100%; height:auto; }}
  figcaption {{ font-size:8.5pt; color:var(--ink-soft); margin-top:.5rem;
                border-left:2px solid var(--rule); padding-left:.6rem; }}
  .figpage {{ break-before:page; page-break-before:always; }}

  .callout {{ border-left:3px solid var(--accent); background:var(--tint);
              padding:.65rem .9rem; margin:.9rem 0; font-size:9.5pt;
              break-inside:avoid; page-break-inside:avoid; }}
  .callout.warn {{ border-left-color:var(--warn); }}
  .tag {{ display:inline-block; font-family:var(--f-mono); font-size:7.5pt;
          text-transform:uppercase; letter-spacing:.04em; padding:.08rem .35rem;
          border-radius:2px; white-space:nowrap; }}
  .tag.good {{ background:var(--good-b); color:var(--good); }}
  .tag.warn {{ background:var(--warn-b); color:var(--warn); }}
  .tag.crit {{ background:var(--crit-b); color:var(--crit); }}
  .tag.mute {{ background:var(--tint); color:var(--ink-mute); }}

  .toc {{ background:var(--tint); border-left:3px solid var(--accent);
          padding:.8rem 1.1rem; margin:1.4rem 0; font-size:9.5pt; }}
  .toc ol {{ columns:2; column-gap:1.8rem; margin:.3rem 0 0; }}
  .toc li {{ break-inside:avoid; margin:.12rem 0; }}

  @page {{ size:A4; margin:16mm 14mm 18mm; }}
  @media print {{
    .page {{ max-width:none; margin:0; padding:0; }}
    h2 {{ break-before:auto; }}
    a {{ color:var(--ink); text-decoration:none; }}
  }}
</style>
</head>
<body>
<div class="page">

<header class="cover">
  <div class="kicker">Data Engineering Project &#183; Submission</div>
  <h1>Competitor Price and Availability Intelligence Platform</h1>
  <p class="subtitle">An end-to-end pipeline that tracks competitor prices across retailers,
  records every change, forecasts short-term movement, and alerts on undercutting.</p>
  <dl class="meta">
    <div><dt>Submitted by</dt><dd>Love Vyas</dd></div>
    <div><dt>Date</dt><dd>1 September 2026</dd></div>
    <div><dt>Domain</dt><dd>Retail price intelligence</dd></div>
    <div><dt>Core stack</dt><dd>Python, Celery, PostgreSQL, dbt</dd></div>
    <div><dt>Data source</dt><dd>Open Prices (public API)</dd></div>
    <div><dt>Scale delivered</dt><dd>{f["events"]} price events</dd></div>
  </dl>
</header>

<nav class="toc">
  <b>Contents</b>
  <ol>
    <li>Problem statement</li>
    <li>Objectives and scope</li>
    <li>Data sources</li>
    <li>Solution architecture</li>
    <li>Technology stack</li>
    <li>Database design</li>
    <li>Data pipeline</li>
    <li>Analytics layer</li>
    <li>Forecasting</li>
    <li>Product matching</li>
    <li>Serving and visualization</li>
    <li>Infrastructure</li>
    <li>Testing and data quality</li>
    <li>Results</li>
    <li>Challenges and resolutions</li>
    <li>Limitations and future work</li>
  </ol>
</nav>

<h2>Section 1 &#8212; Problem Statement</h2>

<h3>Business context</h3>
<p>Retailers and brands lose margin in two ways that are invisible without continuous
monitoring. A competitor quietly drops a price and takes volume before anyone notices;
or a competitor goes out of stock and the demand that would have gone to them is never
captured. Commercial tools such as Prisync, Competera and Minderest sell exactly this
capability &#8212; competitor price monitoring, repricing signals, and market intelligence.</p>

<h3>The problem</h3>
<p>Build a system that continuously monitors competitor prices and availability across
multiple retailers, records the full history of every change rather than only the latest
value, and turns that history into decisions a category manager can act on: who is
undercutting us and by how much, which products are volatile enough to need watching, and
where prices are likely to move next.</p>

<p>The system must work from public data sources, must not lose history when a source is
unavailable, and must be honest about the confidence of what it reports &#8212; a price
observed three weeks ago should not be presented with the same authority as one observed
today.</p>

<h3>Expected outcome</h3>
<p>A working pipeline that converts raw competitor price observations into a queryable
analytical layer, a set of business marts answering specific pricing questions, short-term
per-SKU forecasts with measured accuracy, an alerting path for undercutting, and a
reporting layer suitable for both technical and non-technical consumers.</p>

<h2>Section 2 &#8212; Objectives and Scope</h2>

<table>
  <thead><tr><th style="width:34%">Objective</th><th>Success criterion</th><th>Status</th></tr></thead>
  <tbody>
    <tr><td>Multi-source ingestion</td><td>Pluggable source interface; adding a source is one file</td><td><span class="tag good">met</span></td></tr>
    <tr><td>Full change history</td><td>Every price and attribute change recorded, never overwritten</td><td><span class="tag good">met</span></td></tr>
    <tr><td>Reproducibility</td><td>Warehouse rebuildable from raw payloads with no API calls</td><td><span class="tag good">met</span></td></tr>
    <tr><td>Tested transformations</td><td>Business rules defined once and covered by data tests</td><td><span class="tag good">met</span></td></tr>
    <tr><td>Forecasting</td><td>Per-SKU forecast with backtested error, benchmarked against a naive baseline</td><td><span class="tag good">met</span></td></tr>
    <tr><td>Undercut alerting</td><td>Alerts raised with severity and evidence age, deduplicated</td><td><span class="tag good">met</span></td></tr>
    <tr><td>Availability tracking</td><td>Out-of-stock frequency per SKU and retailer</td><td><span class="tag warn">blocked</span></td></tr>
    <tr><td>Cloud deployment</td><td>Infrastructure as code for the full stack</td><td><span class="tag warn">written, not applied</span></td></tr>
  </tbody>
</table>

<p><b>In scope:</b> ingestion from public APIs, change data capture, warehouse modelling,
forecasting, alerting, product matching, and reporting.</p>
<p><b>Out of scope:</b> web scraping, checkout or transactions, multi-tenancy, and
sub-minute streaming. No personal data is collected; the system holds public product
prices only.</p>

<h2>Section 3 &#8212; Data Sources</h2>

<p>The platform is built on <b>Open Prices</b>, the price project of Open Food Facts. It is a
public, keyless API carrying crowd-sourced retail prices, each with a real observation
date and an OpenStreetMap store location. This matters: one product barcode genuinely
appears at several named retailers over time, which is the exact shape a competitor-price
platform needs. Product attribute data (name, brand, category) comes from the Open Food
Facts catalogue embedded in the same payload.</p>

<table>
  <thead><tr><th>Source</th><th>Auth</th><th>Role</th><th>Status</th></tr></thead>
  <tbody>
    <tr><td>Open Prices / Open Food Facts</td><td>keyless</td><td>All real price, retailer and product data</td><td><span class="tag good">live</span></td></tr>
    <tr><td>Fake Store API</td><td>keyless</td><td>Deterministic fixture for tests and local development</td><td><span class="tag good">live</span></td></tr>
    <tr><td>Best Buy</td><td>API key</td><td>Planned. Publishes stock, which activates availability tracking</td><td><span class="tag mute">interface ready</span></td></tr>
    <tr><td>eBay Browse</td><td>OAuth</td><td>Planned. Configured with the documented 5,000/day quota</td><td><span class="tag mute">interface ready</span></td></tr>
    <tr><td>Digi-Key</td><td>OAuth</td><td>Planned. Publishes real stock and price tiers</td><td><span class="tag mute">interface ready</span></td></tr>
  </tbody>
</table>

<h3>Data characteristics</h3>
<table>
  <thead><tr><th>Property</th><th class="num">Value</th><th>Implication for design</th></tr></thead>
  <tbody>
    <tr><td>Price observations</td><td class="num">{f["events"]}</td><td>Partitioning needed for query performance</td></tr>
    <tr><td>Distinct products</td><td class="num">{f["products"]}</td><td>Per-SKU modelling is feasible</td></tr>
    <tr><td>Distinct retailers</td><td class="num">{f["retailers"]}</td><td>Genuine multi-retailer comparison possible</td></tr>
    <tr><td>Distinct currencies</td><td class="num">{f["currencies"]}</td><td>Currency must be part of the grain (see Section 8)</td></tr>
    <tr><td>Observation span</td><td class="num">{f["span"]}</td><td>Historical backfill must not be treated as current</td></tr>
    <tr><td>Observations in last 30 days</td><td class="num">{f["events_recent"]}</td><td>Recent window drives forecasting and alerting</td></tr>
  </tbody>
</table>

<div class="callout">
<b>One authored dataset.</b> Every price, product, retailer and date is real and comes from
the API. The single exception is <code>own_catalog</code>, which represents the company's own
catalogue &#8212; the thing competitor prices are compared against. No public API can supply
that, so it is generated from products actually observed in the last 60 days, with our
price set around each observed market average. Its provenance is documented alongside it.
</div>

<h2>Section 4 &#8212; Solution Architecture</h2>

<p>Six stages, each independently runnable and inspectable. The defining design choice is
that raw API payloads are persisted <i>before</i> parsing, which makes the database a
derived artifact rather than the system of record.</p>

{system_map()}

<table>
  <thead><tr><th>Layer</th><th>Responsibility</th></tr></thead>
  <tbody>
    <tr><td>Ingestion</td><td>Scheduled fetch with per-source rate limiting and daily quota guards; retries with backoff; dead-letter for permanent failures</td></tr>
    <tr><td>Bronze (raw zone)</td><td>Immutable gzipped JSON, partitioned by source and date, keyed by an idempotency hash</td></tr>
    <tr><td>Serving database</td><td>Normalized reference data, slowly-changing dimension, append-only event tables</td></tr>
    <tr><td>Transformation</td><td>dbt models in three layers, with data tests that gate the build</td></tr>
    <tr><td>Analytics</td><td>Forecasting, product matching, undercut evaluation</td></tr>
    <tr><td>Presentation</td><td>REST API, Metabase dashboard, Slack alerts, weekly written brief</td></tr>
  </tbody>
</table>

<h2>Section 5 &#8212; Technology Stack</h2>

<table>
  <thead><tr><th>Layer</th><th>Technology</th><th>Reason for selection</th></tr></thead>
  <tbody>
    <tr><td>Orchestration</td><td>Celery 5.5 + Celery Beat</td><td>Periodic polling with task fan-out; far lighter than a full orchestrator for this workload</td></tr>
    <tr><td>Broker</td><td>Redis</td><td>Also backs the shared rate limiter, so one component serves two needs</td></tr>
    <tr><td>Database</td><td>PostgreSQL 16 + pgvector</td><td>Partitioning, JSONB and vector similarity in one engine; no separate vector store</td></tr>
    <tr><td>Transformation</td><td>dbt Core</td><td>SQL-first, testable, documented lineage</td></tr>
    <tr><td>Validation</td><td>Pydantic v2 + Pandera</td><td>Per-record shape and cross-record batch contracts</td></tr>
    <tr><td>Forecasting</td><td>Nixtla statsforecast</td><td>Fast per-SKU statistical models with native prediction intervals</td></tr>
    <tr><td>Embeddings</td><td>fastembed (ONNX)</td><td>Same 384-dim model as sentence-transformers without the PyTorch dependency</td></tr>
    <tr><td>API</td><td>FastAPI</td><td>Typed request and response models, generated OpenAPI documentation</td></tr>
    <tr><td>Dashboard</td><td>Metabase</td><td>Connects directly to the marts; no BI-specific modelling layer needed</td></tr>
    <tr><td>Review UI</td><td>Streamlit</td><td>Minimal code for an internal human-in-the-loop screen</td></tr>
    <tr><td>Infrastructure</td><td>Terraform</td><td>Reviewable, version-controlled cloud definition</td></tr>
  </tbody>
</table>

<h2>Section 6 &#8212; Database Design</h2>

<p>Twelve tables in three groups: reference data, append-only event history, and derived
output. The design separates <i>what a product is</i> (slowly changing) from <i>what was
observed about it</i> (append-only), which is what makes exact change history possible.</p>

{er_diagram()}

<h3>Table reference</h3>
<table>
  <thead><tr><th>Table</th><th>Group</th><th>Grain &#8212; one row per</th><th class="num">Rows</th></tr></thead>
  <tbody>
    <tr><td><code>sources</code></td><td>reference</td><td>upstream data source</td><td class="num">2</td></tr>
    <tr><td><code>retailers</code></td><td>reference</td><td>retailer within a source</td><td class="num">{f["retailers"]}</td></tr>
    <tr><td><code>products</code></td><td>reference</td><td>product within a source</td><td class="num">{f["products"]}</td></tr>
    <tr><td><code>seed_products</code></td><td>reference</td><td>SKU selected for scheduled tracking</td><td class="num">60</td></tr>
    <tr><td><code>product_versions</code></td><td>dimension (SCD2)</td><td>version of a product's attributes</td><td class="num">{f["products"]}</td></tr>
    <tr><td><code>price_events</code></td><td>fact</td><td>observed price per product, retailer and time</td><td class="num">{f["events"]}</td></tr>
    <tr><td><code>stock_events</code></td><td>fact</td><td>observed availability</td><td class="num">0</td></tr>
    <tr><td><code>product_matches</code></td><td>derived</td><td>candidate pair of equivalent products</td><td class="num">2,557</td></tr>
    <tr><td><code>forecasts</code></td><td>derived</td><td>predicted price for one product and date</td><td class="num">{f["forecast_rows"]}</td></tr>
    <tr><td><code>forecast_accuracy</code></td><td>derived</td><td>backtested error per product and model</td><td class="num">27</td></tr>
    <tr><td><code>alerts</code></td><td>derived</td><td>alert raised, with delivery timestamp</td><td class="num">62</td></tr>
    <tr><td><code>ingestion_runs</code></td><td>operational</td><td>one ingestion cycle</td><td class="num">&#8212;</td></tr>
  </tbody>
</table>

<h3>Invariants enforced by the schema</h3>
<p>These are constraints in the database, not conventions in application code, so no bug
can violate them.</p>
<table>
  <thead><tr><th style="width:30%">Invariant</th><th>Mechanism</th></tr></thead>
  <tbody>
    <tr><td>Exactly one open version per product</td><td>Partial unique index on <code>product_versions(product_id) where is_current</code></td></tr>
    <tr><td>No duplicate observations</td><td>Unique index on <code>(idempotency_key, observed_at)</code>; retries and replays collapse</td></tr>
    <tr><td>A match is an unordered pair</td><td>Check constraint <code>product_id_a &lt; product_id_b</code></td></tr>
    <tr><td>Events remain queryable at volume</td><td>Monthly range partitions on <code>observed_at</code>, created on demand ({f["partitions"]} in use)</td></tr>
  </tbody>
</table>

<h2>Section 7 &#8212; Data Pipeline</h2>

<h3>Extraction</h3>
<p>Celery Beat enqueues per-source fetch tasks on three cadences: high-volatility SKUs
every six hours, mid-tier daily, long-tail weekly. Before any HTTP call, the worker passes
two Redis-backed guards &#8212; a token bucket for instantaneous rate and a counter for the
daily quota. Both live in Redis rather than in the worker, because Celery's own rate limit
is per-worker and would silently multiply the request rate as workers scale out.</p>

<p>Every response is written to the raw zone before it is parsed. Failures are separated by
kind: a transport error retries with exponential backoff and jitter; a rate limit retries
after the limiter's own computed delay; an exhausted daily quota does <i>not</i> retry,
because it cannot succeed again until the quota resets, and instead dead-letters immediately.</p>

<h3>Transformation</h3>
<p>Raw payloads are normalized into a source-independent record, validated per record with
Pydantic and per batch with Pandera, then applied to the warehouse with change data
capture. Two independent checks catch different failures: per-record validation catches a
malformed price, while batch validation catches an entire source returning zero rows or a
column that has become all-null after an upstream change.</p>

{cdc_diagram()}

<p>Change data capture has two implementations with identical semantics. A row-by-row path
is the readable reference; a set-based path stages the batch in a temporary table and
expresses the same rules in SQL, so cost scales with batch size rather than record count.
A parity test runs both over the same dataset and asserts identical output.</p>

<h3>Loading</h3>
<p>Product attributes are versioned as a Type 2 slowly changing dimension: when a tracked
attribute changes, the open row is closed and a new one opened. Price observations are
appended only when the price differs from the preceding observation, or when a 24-hour
heartbeat has elapsed &#8212; which records that the system looked and found no change.
History is never updated in place.</p>

<h2>Section 8 &#8212; Analytics Layer</h2>

<p>dbt Core on PostgreSQL, in three layers. Every downstream consumer &#8212; API, alerting,
forecasting, dashboard and the written brief &#8212; reads marts, never the raw event
tables. That is what keeps a business rule defined exactly once.</p>

<table>
  <thead><tr><th>Mart</th><th>Question it answers</th><th class="num">Rows</th></tr></thead>
  <tbody>
    <tr><td><code>mart_price_trend</code></td><td>Daily series and day-over-day change; feeds forecasting</td><td class="num">{f["trend_rows"]}</td></tr>
    <tr><td><code>mart_price_volatility</code></td><td>Which SKUs move most, by coefficient of variation</td><td class="num">{f["volatility_rows"]}</td></tr>
    <tr><td><code>mart_price_gap_vs_own</code></td><td>Competitor price versus our catalogue, matched on barcode</td><td class="num">{f["gap_rows"]}</td></tr>
    <tr><td><code>mart_undercut_alerts</code></td><td>Who is undercutting us, how badly, how fresh the evidence</td><td class="num">{f["undercuts"]}</td></tr>
    <tr><td><code>mart_out_of_stock_frequency</code></td><td>Out-of-stock rate per SKU and retailer</td><td class="num">0</td></tr>
  </tbody>
</table>

<div class="callout">
<b>Currency is part of the grain everywhere.</b> The data spans {f["currencies"]} currencies.
Subtracting a price in one currency from a price in another produces a number that looks
authoritative and means nothing &#8212; and would fire false critical alerts, since 12 SEK
beside 1.20 EUR reads as a catastrophic undercut when the two are close in value. The gap
mart therefore joins on barcode <i>and</i> currency, so a cross-currency pair produces no
row rather than a wrong one. Coefficient of variation is used as the volatility measure
for the same reason: being unitless, it stays comparable across currencies and price levels.
</div>

<h2>Section 9 &#8212; Forecasting</h2>

<p>Per-SKU short-horizon price forecasting using statistical models: AutoETS and AutoARIMA
as candidates, with SeasonalNaive as a mandatory baseline. Prices are irregular &#8212; an
observation appears when someone records it &#8212; so each series is resampled onto a daily
grid and forward-filled, on the assumption that a shelf price holds until next observed.</p>

<p>Accuracy is measured by rolling-origin cross-validation, not by fit: the model is refitted
on successive windows and scored on data it has not seen. Series shorter than a minimum
length, or whose most recent observation is older than the staleness threshold, are excluded
rather than forecast badly.</p>

<table>
  <caption>Backtested accuracy, latest run</caption>
  <thead><tr><th>Model</th><th class="num">Series</th><th class="num">Avg MAPE</th><th class="num">Worst</th></tr></thead>
  <tbody>
    <tr><td>AutoARIMA</td><td class="num">9</td><td class="num">3.13%</td><td class="num">15.56%</td></tr>
    <tr><td>SeasonalNaive (baseline)</td><td class="num">9</td><td class="num">3.13%</td><td class="num">15.56%</td></tr>
    <tr><td>AutoETS</td><td class="num">9</td><td class="num">3.13%</td><td class="num">15.56%</td></tr>
  </tbody>
</table>

<p>All three models score identically, and the naive baseline is never beaten. This is
reported rather than hidden: on short, sparse series retail prices behave close to a random
walk, and a champion that cannot beat "tomorrow looks like today" is not earning its cost.
The pipeline is correct; the data density is the limiting factor. A daily-refresh retail API
is what would make forecasting genuinely informative here.</p>

<h2>Section 10 &#8212; Product Matching</h2>

<p>The same physical product appears under different barcodes, titles and languages across
retailers. Matching them is what makes comparison possible beyond an exact barcode hit.
The policy is deliberately ordered:</p>
<ol>
  <li><b>Structured identifiers win outright.</b> An exact barcode match is a fact; an
  embedding similarity is an opinion.</li>
  <li><b>Blocking before vector search.</b> Candidates are restricted by category first,
  which cuts the comparison space and suppresses false positives on similar names.</li>
  <li><b>Three confidence bands</b> rather than one cutoff.</li>
</ol>

<table>
  <thead><tr><th>Band</th><th>Rule</th><th>Action</th><th class="num">Pairs</th></tr></thead>
  <tbody>
    <tr><td><span class="tag good">auto</span></td><td>cosine similarity &#8805; 0.92</td><td>accepted automatically</td><td class="num">{f["matches_auto"]}</td></tr>
    <tr><td><span class="tag warn">review</span></td><td>0.80 to 0.92</td><td>queued for a human decision</td><td class="num">{f["matches_pending"]}</td></tr>
    <tr><td><span class="tag mute">reject</span></td><td>&lt; 0.80</td><td>never surfaced</td><td class="num">&#8212;</td></tr>
  </tbody>
</table>

<p>Embeddings are 384-dimensional, stored in PostgreSQL via pgvector with an HNSW index. A
Streamlit screen presents candidate pairs side by side with their similarity score; each
verdict is stored with reviewer and timestamp, forming the labelled set against which
precision and recall can later be measured.</p>

<h2>Section 11 &#8212; Serving and Visualization</h2>

<h3>API</h3>
<table>
  <thead><tr><th>Endpoint</th><th>Returns</th></tr></thead>
  <tbody>
    <tr><td><code>GET /health</code></td><td>Liveness, database reachability, whether authentication is enabled</td></tr>
    <tr><td><code>GET /products</code></td><td>Catalogue, filterable by category and tier</td></tr>
    <tr><td><code>GET /prices/{{product_id}}</code></td><td>Daily price history with change percentage</td></tr>
    <tr><td><code>GET /forecasts/{{product_id}}</code></td><td>Latest forecast with prediction intervals</td></tr>
    <tr><td><code>GET /undercuts</code></td><td>Current undercuts, filterable by severity and staleness</td></tr>
    <tr><td><code>GET /alerts</code></td><td>Raised alerts and delivery status</td></tr>
    <tr><td><code>GET /matches/review</code></td><td>Candidate matches awaiting review</td></tr>
  </tbody>
</table>

<h3>Alerting</h3>
<p>Undercuts are evaluated every six hours. Each alert carries a severity derived from the
size of the gap and a confidence label derived from the age of the evidence. Alerts are
deduplicated so a persistent undercut is not re-sent every cycle, and alerts resting on
evidence older than the freshness threshold are recorded but deliberately not delivered.</p>

<h3>Dashboard and written brief</h3>
<p>Metabase connects directly to the marts; all dashboard cards were executed against the
live database. Separately, a weekly brief is generated from a closed set of facts queried
from the marts. An optional LLM narration layer receives the same facts and its output is
checked number by number against them; any figure not present in the facts causes the
narrated version to be discarded in favour of the deterministic one.</p>

<h2>Section 12 &#8212; Infrastructure</h2>

<p>The target deployment is defined in Terraform: a VPC with the application host in a public
subnet and the database in private subnets with no internet route, PostgreSQL on RDS with TLS
enforced and no public address, an S3 bucket for the raw zone with versioning and lifecycle
tiering, secrets in SSM Parameter Store, a least-privilege instance role, CloudWatch alarms,
and a monthly budget alarm. Continuous integration runs linting, the test suites, dbt
compilation and Terraform validation without requiring cloud credentials.</p>

<div class="callout warn">
<b>Not applied.</b> The configuration passes <code>terraform fmt</code> and
<code>terraform validate</code>, which confirms syntax and provider schema only.
<code>terraform plan</code> has not been run against a real account, so a first apply should
be expected to surface genuine issues such as availability-zone availability, engine version
drift and IAM propagation delays.
</div>

<h2>Section 13 &#8212; Testing and Data Quality</h2>

<table>
  <thead><tr><th>Suite</th><th class="num">Tests</th><th>Coverage</th></tr></thead>
  <tbody>
    <tr><td>Python unit</td><td class="num">~130</td><td>Normalizers, CDC rules, forecast metrics, alert logic, guardrail, authentication</td></tr>
    <tr><td>Python integration</td><td class="num">~20</td><td>Rate limiting against real Redis; CDC parity against a real database</td></tr>
    <tr><td>dbt data tests</td><td class="num">{f["dbt_tests"]}</td><td>Schema, referential integrity, accepted ranges, cross-field invariants</td></tr>
  </tbody>
</table>

<p>The dbt tests assert relationships between fields rather than only per-column
constraints: the computed gap must agree with its own inputs, the undercut flag must agree
with the gap, maximum must not fall below minimum, and time must move forward within a
series. A <code>not_null</code> test would catch none of these; each guards against a
refactor silently inverting a rule.</p>

<h2>Section 14 &#8212; Results</h2>

<table>
  <caption>Delivered scale, measured with the pipeline idle and marts freshly built</caption>
  <thead><tr><th>Measure</th><th class="num">Value</th></tr></thead>
  <tbody>
    <tr><td>Price observations recorded</td><td class="num">{f["events"]}</td></tr>
    <tr><td>Observations in the last 30 days</td><td class="num">{f["events_recent"]}</td></tr>
    <tr><td>Products tracked</td><td class="num">{f["products"]}</td></tr>
    <tr><td>Retailers observed</td><td class="num">{f["retailers"]}</td></tr>
    <tr><td>Monthly partitions in use</td><td class="num">{f["partitions"]}</td></tr>
    <tr><td>Undercuts detected</td><td class="num">{f["undercuts"]}</td></tr>
    <tr><td>Undercuts on evidence 7 days old or less</td><td class="num">{f["undercuts_fresh"]}</td></tr>
    <tr><td>Automated tests passing</td><td class="num">{int(f["py_tests"]) + int(f["dbt_tests"])}</td></tr>
  </tbody>
</table>

<table>
  <caption>Largest undercuts on current evidence</caption>
  <thead><tr><th>Product</th><th>Retailer</th><th class="num">Ours</th><th class="num">Theirs</th><th class="num">Gap</th><th class="num">Age</th></tr></thead>
  <tbody>{undercut_rows}</tbody>
</table>

<table>
  <caption>Most volatile products by coefficient of variation</caption>
  <thead><tr><th>Product</th><th>Retailer</th><th class="num">Mean</th><th class="num">CV</th><th>Band</th><th class="num">Points</th></tr></thead>
  <tbody>{volatile_rows}</tbody>
</table>

<h3>Performance</h3>
<table>
  <thead><tr><th>Operation</th><th class="num">Result</th></tr></thead>
  <tbody>
    <tr><td>Replay of one stored day (947 payloads, 7,922 records)</td><td class="num">41 s</td></tr>
    <tr><td>The same work row-by-row over a 298 ms link</td><td class="num">~3.3 h (est.)</td></tr>
    <tr><td>Full warehouse rebuild from the raw zone</td><td class="num">30 s</td></tr>
    <tr><td>Embedding 1,251 products</td><td class="num">35 s</td></tr>
    <tr><td>Dashboard card query latency</td><td class="num">141&#8211;486 ms</td></tr>
  </tbody>
</table>

<h2>Section 15 &#8212; Challenges and Resolutions</h2>

<table>
  <thead><tr><th style="width:26%">Challenge</th><th>Diagnosis and resolution</th></tr></thead>
  <tbody>
    <tr>
      <td>Forecast accuracy looked implausibly good</td>
      <td>The first run reported 0.15% MAPE. The metric was scoring the forward-fill rather than the forecast: series are resampled onto a daily grid, and on a near-constant series predicting the last value is trivially correct. Scoring was changed to ignore filled days. Every model's reported accuracy became worse, which was the point.</td>
    </tr>
    <tr>
      <td>Ingestion throughput collapsed against a remote database</td>
      <td>The row-by-row CDC path issued roughly five statements per record &#8212; acceptable at sub-millisecond latency, pathological at 298 ms. A day's backfill would have taken about 3.3 hours. A set-based implementation reduced it to 41 seconds; both paths were kept, with a parity test asserting they produce identical output.</td>
    </tr>
    <tr>
      <td>The warehouse described 2010, not the present</td>
      <td>The source API returns oldest contributions first by default, so discovery filled the warehouse with genuine but decade-old observations &#8212; past every staleness gate, leaving nothing forecastable. Switching the ordering to most-recently-contributed changed the sample from 1 store on 1 date to 22 stores across 11 dates.</td>
    </tr>
    <tr>
      <td>Product versions churned on every observation</td>
      <td>The row-level product name is contributor-entered free text; one barcode carried 25 spellings, opening a new dimension version each time. The canonical catalogue name is used instead, with the free-text field as fallback.</td>
    </tr>
    <tr>
      <td>An intermittent test failure</td>
      <td>A rate-limiter test spent its burst then asserted the next call was refused &#8212; which silently depended on four Redis round-trips completing within one second. Under load they did not, a token refilled, and the test failed with nothing wrong. The refill rate was slowed so the assertion no longer races the clock.</td>
    </tr>
    <tr>
      <td>Database lost to a storage fault</td>
      <td>A Docker storage-layer corruption destroyed the volume mid-project. Because every raw payload had been written before parsing, the entire warehouse was rebuilt in 30 seconds with no upstream API calls. This validated the raw-first design under real failure rather than in theory.</td>
    </tr>
  </tbody>
</table>

<h2>Section 16 &#8212; Limitations and Future Work</h2>

<h3>Current limitations</h3>
<ol>
  <li><b>Availability tracking produces no data.</b> No connected source publishes stock
  levels. The table, partitions and mart are built against the real schema and begin
  producing numbers as soon as a stock-bearing source is connected.</li>
  <li><b>Forecasting is data-limited.</b> Only {f["forecast_products"]} products have series
  dense and recent enough to model, and the naive baseline is not beaten. This reflects the
  sparsity of crowd-sourced pricing, not a defect in the pipeline.</li>
  <li><b>Cloud infrastructure is unproven.</b> Validated but never applied.</li>
  <li><b>{f["matches_pending"]} match candidates await review.</b> A genuine human workload;
  raising the review threshold would reduce it at the cost of recall.</li>
  <li><b>Cross-currency comparison is unsupported</b> by design, pending dated exchange rates.</li>
</ol>

<h3>Future work</h3>
<ol>
  <li><b>Connect a keyed retail source, starting with Best Buy.</b> Highest value per unit of
  effort: it is the simplest approval, it publishes stock &#8212; which alone activates
  availability tracking &#8212; and its refresh cadence supplies the dense daily series
  forecasting currently lacks. Two limitations close together.</li>
  <li><b>Run a plan and apply against a real cloud account</b>, with a budget alarm configured
  before the first apply.</li>
  <li><b>Work the review queue to a few hundred labelled pairs</b>, then measure precision and
  recall and tune the threshold on evidence rather than intuition.</li>
  <li><b>Add dated exchange rates</b> to enable cross-currency comparison. The change is
  additive: a rates table, a converted column in the intermediate layer, and currency-agnostic
  marts alongside the existing scoped ones.</li>
  <li><b>Move to an orchestrator</b> such as Dagster or Airflow when backfill lineage across
  interdependent jobs becomes the operational pain point.</li>
</ol>

<h2>Appendix &#8212; Reproducing the results</h2>
<pre><code>docker compose up -d                  # PostgreSQL + Redis
alembic upgrade head                  # schema and partitions
python -m app.cli ingest openprices --limit 600
python -m app.cli seed openprices --tier 1
make dbt-build                        # models + {f["dbt_tests"]} data tests
make forecast                         # backtest and forecast
make match                            # embed and match products
make alerts                           # evaluate undercuts
make brief                            # weekly brief
python -m app.cli status              # summary of the warehouse</code></pre>

<p style="font-size:8.5pt;color:var(--ink-mute);margin-top:1.4rem;border-top:1px solid var(--rule);padding-top:.7rem">
Every figure in this report was read from the running system on 1 September 2026 with the
pipeline idle and the marts freshly built. No value is estimated except where explicitly
labelled as such.
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
        "--virtual-time-budget=20000",  # let webfonts finish loading
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
