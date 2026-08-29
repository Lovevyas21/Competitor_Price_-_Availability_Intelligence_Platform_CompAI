"""Command-line entrypoint.

python -m app.cli sources
python -m app.cli ingest openprices --limit 200
python -m app.cli status
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import text

from app.clients.registry import CLIENTS
from app.core.db import session_scope
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.ingestion.runner import ingest_seeds, ingest_source, seed_from_source


def cmd_sources(_: argparse.Namespace) -> int:
    for name, cls in sorted(CLIENTS.items()):
        client = cls()
        mark = "ready" if client.is_available() else "needs credentials"
        print(f"  {name:<14} {cls.auth_type:<8} {mark:<18} {cls.base_url}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    if args.seeds:
        result = ingest_seeds(args.source, max_products=args.limit)
    else:
        result = ingest_source(args.source, limit=args.limit)
    print(json.dumps(result.summary(), indent=2, default=str))
    return 0 if result.status == "success" else 1


def cmd_seed(args: argparse.Namespace) -> int:
    seeded = seed_from_source(args.source, limit=args.limit, tier=args.tier)
    if not seeded:
        print(f"{args.source}: source cannot rank its catalogue; seed manually")
        return 1
    print(f"seeded {len(seeded)} SKUs for {args.source} (tier {args.tier})")
    for external_id, count in seeded[:10]:
        print(f"  {external_id:>16}  {count} upstream observations")
    return 0


STATUS_SQL = """
select s.name as source,
       count(distinct p.product_id) as products,
       count(pe.event_id)           as price_events,
       min(pe.observed_at)::date    as earliest,
       max(pe.observed_at)::date    as latest,
       count(distinct pe.retailer_id) as retailers
from sources s
left join products p     on p.source_id = s.source_id
left join price_events pe on pe.product_id = p.product_id
group by s.name
order by s.name
"""


def cmd_status(_: argparse.Namespace) -> int:
    with session_scope() as session:
        rows = session.execute(text(STATUS_SQL)).mappings().all()
        runs = (
            session.execute(
                text("""
                select r.run_id, s.name, r.status, r.records_ok, r.started_at
                from ingestion_runs r join sources s on s.source_id = r.source_id
                order by r.run_id desc limit 5
            """)
            )
            .mappings()
            .all()
        )

    if not rows:
        print("no sources ingested yet")
        return 0

    print(f"{'source':<14}{'products':>9}{'events':>9}{'retailers':>11}  {'range'}")
    for r in rows:
        span = f"{r['earliest']} -> {r['latest']}" if r["earliest"] else "-"
        print(
            f"{r['source']:<14}{r['products']:>9}{r['price_events']:>9}{r['retailers']:>11}  {span}"
        )

    print("\nrecent runs:")
    for r in runs:
        print(f"  #{r['run_id']:<4} {r['name']:<14} {r['status']:<9} ok={r['records_ok']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, pretty=settings.env == "dev")

    parser = argparse.ArgumentParser(prog="cpi", description="Competitor price intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list configured sources").set_defaults(func=cmd_sources)

    p_ingest = sub.add_parser("ingest", help="run one ingestion cycle")
    p_ingest.add_argument("source", choices=sorted(CLIENTS))
    p_ingest.add_argument("--limit", type=int, default=100)
    p_ingest.add_argument(
        "--seeds",
        action="store_true",
        help="fetch full history for seeded SKUs (deep) instead of the broad feed",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_seed = sub.add_parser("seed", help="record the best-tracked SKUs in seed_products")
    p_seed.add_argument("source", choices=sorted(CLIENTS))
    p_seed.add_argument("--limit", type=int, default=25)
    p_seed.add_argument("--tier", type=int, default=1, choices=(1, 2, 3))
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("status", help="warehouse summary").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
