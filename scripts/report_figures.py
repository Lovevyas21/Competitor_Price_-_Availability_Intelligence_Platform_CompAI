ACCENT = "#0e6b59"
MUTED = "#7b8a86"


def _defs(uid: str) -> str:
    return (
        f'<defs><marker id="{uid}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker>'
        f'<marker id="{uid}a" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{ACCENT}"/></marker></defs>'
    )


def _wrap(svg: str, num: int, caption: str, page_break: bool = False) -> str:
    cls = "figpage" if page_break else ""
    return (
        f'<figure class="{cls}"><div class="figscroll">{svg}</div>'
        f"<figcaption><b>Figure {num}.</b> {caption}</figcaption></figure>"
    )


def _box(x, y, w, h, title, lines, accent=False, dashed=False):
    col = ACCENT if accent else "currentColor"
    sw = "1.8" if accent else "1.2"
    da = ' stroke-dasharray="5 3"' if dashed else ""
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="none" '
        f'stroke="{col}" stroke-width="{sw}"{da}/>',
        f'<text x="{x + w / 2}" y="{y + 20}" text-anchor="middle" font-size="13" '
        f'font-weight="600" fill="{col}">{title}</text>',
    ]
    for i, ln in enumerate(lines):
        out.append(
            f'<text x="{x + w / 2}" y="{y + 38 + i * 15}" text-anchor="middle" '
            f'font-size="11" opacity=".72">{ln}</text>'
        )
    return "".join(out)


