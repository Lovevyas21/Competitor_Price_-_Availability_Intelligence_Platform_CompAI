# ADR-010: The weekly brief is deterministic by default; the LLM must pass a numeric guard

**Status:** Accepted

## Context

The build document specifies a CrewAI crew that writes a weekly pricing brief, and names
LLM hallucination as a headline risk with the mitigation *"agents must cite numbers only
from tool output; the Writer receives a structured facts JSON, not free-form recall."*

The risk is specific and serious in this context. A brief saying *"Intermarché undercut
us by 34%"* when the real figure is 33.73% reads perfectly, sounds authoritative, and
could move a price. Fluency is not accuracy, and a pricing brief is exactly the kind of
artefact people act on without re-deriving.

There is also a practical constraint: no LLM credential is configured, and the machine is
memory-constrained. A design that only works with a paid key produces nothing today.

## Decision

**1. The facts layer is the single source of numbers.** `ai/facts.py` queries the tested
dbt marts and returns a closed payload. The writer never touches the database. A
read-only SQL tool exists for exploration but is deliberately *not* on the drafting path:
an agent that can query freely can also summarise loosely, and its output is then
unverifiable.

**2. The deterministic renderer is the default.** `ai/brief.py` renders the facts as
Markdown with no model involved. It always works, costs nothing, and cannot fabricate.

**3. The LLM is optional narration, gated by a hard check.** When `LLM_MODEL` is set, a
CrewAI crew (analyst → forecast interpreter → writer) narrates the same facts. The output
passes through `ai/guard.py`, which requires **every number in the brief to be present in
the facts**. Not "within tolerance" — present. If any number is unsupported, the crew
output is discarded and the deterministic brief is returned.

The fallback direction matters: the worst case is a plainer brief, never a wrong one.

## Consequences

- The system produces a real brief today, with no key and no spend.
- Hallucinated figures cannot ship. The check is decidable because the fact set is closed.
- **The guard immediately earned its place by failing its own author.** Run against the
  deterministic brief it flagged six numbers, exposing two genuine bugs:
  - Numbers embedded in *product names* ("Beurre Demi-Sel … M.G. (60%)") were not in the
    facts' numeric fields. Quoting a product name must not read as an invented statistic,
    so `all_numbers()` now also scans string values — those figures came from the data.
  - The number regex `\d{1,3}(?:,\d{3})*` matched at most three digits when no comma was
    present, splitting `1309` into `130` and `9`, and `5885d` into `588` and `5`. It
    reported phantom violations, which is how guards get switched off. Fixed by requiring
    the comma group.
- Deliberate looseness, to keep the guard credible: ISO dates, list markers, and small
  integers (≤10) are excluded. Policing "the top 5" produces noise without catching the
  fabrication that matters, which is prices and percentages.
- Cost: the facts layer must be extended whenever the brief should discuss something new.
  That is the intended friction — a new claim requires a new query, not a new sentence.
- CrewAI is an optional extra (`pip install -e '.[ai]'`). It is installed and the crew is
  implemented, but it has not been executed against a live model, since no key is
  configured. The guard and fallback are tested independently of it.
