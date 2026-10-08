from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create table if not exists briefs (
            brief_id      bigserial primary key,
            created_at    timestamptz not null default now(),
            period_days   integer not null,
            source        text not null,
            body          text not null,
            guard_ok      boolean,
            guard_checked integer
        )
    """)
    op.execute("create index if not exists ix_briefs_created_at on briefs (created_at desc)")


def downgrade() -> None:
    op.execute("drop table if exists briefs")
