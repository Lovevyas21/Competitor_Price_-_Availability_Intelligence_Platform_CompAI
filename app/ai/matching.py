"""Cross-retailer product matching (entity resolution).

The same physical product appears under different barcodes, titles and languages across
retailers. Matching them is what makes "who is undercutting us" answerable beyond an
exact UPC hit.

The policy, in priority order:

1. **Structured identifiers win outright.** An exact UPC/MPN match is a fact; an
   embedding similarity is an opinion. Never let a 0.95 cosine override a UPC mismatch.
2. **Blocking before vector search.** Candidates are restricted by category/brand first.
   This cuts the comparison space and, more importantly, suppresses the classic failure
   mode where two unrelated products with similarly-shaped names score highly.
3. **Three bands, not a single cutoff** (from the build document):
   `>= 0.92` auto-match, `0.80 - 0.92` human review, `< 0.80` rejected.

Every decision is written to `product_matches` with its method and score, so precision
and recall can be measured against reviewer verdicts later rather than guessed at.

Embeddings use fastembed (ONNX) rather than sentence-transformers: it serves the same
`all-MiniLM-L6-v2` 384-dim model without pulling in torch, which matters on a
memory-constrained machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

#: Thresholds from the build document.
AUTO_MATCH_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.80

#: Nearest neighbours to consider per product before thresholding.
TOP_K = 5


@dataclass
class MatchStats:
    products_embedded: int = 0
    pairs_considered: int = 0
    exact_identifier_matches: int = 0
    auto_matched: int = 0
    queued_for_review: int = 0
    rejected_low_similarity: int = 0
    skipped_no_text: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@lru_cache(maxsize=1)
def _model():
    """Loaded once per process -- construction costs ~25s and allocates the ONNX session."""
    from fastembed import TextEmbedding  # noqa: PLC0415

    log.info("matching.loading_model", model=EMBEDDING_MODEL)
    return TextEmbedding(model_name=EMBEDDING_MODEL)


def build_text(title: str | None, brand: str | None, category: str | None) -> str:
    """The string that gets embedded.

    Brand and category are included deliberately: titles alone are short and generic
    ("Baguette"), and the extra context is what separates two retailers' listing of the
    same item from two genuinely different items with similar names.
    """
    parts = [p.strip() for p in (title, brand, category) if p and p.strip()]
    return " | ".join(parts)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [vector.tolist() for vector in _model().embed(texts)]


# --------------------------------------------------------------------------- #
# embedding backfill
# --------------------------------------------------------------------------- #
_PENDING_SQL = """
select pv.version_id, pv.product_id, pv.title, pv.brand, pv.category
from product_versions pv
where pv.is_current
  and pv.embedding is null
order by pv.product_id
limit :limit
"""

_STORE_SQL = """
update product_versions
set embedding = data.embedding::vector
from (
    select * from unnest(cast(:version_ids as bigint[]), cast(:embeddings as text[]))
         as t(version_id, embedding)
) as data
where product_versions.version_id = data.version_id
"""


def embed_pending_products(
    session: Session, batch_size: int = 256, max_batches: int = 100
) -> MatchStats:
    """Embed current product versions that do not have a vector yet."""
    stats = MatchStats()

    for _ in range(max_batches):
        rows = session.execute(text(_PENDING_SQL), {"limit": batch_size}).mappings().all()
        if not rows:
            break

        version_ids, texts = [], []
        for row in rows:
            body = build_text(row["title"], row["brand"], row["category"])
            if not body:
                stats.skipped_no_text += 1
                continue
            version_ids.append(int(row["version_id"]))
            texts.append(body)

        if not version_ids:
            break

        vectors = embed_texts(texts)
        session.execute(
            text(_STORE_SQL),
            {
                "version_ids": version_ids,
                "embeddings": [str(v) for v in vectors],
            },
        )
        stats.products_embedded += len(version_ids)
        log.info("matching.embedded_batch", count=len(version_ids))

        if len(rows) < batch_size:
            break

    return stats


# --------------------------------------------------------------------------- #
# candidate generation
# --------------------------------------------------------------------------- #
#: Nearest neighbours within the same category, excluding the product itself and
#: anything already carrying the same UPC (those are handled as exact matches).
#: `1 - (a <=> b)` converts pgvector cosine *distance* to cosine *similarity*.
_CANDIDATES_SQL = """
with base as (
    select pv.product_id, pv.embedding, pv.category, p.upc
    from product_versions pv
    join products p on p.product_id = pv.product_id
    where pv.is_current and pv.embedding is not null
)
select
    b.product_id            as product_id_a,
    o.product_id            as product_id_b,
    1 - (b.embedding <=> o.embedding) as similarity
