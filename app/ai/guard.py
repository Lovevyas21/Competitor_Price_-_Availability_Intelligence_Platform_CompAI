"""Numeric guardrail for generated text.

The failure mode this exists to stop: an LLM writes "Intermarche undercut us by 34%"
when the real figure is 33.7%, or invents a retailer that had a bad week. The number
looks right, reads fluently, and is wrong -- and a pricing decision gets made on it.

The rule is blunt on purpose: **every number appearing in the brief must exist in the
facts payload.** Not "approximately", not "within tolerance" -- present. If the writer
wants to say something, it must be grounded in a value the SQL produced.

Dates, percentages written as words, and ordinary list numbering would produce false
alarms, so they are excluded explicitly rather than by loosening the rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)

#: Numbers with optional sign, thousands separators and decimals.
#:
#: The comma-grouped alternative REQUIRES at least one group (`+`, not `*`). With `*` it
#: matches a bare run of up to three digits, so "1309" was read as 130 and 9, and
#: "5885d" as 588 and 5 -- producing phantom "unsupported" numbers. The plain-number
#: alternative handles ungrouped digits of any length.
_NUMBER_RE = re.compile(
    r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # 1,234.56
    r"|[-+]?\d+(?:\.\d+)?"  # 1309, 33.73
)

#: ISO dates -- stripped before scanning so 2026-09-01 is not read as three numbers.
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: Markdown table pipes, headings and list markers carry no factual numbers.
_LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)

#: Small integers are ubiquitous in prose ("the top 5", "3 retailers") and checking them
#: produces noise without catching real fabrication, which is about prices and percentages.
SMALL_INTEGER_CEILING = 10


@dataclass
class GuardResult:
    ok: bool
    unsupported: list[float] = field(default_factory=list)
    checked: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "unsupported": self.unsupported,
            "checked": self.checked,
            "notes": self.notes,
        }


def extract_numbers(body: str) -> list[float]:
    """Pull candidate factual numbers out of generated text."""
    cleaned = _DATE_RE.sub(" ", body)
    cleaned = _LIST_MARKER_RE.sub(" ", cleaned)

    numbers: list[float] = []
    for raw in _NUMBER_RE.findall(cleaned):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        numbers.append(round(value, 2))
    return numbers


def validate_brief(
    body: str, allowed: set[float], small_integer_ceiling: int = SMALL_INTEGER_CEILING
) -> GuardResult:
    """Check every number in `body` against the facts.

    A number matches if it appears in the facts, or if its absolute value does (an
    undercut of -33.7% is legitimately written as "33.7% below").
    """
    allowed_abs = {abs(v) for v in allowed}
    unsupported: list[float] = []
    checked = 0

    for value in extract_numbers(body):
        # Ordinary prose integers are not the fabrication risk; prices and percentages are.
        if float(value).is_integer() and abs(value) <= small_integer_ceiling:
            continue
        checked += 1
        if value in allowed or abs(value) in allowed_abs:
            continue
        unsupported.append(value)

    result = GuardResult(
        ok=not unsupported,
        unsupported=sorted(set(unsupported)),
        checked=checked,
    )
    if not result.ok:
        result.notes.append(
            f"{len(result.unsupported)} number(s) in the brief are absent from the facts"
        )
        log.error("brief.guard_failed", unsupported=result.unsupported, checked=checked)
    else:
        log.info("brief.guard_passed", checked=checked)
    return result
