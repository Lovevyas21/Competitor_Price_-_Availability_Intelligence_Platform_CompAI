"""matching: HNSW vector index and match review support

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW over cosine distance. Cosine (not L2) because these are sentence embeddings:
    # direction carries the meaning, magnitude does not.
    #
    # Built only over current versions' vectors in practice, but a partial index cannot
    # be used by the ANN search unless the query repeats the predicate, so the index is
    # unconditional and the query filters on is_current.
    op.execute("""
        create index if not exists ix_product_versions_embedding_hnsw
        on product_versions
        using hnsw (embedding vector_cosine_ops)
        with (m = 16, ef_construction = 64)
    """)

    # Blocking columns: candidate generation is restricted by brand/category before the
    # vector search, which cuts the comparison space and reduces false positives.
    op.execute("""
        create index if not exists ix_product_versions_blocking
        on product_versions (category, brand)
        where is_current
    """)

    # Review workflow: reviewers pull the pending queue ordered by confidence.
    op.execute("""
        create index if not exists ix_product_matches_pending
        on product_matches (status, confidence desc)
    """)

    # Auditability of the review decision -- who decided, and when.
    op.execute("alter table product_matches add column if not exists reviewed_at timestamptz")
    op.execute("alter table product_matches add column if not exists notes text")

    # A match is an unordered pair: (a, b) and (b, a) are the same statement about the
    # world. Storing both would double the review queue and let them disagree.
    op.execute("""
        alter table product_matches
        add constraint ck_product_matches_ordered_pair
        check (product_id_a < product_id_b)
    """)


def downgrade() -> None:
    op.execute(
        "alter table product_matches "
        "drop constraint if exists ck_product_matches_ordered_pair"
    )
    op.execute("alter table product_matches drop column if exists notes")
    op.execute("alter table product_matches drop column if exists reviewed_at")
    op.execute("drop index if exists ix_product_matches_pending")
    op.execute("drop index if exists ix_product_versions_blocking")
    op.execute("drop index if exists ix_product_versions_embedding_hnsw")