from base b
join lateral (
    select pv.product_id, pv.embedding
    from product_versions pv
    join products p2 on p2.product_id = pv.product_id
    where pv.is_current
      and pv.embedding is not null
      and pv.product_id <> b.product_id
      -- Blocking: same category (or both unknown) keeps comparisons meaningful.
      and pv.category is not distinct from b.category
      -- Exact-identifier pairs are recorded separately, with method 'exact_upc'.
      and (p2.upc is null or b.upc is null or p2.upc <> b.upc)
    order by pv.embedding <=> b.embedding
    limit :top_k
) o on true
where b.product_id < o.product_id
  and 1 - (b.embedding <=> o.embedding) >= :review_threshold
order by similarity desc
limit :max_pairs
"""

_EXACT_UPC_SQL = """
select least(a.product_id, b.product_id)    as product_id_a,
       greatest(a.product_id, b.product_id) as product_id_b
from products a
join products b
  on a.upc = b.upc
 and a.product_id < b.product_id
where a.upc is not null and a.upc <> ''
"""

_UPSERT_MATCH_SQL = """
insert into product_matches
    (product_id_a, product_id_b, confidence, method, status, created_at)
values (:a, :b, :confidence, :method, :status, now())
on conflict (product_id_a, product_id_b) do update set
    confidence = excluded.confidence,
    method     = excluded.method
-- A human decision is final: never let a re-run flip an approved or rejected pair
-- back to pending.
where product_matches.status = 'pending'
"""


def generate_matches(
    session: Session,
    top_k: int = TOP_K,
    max_pairs: int = 5000,
    auto_threshold: float = AUTO_MATCH_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
) -> MatchStats:
    """Find candidate pairs and file them by confidence band."""
    stats = MatchStats()

    # 1. Exact identifiers first -- these are facts, not similarities.
    for row in session.execute(text(_EXACT_UPC_SQL)).mappings().all():
        session.execute(
            text(_UPSERT_MATCH_SQL),
            {
                "a": row["product_id_a"],
                "b": row["product_id_b"],
                "confidence": 1.0,
                "method": "exact_upc",
                "status": "approved",
            },
        )
        stats.exact_identifier_matches += 1

    # 2. Vector similarity for everything else.
    candidates = (
        session.execute(
            text(_CANDIDATES_SQL),
            {"top_k": top_k, "review_threshold": review_threshold, "max_pairs": max_pairs},
        )
        .mappings()
        .all()
    )

    for row in candidates:
        stats.pairs_considered += 1
        similarity = float(row["similarity"])

        if similarity >= auto_threshold:
            status, method = "approved", "embedding_auto"
            stats.auto_matched += 1
        else:
            status, method = "pending", "embedding_review"
            stats.queued_for_review += 1

        session.execute(
            text(_UPSERT_MATCH_SQL),
            {
                "a": int(row["product_id_a"]),
                "b": int(row["product_id_b"]),
                "confidence": round(similarity, 3),
                "method": method,
                "status": status,
            },
        )

    log.info("matching.generated", **stats.as_dict())
    return stats


def record_review(
    session: Session, match_id: int, approved: bool, reviewer: str, notes: str | None = None
) -> None:
    """Record a human verdict. This is the label set precision/recall is measured against."""
    session.execute(
        text("""
            update product_matches
            set status = :status, reviewed_by = :reviewer,
                reviewed_at = now(), notes = :notes, method = 'human'
            where match_id = :match_id
        """),
        {
            "match_id": match_id,
            "status": "approved" if approved else "rejected",
            "reviewer": reviewer,
            "notes": notes,
        },
    )
