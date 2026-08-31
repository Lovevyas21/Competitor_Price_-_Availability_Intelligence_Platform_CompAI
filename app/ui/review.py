"""Human-in-the-loop review UI for candidate product matches.

Embedding similarity in the 0.80-0.92 band is a suggestion, not a decision. This screen
is where a person turns it into one -- and, just as importantly, where the labels come
from that let precision and recall be *measured* later instead of assumed.

Run with: `make review`  ->  http://localhost:8501
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy import text

from app.ai.matching import record_review
from app.core.db import session_scope

PENDING_SQL = """
select
    m.match_id, m.confidence, m.method,
    a.product_id as a_id, a.upc as a_upc, a.external_id as a_external,
    va.title as a_title, va.brand as a_brand, va.category as a_category,
    b.product_id as b_id, b.upc as b_upc, b.external_id as b_external,
    vb.title as b_title, vb.brand as b_brand, vb.category as b_category
from product_matches m
join products a on a.product_id = m.product_id_a
join products b on b.product_id = m.product_id_b
left join product_versions va on va.product_id = a.product_id and va.is_current
left join product_versions vb on vb.product_id = b.product_id and vb.is_current
where m.status = 'pending'
order by m.confidence desc nulls last
limit :limit
"""

STATS_SQL = """
select status, count(*) as n
from product_matches
group by status
order by status
"""


def load_pending(limit: int) -> list[dict]:
    with session_scope() as session:
        return [dict(r) for r in session.execute(text(PENDING_SQL), {"limit": limit}).mappings()]


def load_stats() -> dict[str, int]:
    with session_scope() as session:
        return {r["status"]: int(r["n"]) for r in session.execute(text(STATS_SQL)).mappings()}


def submit(match_id: int, approved: bool, reviewer: str, notes: str | None) -> None:
    with session_scope() as session:
        record_review(session, match_id, approved=approved, reviewer=reviewer, notes=notes)


def side_by_side(row: dict) -> None:
    left, right = st.columns(2)
    for col, prefix, label in ((left, "a", "Product A"), (right, "b", "Product B")):
        with col:
            st.markdown(f"**{label}**")
            st.write(row[f"{prefix}_title"] or "_no title_")
            st.caption(
                f"brand: {row[f'{prefix}_brand'] or '—'}  \n"
                f"category: {row[f'{prefix}_category'] or '—'}  \n"
                f"barcode: {row[f'{prefix}_upc'] or row[f'{prefix}_external']}"
            )


def main() -> None:
    st.set_page_config(page_title="Match review", page_icon="🔍", layout="wide")
    st.title("Product match review")

    stats = load_stats()
    cols = st.columns(4)
    cols[0].metric("Pending", stats.get("pending", 0))
    cols[1].metric("Approved", stats.get("approved", 0))
    cols[2].metric("Rejected", stats.get("rejected", 0))
    reviewed = stats.get("approved", 0) + stats.get("rejected", 0)
    cols[3].metric("Reviewed", reviewed)

    with st.sidebar:
        st.header("Reviewer")
        reviewer = st.text_input("Your name", value="", placeholder="required to submit")
        limit = st.slider("Candidates to show", 1, 50, 10)
        st.caption(
            "Pairs scoring 0.92 or above are auto-approved; below 0.80 they are not "
            "shown at all. Everything here is in the uncertain band, which is exactly "
            "why a person decides it."
        )

    rows = load_pending(limit)
    if not rows:
        st.success("Nothing pending. Run matching to generate candidates.")
        return

    st.caption(f"Showing {len(rows)} of {stats.get('pending', 0)} pending pairs.")

    for row in rows:
        confidence = float(row["confidence"] or 0)
        with st.container(border=True):
            head, action = st.columns([3, 1])
            with head:
                st.progress(
                    min(confidence, 1.0),
                    text=f"similarity {confidence:.3f} · {row['method']}",
                )
            side_by_side(row)

            notes = st.text_input(
                "Notes (optional)",
                key=f"notes_{row['match_id']}",
                label_visibility="collapsed",
                placeholder="why did you decide this?",
            )
            with action:
                approve, reject = st.columns(2)
                disabled = not reviewer.strip()
                if approve.button("Same", key=f"y_{row['match_id']}", disabled=disabled):
                    submit(row["match_id"], True, reviewer.strip(), notes or None)
                    st.rerun()
                if reject.button("Different", key=f"n_{row['match_id']}", disabled=disabled):
                    submit(row["match_id"], False, reviewer.strip(), notes or None)
                    st.rerun()
            if not reviewer.strip():
                st.caption("Enter your name in the sidebar to record a decision.")


if __name__ == "__main__":
    main()