def fig_architecture(num: int) -> str:
    s = [
        '<svg viewBox="0 0 920 400" role="img" aria-label="High level architecture. Public price APIs feed a scheduled ingestion layer. Raw payloads go to object storage before parsing; normalized rows go to PostgreSQL with change data capture. dbt builds tested marts. Forecasting, product matching and the AI brief read the marts, and results are served through an API, a BI dashboard, a review interface and alerts.">',
        _defs("ar1"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]

    s.append('<text x="12" y="20" font-size="11" opacity=".55">1. ACQUIRE</text>')
    s.append('<text x="250" y="20" font-size="11" opacity=".55">2. STORE</text>')
    s.append('<text x="500" y="20" font-size="11" opacity=".55">3. MODEL</text>')
    s.append('<text x="720" y="20" font-size="11" opacity=".55">4. PRESENT</text>')
    s.append(
        '<line x1="12" y1="30" x2="908" y2="30" stroke="currentColor" stroke-width=".7" opacity=".2"/>'
    )

    s.append(_box(12, 50, 170, 74, "Price sources", ["Open Prices API", "retail APIs (roadmap)"]))
    s.append(_box(12, 165, 170, 74, "Celery Beat", ["10 schedules", "tier 1 / 2 / 3"]))
    s.append(
        _box(12, 280, 170, 74, "Celery workers", ["rate limit + quota", "retry, backoff, DLQ"])
    )

    s.append(
        _box(
            250,
            50,
            180,
            74,
            "Object storage",
            ["raw JSON, gzipped", "written before parsing"],
            accent=True,
        )
    )
    s.append(
        _box(
            250,
            165,
            180,
            110,
            "PostgreSQL",
            ["reference tables", "SCD2 dimension", "append-only events", "pgvector embeddings"],
        )
    )
    s.append(_box(250, 305, 180, 60, "Dead letter", ["failed payloads"], dashed=True))

    s.append(_box(500, 50, 170, 90, "dbt", ["staging", "intermediate", "5 marts + 102 tests"]))
    s.append(_box(500, 175, 170, 74, "ML layer", ["statsforecast", "vector matching"]))
    s.append(_box(500, 285, 170, 74, "AI layer", ["CrewAI agents", "numeric guardrail"]))

    s.append(_box(720, 50, 188, 60, "FastAPI", ["7 endpoints"]))
    s.append(_box(720, 130, 188, 60, "Metabase", ["BI dashboard"]))
    s.append(_box(720, 210, 188, 60, "Streamlit", ["match review"]))
    s.append(_box(720, 290, 188, 60, "Alerts", ["Slack / email"]))

    a = 'stroke="currentColor" stroke-width="1.2" marker-end="url(#ar1)"'
    ac = f'stroke="{ACCENT}" stroke-width="1.6" marker-end="url(#ar1a)"'
    s.append(f'<path d="M 97 124 V 165" fill="none" {a}/>')
    s.append(f'<path d="M 97 239 V 280" fill="none" {a}/>')
    s.append(f'<path d="M 182 300 H 216 V 87 H 246" fill="none" {ac}/>')
    s.append('<text x="188" y="80" font-size="10" fill="' + ACCENT + '">raw first</text>')
    s.append(
        '<path d="M 182 317 H 246" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="5 3" marker-end="url(#ar1)"/>'
    )
    s.append(f'<path d="M 182 330 H 216 V 220 H 246" fill="none" {a}/>')
    s.append('<text x="188" y="214" font-size="10" opacity=".7">normalized</text>')
    s.append(f'<path d="M 340 124 V 165" fill="none" {ac} stroke-dasharray="5 3"/>')
    s.append(f'<text x="346" y="150" font-size="10" fill="{ACCENT}">replay</text>')
    s.append(f'<path d="M 430 200 H 466 V 95 H 496" fill="none" {a}/>')
    s.append(f'<path d="M 670 95 H 700 V 80 H 716" fill="none" {a}/>')
    s.append(f'<path d="M 670 110 H 690 V 160 H 716" fill="none" {a}/>')
    s.append(f'<path d="M 670 212 H 690 V 240 H 716" fill="none" {a}/>')
    s.append(f'<path d="M 670 322 H 716" fill="none" {a}/>')
    s.append(f'<path d="M 585 140 V 175" fill="none" {a}/>')
    s.append(f'<path d="M 585 249 V 285" fill="none" {a}/>')
    s.append(
        '<text x="12" y="388" font-size="10" opacity=".6">Green = the raw-first path: payloads are stored before parsing, so the warehouse can be rebuilt from them without calling any API again.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "End-to-end architecture. Data moves left to right through four stages; every "
        "presentation surface reads from the modelled marts, never from raw tables.",
    )


def fig_ingestion(num: int) -> str:
    steps = [
        ("1", "Schedule fires", "Beat enqueues a tier refresh onto the broker"),
        ("2", "Rate guard", "Redis token bucket: is a request allowed right now?"),
        ("3", "Quota guard", "Redis daily counter: is the source's daily budget left?"),
        ("4", "Fetch", "HTTP call to the source API"),
        ("5", "Persist raw", "Gzipped JSON written to object storage, unparsed"),
        ("6", "Normalize", "Source payload mapped to one internal record shape"),
        ("7", "Validate", "Per record (Pydantic) and per batch (Pandera)"),
        ("8", "Apply CDC", "Set-based upsert into PostgreSQL, idempotent"),
    ]
    s = [
        f'<svg viewBox="0 0 900 {70 + len(steps) * 52}" role="img" aria-label="Ingestion module: a schedule fires, two Redis guards check rate and daily quota, the source API is called, the raw payload is stored before parsing, the record is normalized and validated, and change data capture applies it to PostgreSQL. Rate limiting causes a timed retry; an exhausted quota sends the task to the dead-letter store without retrying.">',
        _defs("ar2"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    y = 46
    for n, title, sub in steps:
        accent = n in ("5", "8")
        col = ACCENT if accent else "currentColor"
        s.append(f'<circle cx="30" cy="{y}" r="13" fill="none" stroke="{col}" stroke-width="1.4"/>')
        s.append(
            f'<text x="30" y="{y + 4}" text-anchor="middle" font-size="11" fill="{col}">{n}</text>'
        )
        s.append(
            f'<text x="56" y="{y - 1}" font-size="13" font-weight="600" fill="{col}">{title}</text>'
        )
        s.append(f'<text x="56" y="{y + 15}" font-size="11" opacity=".72">{sub}</text>')
        if n != steps[-1][0]:
            s.append(
                f'<line x1="30" y1="{y + 13}" x2="30" y2="{y + 39}" stroke="currentColor" stroke-width="1" opacity=".35"/>'
            )
        y += 52
    s.append(
        '<rect x="470" y="30" width="420" height="86" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="5 3" opacity=".6"/>'
    )
    s.append('<text x="486" y="52" font-size="12" font-weight="600">Failure handling</text>')
    s.append(
        '<text x="486" y="70" font-size="11" opacity=".75">Rate limited -&gt; retry after the limiter\'s own computed delay.</text>'
    )
    s.append(
        '<text x="486" y="86" font-size="11" opacity=".75">Quota spent -&gt; dead-letter immediately, no retry: it cannot</text>'
    )
    s.append(
        '<text x="486" y="102" font-size="11" opacity=".75">succeed again until the quota resets.</text>'
    )
    s.append(
        '<rect x="470" y="140" width="420" height="70" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="5 3" opacity=".6"/>'
    )
    s.append('<text x="486" y="162" font-size="12" font-weight="600">Transport errors</text>')
    s.append(
        '<text x="486" y="180" font-size="11" opacity=".75">Exponential backoff with jitter, up to five attempts, then the</text>'
    )
    s.append(
        '<text x="486" y="196" font-size="11" opacity=".75">payload is dead-lettered for inspection and replay.</text>'
    )
    s.append(
        f'<text x="56" y="{y + 4}" font-size="10" opacity=".6">Step 5 is what makes steps 6 to 8 repeatable without contacting the source again.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Ingestion module. Two independent Redis guards sit in front of every HTTP call, "
        "and the raw payload is durable before any parsing logic runs.",
    )


def fig_cdc(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 220" role="img" aria-label="Change data capture decision. An incoming observation is compared with the preceding observation for the same product and retailer. If the price differs, or the twenty-four hour heartbeat has elapsed, a new row is appended. Otherwise it is skipped. Existing rows are never modified.">',
        _defs("ar3"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append(_box(10, 82, 140, 52, "observation", ["price + timestamp"]))
    s.append(
        '<polygon points="236,108 330,70 424,108 330,146" fill="none" stroke="currentColor" stroke-width="1.2"/>'
    )
    s.append('<text x="330" y="104" text-anchor="middle" font-size="11">price differs from</text>')
    s.append('<text x="330" y="119" text-anchor="middle" font-size="11">the preceding one?</text>')
    s.append(
        '<polygon points="480,108 574,70 668,108 574,146" fill="none" stroke="currentColor" stroke-width="1.2"/>'
    )
    s.append('<text x="574" y="104" text-anchor="middle" font-size="11">24h heartbeat</text>')
    s.append('<text x="574" y="119" text-anchor="middle" font-size="11">elapsed?</text>')
    s.append(_box(726, 40, 164, 52, "append row", ["idempotency key set"], accent=True))
    s.append(_box(726, 132, 164, 52, "skip", ["counted, not stored"], dashed=True))
    a = 'stroke="currentColor" stroke-width="1.2" marker-end="url(#ar3)"'
    s.append(f'<path d="M 150 108 H 231" fill="none" {a}/>')
    s.append(f'<path d="M 424 108 H 475" fill="none" {a}/>')
    s.append('<text x="449" y="100" text-anchor="middle" font-size="10" opacity=".7">no</text>')
    s.append(f'<path d="M 330 70 V 44 L 721 44" fill="none" {a}/>')
    s.append('<text x="356" y="38" font-size="10" opacity=".7">yes</text>')
    s.append(f'<path d="M 574 70 V 52 L 721 52" fill="none" {a}/>')
    s.append('<text x="600" y="46" font-size="10" opacity=".7">yes &#8212; record liveness</text>')
    s.append(f'<path d="M 574 146 V 156 L 721 156" fill="none" {a}/>')
    s.append('<text x="600" y="170" font-size="10" opacity=".7">no</text>')
    s.append(
        '<text x="10" y="208" font-size="10" opacity=".6">The comparison uses the observation immediately PRECEDING this one in time, not the newest row, so backfilled history is judged against the right neighbour.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Change data capture. Unchanged prices are not re-recorded, which keeps the event "
        "tables lean; the heartbeat still records that the system looked and saw no change.",
    )


ENTITIES = {
    "SOURCES": (14, 96, [("source_id", "PK"), ("name", "UK"), ("base_url", ""), ("auth_type", "")]),
    "RETAILERS": (
        14,
        272,
        [("retailer_id", "PK"), ("source_id", "FK"), ("name", ""), ("country", "")],
    ),
    "INGESTION_RUNS": (
        14,
        462,
        [("run_id", "PK"), ("source_id", "FK"), ("status", ""), ("records_ok", "")],
    ),
    "SEED_PRODUCTS": (
        14,
        652,
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
            ("mpn", ""),
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
            ("embedding", "vec"),
            ("valid_from", ""),
            ("is_current", ""),
        ],
    ),
    "PRODUCT_MATCHES": (
        300,
        700,
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
            ("quantity", ""),
            ("observed_at", "PK"),
        ],
    ),
    "FORECASTS": (
        620,
        540,
        [("forecast_id", "PK"), ("product_id", "FK"), ("yhat", ""), ("forecast_for", "")],
    ),
    "FORECAST_ACCURACY": (
        620,
        700,
        [("id", "PK"), ("product_id", "FK"), ("model", ""), ("mape", "")],
    ),
    "ALERTS": (
        620,
        860,
        [("alert_id", "PK"), ("product_id", "FK"), ("severity", ""), ("sent_at", "")],
    ),
}
BW, TH, LH = 232, 30, 22


def _entity(name, x, y, fields):
    h = TH + len(fields) * LH + 8
    hub = name == "PRODUCTS"
    col, sw = (ACCENT, "2") if hub else ("currentColor", "1.2")
    out = [
        f'<rect x="{x}" y="{y}" width="{BW}" height="{h}" rx="4" fill="none" stroke="{col}" stroke-width="{sw}"/>',
        f'<line x1="{x}" y1="{y + TH}" x2="{x + BW}" y2="{y + TH}" stroke="{col}" stroke-width="{sw}"/>',
        f'<text x="{x + 10}" y="{y + 20}" font-size="14" font-weight="600" fill="{col}">{name}</text>',
    ]
    for i, (f, m) in enumerate(fields):
        ty = y + TH + 17 + i * LH
        out.append(f'<text x="{x + 10}" y="{ty}" font-size="13" opacity=".85">{f}</text>')
        if m:
            out.append(
                f'<text x="{x + BW - 10}" y="{ty}" font-size="11" text-anchor="end" opacity=".55">{m}</text>'
            )
    return "".join(out), h


def fig_er(num: int) -> str:
    boxes, hs = [], {}
    for n, (x, y, f) in ENTITIES.items():
        svg, h = _entity(n, x, y, f)
        boxes.append(svg)
        hs[n] = h

    def cy(n):
        return ENTITIES[n][1] + hs[n] / 2

    def bot(n):
        return ENTITIES[n][1] + hs[n]

    e = []

    def path(d, dash="", w="1.1", arrow=True):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        mk = ' marker-end="url(#ar4)"' if arrow else ""
        e.append(
            f'<path d="{d}" fill="none" stroke="currentColor" stroke-width="{w}" opacity=".5"{da}{mk}/>'
        )

    def lab(x, y, t, anchor="start"):
        e.append(
            f'<text x="{x}" y="{y}" font-size="11" opacity=".6" text-anchor="{anchor}">{t}</text>'
        )

    path(f"M 246 {cy('SOURCES')} H 273 V {cy('PRODUCTS')} H 300")
    lab(250, cy("SOURCES") - 7, "1:N")
    path(f"M 130 {bot('SOURCES')} V {ENTITIES['RETAILERS'][1]}")
    lab(136, bot("SOURCES") + 40, "1:N")
    path(f"M 130 {bot('RETAILERS')} V {ENTITIES['INGESTION_RUNS'][1]}")
    lab(136, bot("RETAILERS") + 40, "1:N")
    path(f"M 416 {bot('PRODUCTS')} V {ENTITIES['PRODUCT_VERSIONS'][1]}")
    lab(422, bot("PRODUCTS") + 46, "1:N  attribute history")
    path(f"M 416 {bot('PRODUCT_VERSIONS')} V {ENTITIES['PRODUCT_MATCHES'][1]}")
    lab(422, bot("PRODUCT_VERSIONS") + 46, "1:N x2  (side a, side b)")

    BUS = 556
    tgts = ["PRICE_EVENTS", "STOCK_EVENTS", "FORECASTS", "FORECAST_ACCURACY", "ALERTS"]
    path(f"M 532 {cy('PRODUCTS')} H {BUS}", arrow=False)
    path(f"M {BUS} {cy(tgts[0])} V {cy(tgts[-1])}", w="1.4", arrow=False)
    for t in tgts:
        path(f"M {BUS} {cy(t)} H 620")
    e.append(
        f'<text x="{BUS}" y="96" font-size="11" opacity=".6" text-anchor="middle">product_id 1:N</text>'
    )

    RB = 590
    path(f"M 246 {cy('RETAILERS')} H {RB}", dash="5 3", arrow=False)
    path(f"M {RB} {cy('PRICE_EVENTS') + 30} V {cy('STOCK_EVENTS') + 30}", dash="5 3", arrow=False)
    path(f"M {RB} {cy('PRICE_EVENTS') + 30} H 620", dash="5 3")
    path(f"M {RB} {cy('STOCK_EVENTS') + 30} H 620", dash="5 3")
    lab(300, cy("RETAILERS") - 7, "retailer_id 1:N (dashed)")

    svg = (
        '<svg viewBox="0 0 900 1030" role="img" aria-label="Detailed entity relationship diagram. '
        "SOURCES supplies PRODUCTS, RETAILERS and INGESTION_RUNS. PRODUCTS is the hub: it owns "
        "PRODUCT_VERSIONS which carries the vector embedding and relates to PRODUCT_MATCHES, and a "
        "single bus carries product_id into PRICE_EVENTS, STOCK_EVENTS, FORECASTS, FORECAST_ACCURACY "
        "and ALERTS. RETAILERS is referenced by both event tables, shown dashed. SEED_PRODUCTS is "
        'standalone ingestion configuration.">'
        + _defs("ar4").replace("ar4a", "ar4b")
        + '<g font-family="IBM Plex Mono, monospace" fill="currentColor">'
        '<text x="14" y="34" font-size="12" opacity=".6">REFERENCE DATA</text>'
        '<text x="300" y="34" font-size="12" opacity=".6">CORE + ATTRIBUTE HISTORY</text>'
        '<text x="620" y="34" font-size="12" opacity=".6">EVENTS + DERIVED OUTPUT</text>'
        '<line x1="14" y1="44" x2="886" y2="44" stroke="currentColor" stroke-width=".7" opacity=".25"/>'
        + "".join(e)
        + "".join(boxes)
        + '<text x="14" y="1002" font-size="11" opacity=".6">PK primary key &#183; FK foreign key &#183; UK unique &#183; vec = 384-dimension vector column &#183; dashed = retailer_id relationship</text>'
        '<text x="14" y="1018" font-size="11" opacity=".6">price_events and stock_events are range-partitioned by month, so observed_at forms part of their primary key</text>'
        "</g></svg>"
    )
    return _wrap(
        svg,
        num,
        "Entity relationship diagram. <code>products</code> is the hub: every table in the "
        "right-hand column carries <code>product_id</code> as a foreign key, drawn as one bus "
        "rather than five crossing lines. The embedding used for product matching lives on "
        "<code>product_versions</code>, so it versions with the attributes it was derived from.",
        page_break=True,
    )


def fig_dbt(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 420" role="img" aria-label="dbt model lineage. Six staging views read the serving tables. Three intermediate views build the shared join, a daily grain and a latest-price view. Five marts answer business questions and are the only thing downstream consumers read.">',
        _defs("ar5"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append('<text x="12" y="20" font-size="11" opacity=".55">SOURCE TABLES</text>')
    s.append('<text x="232" y="20" font-size="11" opacity=".55">STAGING (views)</text>')
    s.append('<text x="452" y="20" font-size="11" opacity=".55">INTERMEDIATE (views)</text>')
    s.append('<text x="700" y="20" font-size="11" opacity=".55">MARTS (tables)</text>')
    s.append(
        '<line x1="12" y1="30" x2="888" y2="30" stroke="currentColor" stroke-width=".7" opacity=".2"/>'
    )

    src = ["price_events", "products", "product_versions", "retailers", "stock_events", "sources"]
    for i, t in enumerate(src):
        y = 48 + i * 40
        s.append(
            f'<rect x="12" y="{y}" width="150" height="30" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".75"/>'
        )
        s.append(f'<text x="87" y="{y + 19}" text-anchor="middle" font-size="11">{t}</text>')
        s.append(f'<text x="176" y="{y + 19}" font-size="11" opacity=".5">&#8594;</text>')
        s.append(
            f'<rect x="232" y="{y}" width="150" height="30" rx="3" fill="none" stroke="currentColor" stroke-width="1"/>'
        )
        s.append(f'<text x="307" y="{y + 19}" text-anchor="middle" font-size="11">stg_{t}</text>')

    inter = [
        ("int_price_observations", "the one join every mart reuses", 60),
        ("int_price_daily", "one price per product/retailer/day", 150),
        ("int_price_latest", "newest price + staleness", 240),
    ]
    for name, sub, y in inter:
        s.append(
            f'<rect x="452" y="{y}" width="196" height="46" rx="3" fill="none" stroke="currentColor" stroke-width="1.2"/>'
        )
        s.append(
            f'<text x="550" y="{y + 19}" text-anchor="middle" font-size="11.5" font-weight="600">{name}</text>'
        )
        s.append(
            f'<text x="550" y="{y + 35}" text-anchor="middle" font-size="10" opacity=".7">{sub}</text>'
        )

    marts = [
        ("mart_price_trend", 48),
        ("mart_price_volatility", 105),
        ("mart_price_gap_vs_own", 162),
        ("mart_undercut_alerts", 219),
        ("mart_out_of_stock_frequency", 276),
    ]
    for name, y in marts:
        s.append(
            f'<rect x="700" y="{y}" width="188" height="40" rx="3" fill="none" stroke="{ACCENT}" stroke-width="1.4"/>'
        )
        s.append(
            f'<text x="794" y="{y + 25}" text-anchor="middle" font-size="11" fill="{ACCENT}">{name}</text>'
        )

    a = 'stroke="currentColor" stroke-width="1" opacity=".55" marker-end="url(#ar5)"'
    s.append(f'<path d="M 382 63 H 420 V 83 H 448" fill="none" {a}/>')
    s.append(f'<path d="M 382 223 H 420 V 83 H 448" fill="none" {a}/>')
    s.append(f'<path d="M 550 106 V 150" fill="none" {a}/>')
    s.append(f'<path d="M 550 196 V 240" fill="none" {a}/>')
    s.append(f'<path d="M 648 173 H 672 V 68 H 696" fill="none" {a}/>')
    s.append(f'<path d="M 648 173 H 672 V 125 H 696" fill="none" {a}/>')
    s.append(f'<path d="M 648 263 H 672 V 182 H 696" fill="none" {a}/>')
    s.append(f'<path d="M 794 202 V 219" fill="none" {a}/>')
    s.append(f'<path d="M 382 183 H 420 V 296 H 696" fill="none" {a}/>')

    s.append(
        '<rect x="452" y="330" width="436" height="56" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="5 3" opacity=".6"/>'
    )
    s.append(
        '<text x="468" y="352" font-size="12" font-weight="600">102 data tests run with the models</text>'
    )
    s.append(
        '<text x="468" y="370" font-size="11" opacity=".75">Schema, referential integrity, accepted ranges, and cross-field invariants.</text>'
    )
    s.append(
        '<text x="12" y="404" font-size="10" opacity=".6">Consumers read only marts. A rule such as "what counts as an undercut" is therefore defined exactly once.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Transformation lineage. Staging cleans, intermediate joins once and defines the daily "
        "grain, and marts answer business questions. Tests run with the build, so a failing "
        "assertion stops bad numbers reaching the dashboard.",
    )


def fig_forecast(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 400" role="img" aria-label="Forecasting pipeline. Daily price series are read from a mart, resampled to a regular daily grid, and filtered for length and recency. Three models are fitted: AutoETS, AutoARIMA and a SeasonalNaive baseline. Rolling origin cross validation scores each on unseen windows, the lowest error model is selected per series, and forecasts with prediction intervals plus the accuracy of every model are written back to the database.">',
        _defs("ar6"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append(_box(12, 46, 168, 74, "mart_price_trend", ["daily series", "per product+retailer"]))
    s.append(
        _box(
            12,
            160,
            168,
            88,
            "Prepare",
            ["resample to daily grid", "forward-fill gaps", "drop short / stale series"],
        )
    )
    s.append(
        _box(
            240,
            46,
            190,
            130,
            "Fit candidates",
            ["AutoETS", "AutoARIMA", "SeasonalNaive (baseline)", "", "statsforecast"],
        )
    )
    s.append(
        _box(
            240,
            210,
            190,
            88,
            "Backtest",
            ["rolling-origin CV", "3 windows, 7-day horizon", "scored on unseen data"],
        )
    )
    s.append(
        _box(
            490,
            120,
            190,
            88,
            "Select champion",
            ["lowest backtested error", "baseline retained unless", "genuinely beaten"],
            accent=True,
        )
    )
    s.append(_box(740, 46, 150, 74, "forecasts", ["yhat + interval", "per date"]))
    s.append(
        _box(
            740,
            160,
            150,
            74,
            "forecast_accuracy",
            ["MAPE per model", "kept for all, not", "only the winner"],
        )
    )
    a = 'stroke="currentColor" stroke-width="1.2" marker-end="url(#ar6)"'
    ac = f'stroke="{ACCENT}" stroke-width="1.5" marker-end="url(#ar6a)"'
    s.append(f'<path d="M 96 120 V 160" fill="none" {a}/>')
    s.append(f'<path d="M 180 200 H 210 V 110 H 236" fill="none" {a}/>')
    s.append(f'<path d="M 335 176 V 210" fill="none" {a}/>')
    s.append(f'<path d="M 430 254 H 460 V 164 H 486" fill="none" {a}/>')
    s.append(f'<path d="M 680 150 H 710 V 83 H 736" fill="none" {ac}/>')
    s.append(f'<path d="M 680 178 H 710 V 197 H 736" fill="none" {a}/>')
    s.append(
        '<rect x="12" y="290" width="668" height="76" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="5 3" opacity=".6"/>'
    )
    s.append(
        '<text x="28" y="312" font-size="12" font-weight="600">Why a baseline always competes</text>'
    )
    s.append(
        '<text x="28" y="330" font-size="11" opacity=".75">Retail prices are close to a random walk over short horizons. A model that cannot beat</text>'
    )
    s.append(
        '<text x="28" y="346" font-size="11" opacity=".75">"tomorrow looks like today" is not worth its cost, and without the baseline in the comparison</text>'
    )
    s.append(
        '<text x="28" y="362" font-size="11" opacity=".75">there is no way to tell. Scoring ignores forward-filled days so the metric measures forecasting.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Forecasting module. Accuracy is measured by refitting on successive windows and "
        "scoring predictions the model has not seen, which is what makes the reported error "
        "meaningful rather than flattering.",
    )


def fig_matching(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 430" role="img" aria-label="Product matching pipeline. Product title, brand and category are combined and embedded into a 384 dimension vector stored in PostgreSQL with pgvector. Exact barcode matches are accepted outright. Otherwise candidates are restricted by category, an approximate nearest neighbour search over an HNSW index produces similarity scores, and the score is banded: at or above 0.92 accepted automatically, between 0.80 and 0.92 sent for human review in Streamlit, below 0.80 rejected.">',
        _defs("ar7"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append(_box(12, 46, 176, 74, "Product text", ["title | brand | category"]))
    s.append(
        _box(
            12,
            156,
            176,
            88,
            "fastembed (ONNX)",
            ["all-MiniLM-L6-v2", "384 dimensions", "no PyTorch runtime"],
        )
    )
    s.append(
        _box(
            12,
            280,
            176,
            88,
            "pgvector column",
            ["product_versions", ".embedding", "HNSW index, cosine"],
            accent=True,
        )
    )
    s.append(_box(250, 46, 190, 74, "Exact identifier", ["barcode / MPN match"], accent=True))
    s.append(_box(250, 156, 190, 74, "Blocking", ["restrict to same category"]))
    s.append(
        _box(
            250,
            266,
            190,
            88,
            "ANN search",
            ["top-k nearest neighbours", "cosine similarity", "over HNSW index"],
        )
    )
    s.append(_box(510, 156, 176, 88, "Score band", ["compare similarity", "against thresholds"]))
    s.append(_box(730, 40, 158, 66, "Accepted", ["&#8805; 0.92"], accent=True))
    s.append(_box(730, 130, 158, 78, "Human review", ["0.80 &#8211; 0.92", "Streamlit screen"]))
    s.append(_box(730, 232, 158, 66, "Rejected", ["&lt; 0.80"], dashed=True))
    s.append(_box(730, 330, 158, 66, "product_matches", ["decision + method"]))
    a = 'stroke="currentColor" stroke-width="1.2" marker-end="url(#ar7)"'
    ac = f'stroke="{ACCENT}" stroke-width="1.5" marker-end="url(#ar7a)"'
    s.append(f'<path d="M 100 120 V 156" fill="none" {a}/>')
    s.append(f'<path d="M 100 244 V 280" fill="none" {a}/>')
    s.append(f'<path d="M 188 310 H 214 V 310 H 246" fill="none" {a}/>')
    s.append(f'<path d="M 188 83 H 246" fill="none" {ac}/>')
    s.append(f'<path d="M 440 83 H 700 V 73 H 726" fill="none" {ac}/>')
    s.append(
        '<text x="470" y="76" font-size="10" fill="' + ACCENT + '">identifier wins outright</text>'
    )
    s.append(f'<path d="M 345 230 V 266" fill="none" {a}/>')
    s.append(f'<path d="M 440 310 H 470 V 200 H 506" fill="none" {a}/>')
    s.append(f'<path d="M 686 180 H 706 V 169 H 726" fill="none" {a}/>')
    s.append(f'<path d="M 686 200 H 706 V 265 H 726" fill="none" {a}/>')
    s.append(
        '<path d="M 809 208 V 232" fill="none" stroke="currentColor" stroke-width="1" opacity=".4"/>'
    )
    s.append(
        '<path d="M 809 106 V 130" fill="none" stroke="currentColor" stroke-width="1" opacity=".4"/>'
    )
    s.append(f'<path d="M 809 298 V 330" fill="none" {a}/>')
    s.append(
        '<text x="12" y="408" font-size="10" opacity=".6">An exact barcode is a fact; a similarity score is an opinion. Identifiers therefore bypass the vector path entirely.</text>'
    )
    s.append(
        '<text x="12" y="422" font-size="10" opacity=".6">Reviewer decisions are stored with reviewer and timestamp, forming the labelled set that precision and recall are later measured against.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Product matching. This is where the vector database capability is used: embeddings "
        "live in a <code>pgvector</code> column on <code>product_versions</code>, indexed with "
        "HNSW for approximate nearest-neighbour search.",
    )


def fig_ai(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 400" role="img" aria-label="Weekly brief generation. A facts builder queries the marts and produces a closed set of numbers. Three CrewAI agents, an analyst, a forecast interpreter and a writer, receive that payload and produce prose. A numeric guard checks every number in the prose against the facts. If all numbers are supported the narrated brief is published; if any number is unsupported the narrated version is discarded and a deterministic rendering of the same facts is published instead.">',
        _defs("ar8"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append(
        _box(
            12,
            60,
            168,
            88,
            "dbt marts",
            ["undercuts, volatility,", "movers, forecasts,", "data quality"],
        )
    )
    s.append(
        _box(
            12,
            190,
            168,
            88,
            "Facts payload",
            ["closed set of numbers", "JSON, not free text"],
            accent=True,
        )
    )
    s.append(_box(240, 40, 178, 62, "Analyst agent", ["picks what matters"]))
    s.append(_box(240, 120, 178, 62, "Forecast agent", ["explains confidence"]))
    s.append(_box(240, 200, 178, 62, "Writer agent", ["composes the brief"]))
    s.append(
        '<rect x="228" y="26" width="202" height="252" rx="5" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 3" opacity=".5"/>'
    )
    s.append(
        '<text x="329" y="296" text-anchor="middle" font-size="11" opacity=".6">CrewAI &#183; sequential process</text>'
    )
    s.append(
        '<polygon points="480,154 580,110 680,154 580,198" fill="none" stroke="'
        + ACCENT
        + '" stroke-width="1.6"/>'
    )
    s.append(
        f'<text x="580" y="150" text-anchor="middle" font-size="11.5" fill="{ACCENT}">every number</text>'
    )
    s.append(
        f'<text x="580" y="165" text-anchor="middle" font-size="11.5" fill="{ACCENT}">present in facts?</text>'
    )
    s.append(_box(730, 46, 158, 66, "Narrated brief", ["published"], accent=True))
    s.append(_box(730, 196, 158, 78, "Deterministic brief", ["same facts,", "rendered directly"]))
    a = 'stroke="currentColor" stroke-width="1.2" marker-end="url(#ar8)"'
    ac = f'stroke="{ACCENT}" stroke-width="1.5" marker-end="url(#ar8a)"'
    s.append(f'<path d="M 96 148 V 190" fill="none" {a}/>')
    s.append(f'<path d="M 180 216 H 206 V 71 H 236" fill="none" {a}/>')
    s.append(f'<path d="M 180 234 H 206 V 151 H 236" fill="none" {a}/>')
    s.append(f'<path d="M 180 250 H 206 V 231 H 236" fill="none" {a}/>')
    s.append(f'<path d="M 418 231 H 450 V 154 H 476" fill="none" {a}/>')
    s.append(f'<path d="M 580 110 V 79 H 726" fill="none" {ac}/>')
    s.append(f'<text x="600" y="72" font-size="10" fill="{ACCENT}">all supported</text>')
    s.append(f'<path d="M 580 198 V 235 H 726" fill="none" {a}/>')
    s.append(
        '<text x="600" y="228" font-size="10" opacity=".7">any unsupported &#8212; discard narration</text>'
    )
    s.append(
        '<path d="M 180 234 H 200 V 320 H 700 V 262 H 726" fill="none" stroke="currentColor" stroke-width="1" opacity=".45" stroke-dasharray="5 3" marker-end="url(#ar8)"/>'
    )
    s.append(
        '<text x="300" y="334" font-size="10" opacity=".6">the same facts also feed the deterministic path directly</text>'
    )
    s.append(
        '<text x="12" y="368" font-size="10" opacity=".6">The agents never query the database. They receive a fixed payload, which is what makes the check decidable.</text>'
    )
    s.append(
        '<text x="12" y="384" font-size="10" opacity=".6">Worst case is a plainer brief, never one containing a figure the data does not support.</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "AI module. CrewAI supplies the writing; the guardrail supplies the trust. Because the "
        "agents see a closed fact set rather than a database connection, every number they "
        "write can be checked mechanically.",
    )


def fig_ui(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 460" role="img" aria-label="User interface surfaces. The Metabase dashboard shows scorecards, an undercut table, a volatility leaderboard, price trend charts and forecast accuracy. The Streamlit review screen shows candidate product pairs for approval. The REST API exposes seven endpoints. Alerts are delivered to Slack or email. The weekly brief is a written document. All five surfaces read from the marts.">',
        _defs("ar9"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append(_box(360, 20, 180, 54, "dbt marts", ["single source for all UI"], accent=True))

    s.append(
        '<rect x="12" y="110" width="420" height="230" rx="5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    )
    s.append('<text x="24" y="132" font-size="12.5" font-weight="600">Metabase dashboard</text>')
    for i, (lbl, val) in enumerate(
        [("Products", "3,932"), ("Retailers", "157"), ("Undercuts", "108"), ("Events", "8,433")]
    ):
        x = 24 + i * 100
        s.append(
            f'<rect x="{x}" y="144" width="90" height="42" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".6"/>'
        )
        s.append(f'<text x="{x + 8}" y="159" font-size="9" opacity=".6">{lbl}</text>')
        s.append(f'<text x="{x + 8}" y="177" font-size="14" font-weight="600">{val}</text>')
    s.append(
        '<rect x="24" y="198" width="196" height="60" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".6"/>'
    )
    s.append('<text x="32" y="214" font-size="9.5" opacity=".7">Undercut table</text>')
    for i in range(3):
        s.append(
            f'<line x1="32" y1="{226 + i * 11}" x2="150" y2="{226 + i * 11}" stroke="currentColor" stroke-width="3" opacity=".22"/>'
        )
        s.append(
            f'<line x1="176" y1="{226 + i * 11}" x2="212" y2="{226 + i * 11}" stroke="{ACCENT}" stroke-width="3" opacity=".55"/>'
        )
    s.append(
        '<rect x="232" y="198" width="188" height="60" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".6"/>'
    )
    s.append('<text x="240" y="214" font-size="9.5" opacity=".7">Volatility leaderboard</text>')
    for i in range(3):
        s.append(
            f'<rect x="240" y="{221 + i * 11}" width="{140 - i * 34}" height="6" rx="2" fill="{ACCENT}" opacity=".45"/>'
        )
    s.append(
        '<rect x="24" y="268" width="396" height="58" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".6"/>'
    )
    s.append(
        '<text x="32" y="284" font-size="9.5" opacity=".7">Price trend by retailer &#183; forecast accuracy</text>'
    )
    s.append(
        '<polyline points="34,318 74,306 114,312 154,296 194,302 234,290 274,296 314,284 354,290 410,280" fill="none" stroke="'
        + ACCENT
        + '" stroke-width="1.6" opacity=".8"/>'
    )

    s.append(
        '<rect x="460" y="110" width="200" height="112" rx="5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    )
    s.append('<text x="472" y="132" font-size="12.5" font-weight="600">Streamlit review</text>')
    s.append(
        '<rect x="472" y="144" width="82" height="46" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".55"/>'
    )
    s.append(
        '<rect x="566" y="144" width="82" height="46" rx="3" fill="none" stroke="currentColor" stroke-width="1" opacity=".55"/>'
    )
    s.append(
        '<text x="513" y="170" text-anchor="middle" font-size="9.5" opacity=".65">product A</text>'
    )
    s.append(
        '<text x="607" y="170" text-anchor="middle" font-size="9.5" opacity=".65">product B</text>'
    )
    s.append(
        f'<text x="560" y="208" text-anchor="middle" font-size="9" fill="{ACCENT}">same / different &#183; 0.87</text>'
    )

    s.append(
        '<rect x="686" y="110" width="202" height="112" rx="5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    )
    s.append('<text x="698" y="132" font-size="12.5" font-weight="600">REST API</text>')
    for i, ep in enumerate(
        ["/products", "/prices/{id}", "/forecasts/{id}", "/undercuts", "/alerts", "/matches/review"]
    ):
        s.append(f'<text x="698" y="{150 + i * 12}" font-size="9.5" opacity=".7">{ep}</text>')

    s.append(
        '<rect x="460" y="240" width="200" height="100" rx="5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    )
    s.append('<text x="472" y="262" font-size="12.5" font-weight="600">Alerts</text>')
    s.append('<text x="472" y="282" font-size="10" opacity=".72">Slack / email delivery</text>')
    s.append('<text x="472" y="298" font-size="10" opacity=".72">severity + evidence age</text>')
    s.append('<text x="472" y="314" font-size="10" opacity=".72">deduplicated per product</text>')
    s.append('<text x="472" y="330" font-size="10" opacity=".72">stale evidence withheld</text>')

    s.append(
        '<rect x="686" y="240" width="202" height="100" rx="5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    )
    s.append('<text x="698" y="262" font-size="12.5" font-weight="600">Weekly brief</text>')
    s.append('<text x="698" y="282" font-size="10" opacity=".72">Markdown document</text>')
    s.append('<text x="698" y="298" font-size="10" opacity=".72">top movers + undercuts</text>')
    s.append('<text x="698" y="314" font-size="10" opacity=".72">forecast commentary</text>')
    s.append('<text x="698" y="330" font-size="10" opacity=".72">numerically guarded</text>')

    a = f'stroke="{ACCENT}" stroke-width="1.3" opacity=".75" marker-end="url(#ar9a)"'
    s.append(f'<path d="M 400 74 V 92 H 222 V 106" fill="none" {a}/>')
    s.append(f'<path d="M 440 74 V 92 H 560 V 106" fill="none" {a}/>')
    s.append(f'<path d="M 470 74 V 92 H 787 V 106" fill="none" {a}/>')
    s.append(
        f'<path d="M 460 74 V 92 H 660 V 236" fill="none" stroke="{ACCENT}" stroke-width="1" opacity=".35"/>'
    )
    s.append(
        '<text x="12" y="368" font-size="10" opacity=".6">Five surfaces, one definition. Because each reads the same marts, the undercut count on the dashboard, in the API and in the brief cannot disagree.</text>'
    )

    s.append(
        '<rect x="12" y="384" width="876" height="62" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="5 3" opacity=".55"/>'
    )
    s.append(
        '<text x="28" y="404" font-size="11.5" font-weight="600">Who uses which surface</text>'
    )
    s.append(
        '<text x="28" y="422" font-size="10.5" opacity=".75">Category manager &#8594; dashboard and weekly brief &#183; Pricing analyst &#8594; alerts and API &#183; Data steward &#8594; review screen</text>'
    )
    s.append(
        '<text x="28" y="438" font-size="10.5" opacity=".75">Engineer &#8594; API and pipeline observability</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Presentation layer. What each audience sees, and where it comes from. Every surface "
        "is downstream of the same tested marts.",
    )


def fig_aws(num: int) -> str:
    s = [
        '<svg viewBox="0 0 900 470" role="img" aria-label="AWS deployment architecture in the Mumbai region. A virtual private cloud contains a public subnet holding an EC2 application host running the API, worker and scheduler containers, and two private subnets in different availability zones holding the RDS PostgreSQL instance. The application host reads secrets from SSM Parameter Store, writes raw payloads to S3, and sends logs and metrics to CloudWatch. The database has no public address and accepts connections only from the application security group.">',
        _defs("ar10"),
        '<g font-family="IBM Plex Mono, monospace" fill="currentColor">',
    ]
    s.append(
        '<rect x="12" y="40" width="600" height="330" rx="6" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    )
    s.append(
        '<text x="26" y="62" font-size="12" font-weight="600">VPC 10.20.0.0/16 &#183; ap-south-1 (Mumbai)</text>'
    )

    s.append(
        '<rect x="30" y="78" width="286" height="128" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 3" opacity=".7"/>'
    )
    s.append('<text x="42" y="96" font-size="11" opacity=".7">Public subnet &#183; AZ-a</text>')
    s.append(
        _box(
            44,
            106,
            258,
            88,
            "EC2 t4g.small",
            ["Docker Compose", "API &#183; worker &#183; scheduler", "IMDSv2, no SSH by default"],
            accent=True,
        )
    )

    s.append(
        '<rect x="30" y="222" width="566" height="130" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 3" opacity=".7"/>'
    )
    s.append(
        '<text x="42" y="240" font-size="11" opacity=".7">Private subnets &#183; AZ-a + AZ-b &#183; no internet route</text>'
    )
    s.append(
        _box(
            44,
            250,
            258,
            88,
            "RDS PostgreSQL 16",
            [
                "db.t4g.micro, gp3, encrypted",
                "TLS enforced, private only",
                "automated backups, 7 days",
            ],
        )
    )
    s.append(
        _box(
            322,
            250,
            258,
            88,
            "pgvector extension",
            ["384-dim embeddings", "HNSW index", "same engine, no extra store"],
        )
    )

    s.append(
        _box(
            340,
            106,
            256,
            88,
            "Security groups",
            ["app SG: outbound only", "db SG: 5432 from app SG", "referenced by group, not IP"],
        )
    )

    s.append(
        _box(
            650,
            60,
            234,
            74,
            "S3 bucket",
            ["raw payload zone", "versioned, encrypted, lifecycle"],
            accent=True,
        )
    )
    s.append(
        _box(
            650,
            150,
            234,
            74,
            "SSM Parameter Store",
            ["credentials + API keys", "SecureString, never in code"],
        )
    )
    s.append(
        _box(650, 240, 234, 74, "CloudWatch", ["logs, metrics, alarms", "budget alarm on spend"])
    )
    s.append(_box(650, 330, 234, 62, "IAM role", ["least privilege, scoped"]))

    a = 'stroke="currentColor" stroke-width="1.2" marker-end="url(#ar10)"'
    s.append(f'<path d="M 173 194 V 250" fill="none" {a}/>')
    s.append('<text x="182" y="216" font-size="10" opacity=".7">TLS 5432</text>')
    s.append(f'<path d="M 302 150 H 336" fill="none" {a}/>')
    s.append(f'<path d="M 612 130 H 630 V 97 H 646" fill="none" {a}/>')
    s.append(f'<path d="M 612 150 H 630 V 187 H 646" fill="none" {a}/>')
    s.append(f'<path d="M 612 170 H 626 V 277 H 646" fill="none" {a}/>')
    s.append(
        '<text x="12" y="386" font-size="10" opacity=".6">No NAT gateway: nothing in the private subnets needs</text>'
    )
    s.append(
        '<text x="12" y="398" font-size="10" opacity=".6">outbound internet, and a NAT would cost more than the rest of the stack.</text>'
    )

    s.append(
        '<rect x="12" y="404" width="876" height="56" rx="4" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="5 3" opacity=".55"/>'
    )
    s.append('<text x="28" y="424" font-size="11.5" font-weight="600">Delivery</text>')
    s.append(
        '<text x="28" y="442" font-size="10.5" opacity=".75">Terraform defines every resource above &#183; GitHub Actions runs lint, tests, dbt and plan validation &#183; Alembic applies migrations on deploy</text>'
    )
    s.append(
        '<text x="28" y="456" font-size="10.5" opacity=".75">Estimated run cost: USD 28&#8211;36 per month (approximately INR 2,350&#8211;3,020)</text>'
    )
    s.append("</g></svg>")
    return _wrap(
        "".join(s),
        num,
        "Target AWS deployment. The database is unreachable from the internet by construction: "
        "it sits in subnets with no internet route and accepts traffic only from the "
        "application's security group.",
    )
