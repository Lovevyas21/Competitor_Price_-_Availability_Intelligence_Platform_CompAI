from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create index if not exists ix_product_versions_embedding_hnsw
        on product_versions
        using hnsw (embedding vector_cosine_ops)
        with (m = 16, ef_construction = 64)
    """)

    op.execute("""
        create index if not exists ix_product_versions_blocking
        on product_versions (category, brand)
        where is_current
    """)

    op.execute("""
        create index if not exists ix_product_matches_pending
        on product_matches (status, confidence desc)
    """)

    op.execute("alter table product_matches add column if not exists reviewed_at timestamptz")
    op.execute("alter table product_matches add column if not exists notes text")

    op.execute("""
        alter table product_matches
        add constraint ck_product_matches_ordered_pair
        check (product_id_a < product_id_b)
    """)


def downgrade() -> None:
    op.execute(
        "alter table product_matches drop constraint if exists ck_product_matches_ordered_pair"
    )
    op.execute("alter table product_matches drop column if exists notes")
    op.execute("alter table product_matches drop column if exists reviewed_at")
    op.execute("drop index if exists ix_product_matches_pending")
    op.execute("drop index if exists ix_product_versions_blocking")
    op.execute("drop index if exists ix_product_versions_embedding_hnsw")
