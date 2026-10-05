from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)

_NUMBER_RE = re.compile(
    r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|[-+]?\d+(?:\.\d+)?"
)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)

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
    allowed_abs = {abs(v) for v in allowed}
    unsupported: list[float] = []
    checked = 0

    for value in extract_numbers(body):
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
