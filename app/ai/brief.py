"""Weekly pricing brief.

Two paths, same facts:

* **Deterministic** (default) -- renders the facts as Markdown. No API key, no cost, no
  chance of a fabricated number. This is what runs today.
* **LLM-narrated** (optional) -- a CrewAI crew turns the same facts into prose. The
  output is passed through `guard.validate_brief`, and **falls back to the deterministic
  brief if any number in it is not present in the facts.**

That fallback is the point. An unvalidated LLM brief is a liability in a pricing context:
it reads authoritatively whether or not the figures are real. Making the deterministic
render the default -- and the guard a hard gate rather than a warning -- means the worst
case is a plainer brief, never a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.facts import WeeklyFacts, collect_weekly_facts
from app.ai.guard import GuardResult, validate_brief
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class BriefResult:
    body: str
    source: str  # "deterministic" | "llm" | "llm-cached"
    guard: GuardResult | None = None
    facts: WeeklyFacts | None = None

    def summary(self) -> dict:
        return {
            "source": self.source,
            "length": len(self.body),
            "guard_ok": None if self.guard is None else self.guard.ok,
            "guard_checked": None if self.guard is None else self.guard.checked,
        }


def _money(value, currency: str) -> str:
    return "n/a" if value is None else f"{value:.2f} {currency}"


def render_markdown(facts: WeeklyFacts) -> str:
    """Deterministic brief. Every number comes straight from the facts payload."""
    f = facts
    lines: list[str] = [
        f"# Weekly Pricing Brief — {f.generated_at}",
        "",
        f"Covering the last {f.period_days} days.",
        "",
        "## At a glance",
        "",
        f"- Products tracked: {f.totals.get('products_tracked', 0)}",
        f"- Retailers tracked: {f.totals.get('retailers_tracked', 0)}",
        f"- Price observations this period: {f.totals.get('price_events_this_period', 0)}",
        f"- Active undercuts: {f.totals.get('active_undercuts', 0)}",
        "",
    ]

    lines += ["## Where we are being undercut", ""]
    if not f.top_undercuts:
        lines += ["No competitor is currently priced below our catalogue.", ""]
    else:
        lines += [
            "| Product | Retailer | Ours | Theirs | Gap | Severity | Evidence |",
            "|---|---|---|---|---|---|---|",
        ]
        for u in f.top_undercuts:
            lines.append(
                f"| {u['product_name']} | {u['retailer_name']} "
                f"| {_money(u['our_price'], u['currency'])} "
                f"| {_money(u['competitor_price'], u['currency'])} "
                f"| {u['gap_pct']}% | {u['severity']} "
                f"| {u['confidence']} ({u['days_stale']}d old) |"
            )
        lines.append("")

    lines += ["## Most volatile prices", ""]
    if not f.most_volatile:
        lines += ["Not enough history yet to measure dispersion.", ""]
    else:
        lines += ["| Product | Retailer | Mean | Range | CV | Band |", "|---|---|---|---|---|---|"]
        for v in f.most_volatile:
            lines.append(
                f"| {v['title']} | {v['retailer_name']} "
                f"| {_money(v['mean_price'], v['currency'])} "
                f"| {v['min_price']}–{v['max_price']} "
                f"| {v['coefficient_of_variation']} | {v['volatility_band']} |"
            )
        lines.append("")

    lines += ["## Biggest movers", ""]
    if not f.biggest_movers:
        lines += ["No price changes recorded in this period.", ""]
    else:
        for m in f.biggest_movers:
            lines.append(
                f"- **{m['title']}** at {m['retailer_name']}: "
                f"{m['prev_price']} → {m['close_price']} {m['currency']} "
                f"({m['change_pct']}%) on {m['observed_date']}"
            )
        lines.append("")

    lines += ["## Forecasts", ""]
    fs = f.forecast_summary
    if not fs.get("forecast_rows"):
        lines += ["No current forecasts.", ""]
    else:
        lines += [
            f"- {fs['forecast_rows']} forecast points across {fs['products_forecast']} products",
            f"- Horizon: {fs['horizon_start']} to {fs['horizon_end']}",
            "",
        ]
    if f.forecast_accuracy:
        lines += ["| Model | Series | Avg MAPE | Worst |", "|---|---|---|---|"]
        for a in f.forecast_accuracy:
            lines.append(
                f"| {a['model']} | {a['series']} | {a['avg_mape']}% | {a['worst_mape']}% |"
            )
        lines.append("")

    q = f.data_quality
    lines += [
        "## Data quality",
        "",
        f"- Latest observation: {q.get('latest_observation')}",
        f"- Matches awaiting review: {q.get('matches_pending_review', 0)}",
        f"- Matches approved: {q.get('matches_approved', 0)}",
        f"- Failed ingestion runs this period: {q.get('failed_runs', 0)}",
        "",
    ]
    return "\n".join(lines)


def generate_brief(session: Session, period_days: int = 7, use_llm: bool = False) -> BriefResult:
    """Produce the weekly brief, preferring a validated LLM version when enabled."""
    facts = collect_weekly_facts(session, period_days=period_days)
    deterministic = render_markdown(facts)

    if not use_llm:
        return BriefResult(body=deterministic, source="deterministic", facts=facts)

    try:
        from app.ai import cache  # noqa: PLC0415
        from app.ai.crew import _require_llm, narrate_with_crew  # noqa: PLC0415

        # Checked before the model is reached. The brief is a function of the facts, so
        # unchanged facts justify the previous prose -- and a request not made is the
        # only one guaranteed not to cost anything.
        fingerprint = cache.facts_fingerprint(facts, _require_llm())
        cached = cache.get(fingerprint)
        if cached is not None:
            guard = validate_brief(cached, facts.all_numbers())
            if guard.ok:
                return BriefResult(body=cached, source="llm-cached", guard=guard, facts=facts)
            # Re-validated rather than trusted. The guard is cheap, and the facts are
            # what the cache is keyed on, so a hit that no longer validates means the
            # key is wrong -- fall through and narrate again rather than serve it.
            log.warning("brief.cache_rejected", fingerprint=fingerprint)

        narrated = narrate_with_crew(facts)
    except Exception as exc:  # noqa: BLE001 - never let the crew break the brief
        log.warning("brief.crew_unavailable", error=str(exc))
        return BriefResult(body=deterministic, source="deterministic", facts=facts)

    guard = validate_brief(narrated, facts.all_numbers())
    if not guard.ok:
        log.error("brief.llm_rejected", unsupported=guard.unsupported)
        return BriefResult(body=deterministic, source="deterministic", guard=guard, facts=facts)

    cache.put(fingerprint, narrated)
    return BriefResult(body=narrated, source="llm", guard=guard, facts=facts)
