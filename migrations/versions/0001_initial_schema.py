from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create extension if not exists vector")

    op.execute("""
        create table sources (
          source_id   serial primary key,
          name        text unique not null,
          base_url    text,
          auth_type   text,
          created_at  timestamptz not null default now()
        )
    """)

    op.execute("""
        create table retailers (
          retailer_id serial primary key,
          source_id   int references sources(source_id),
          name        text not null,
          country     text,
          created_at  timestamptz not null default now(),
          unique (source_id, name)
        )
    """)

    op.execute("""
        create table products (
          product_id  bigserial primary key,
          source_id   int not null references sources(source_id),
          external_id text not null,
          sku text, upc text, mpn text, brand text,
          category text,
          tier smallint not null default 3,
          created_at timestamptz not null default now(),
          unique (source_id, external_id)
        )
    """)
    op.execute("create index ix_products_tier on products(tier)")
    op.execute("create index ix_products_upc on products(upc) where upc is not null")

    op.execute("""
        create table product_versions (
          version_id bigserial primary key,
          product_id bigint not null references products(product_id),
          title text, brand text, category text,
          attributes jsonb,
          embedding vector(384),
          valid_from timestamptz not null default now(),
          valid_to   timestamptz,
          is_current boolean not null default true
        )
    """)
    op.execute(
        "create unique index ux_product_versions_current on product_versions(product_id) "
        "where is_current"
    )

    op.execute("""
        create table price_events (
          event_id bigserial,
          product_id bigint not null references products(product_id),
          retailer_id int references retailers(retailer_id),
          price numeric(12,2) not null,
          currency text not null default 'USD',
          observed_at timestamptz not null,
          ingested_at timestamptz not null default now(),
          idempotency_key text not null,
          primary key (event_id, observed_at)
        ) partition by range (observed_at)
    """)
    op.execute(
        "create unique index ux_price_events_idem on price_events(idempotency_key, observed_at)"
    )
    op.execute("create index ix_price_events_product on price_events(product_id, observed_at desc)")

    op.execute("""
        create table stock_events (
          event_id bigserial,
          product_id bigint not null references products(product_id),
          retailer_id int references retailers(retailer_id),
          in_stock boolean,
          quantity int,
          observed_at timestamptz not null,
          ingested_at timestamptz not null default now(),
          idempotency_key text not null,
          primary key (event_id, observed_at)
        ) partition by range (observed_at)
    """)
    op.execute(
        "create unique index ux_stock_events_idem on stock_events(idempotency_key, observed_at)"
    )
    op.execute("create index ix_stock_events_product on stock_events(product_id, observed_at desc)")

    op.execute("""
        create or replace function ensure_month_partition(parent text, month_start date)
        returns void language plpgsql as $func$
        declare
          part_name text := parent || '_' || to_char(month_start, 'YYYYMM');
          next_month date := (month_start + interval '1 month')::date;
        begin
          if not exists (select 1 from pg_class where relname = part_name) then
            execute format(
              'create table %I partition of %I for values from (%L) to (%L)',
              part_name, parent, month_start, next_month
            );
          end if;
        end $func$
    """)

    for tbl in ("price_events", "stock_events"):
        op.execute(f"""
            select ensure_month_partition('{tbl}', d::date) from generate_series(
              date_trunc('month', now() - interval '1 month'),
              date_trunc('month', now() + interval '1 month'),
              interval '1 month'
            ) d
        """)

    op.execute("""
        create table product_matches (
          match_id bigserial primary key,
          product_id_a bigint not null references products(product_id),
          product_id_b bigint not null references products(product_id),
          confidence numeric(4,3),
          method text,
          status text not null default 'pending',
          reviewed_by text,
          created_at timestamptz not null default now(),
          unique (product_id_a, product_id_b)
        )
    """)

    op.execute("""
        create table forecasts (
          forecast_id bigserial primary key,
          product_id bigint not null references products(product_id),
          model text not null,
          horizon_days int not null,
          yhat numeric(12,2), yhat_lower numeric(12,2), yhat_upper numeric(12,2),
          forecast_for date not null,
          trained_at timestamptz not null default now()
        )
    """)
    op.execute("create index ix_forecasts_product on forecasts(product_id, forecast_for desc)")

    op.execute("""
        create table forecast_accuracy (
          id bigserial primary key,
          product_id bigint not null references products(product_id),
          model text not null,
          mape numeric(6,3),
          horizon_days int,
          evaluated_at timestamptz not null default now()
        )
    """)

    op.execute("""
        create table alerts (
          alert_id bigserial primary key,
          product_id bigint references products(product_id),
          type text not null, message text, severity text,
          created_at timestamptz not null default now(),
          sent_at timestamptz
        )
    """)

    op.execute("""
        create table ingestion_runs (
          run_id bigserial primary key,
          source_id int references sources(source_id),
          started_at timestamptz not null default now(),
          finished_at timestamptz,
          status text not null default 'running',
          records_ok int not null default 0,
          records_failed int not null default 0,
          notes text
        )
    """)

    op.execute("""
        create table seed_products (
          seed_id bigserial primary key,
          source_name text not null,
          external_id text not null,
          tier smallint not null default 3,
          note text,
          active boolean not null default true,
          created_at timestamptz not null default now(),
          unique (source_name, external_id)
        )
    """)


def downgrade() -> None:
    for t in (
        "seed_products",
        "ingestion_runs",
        "alerts",
        "forecast_accuracy",
        "forecasts",
        "product_matches",
        "stock_events",
        "price_events",
        "product_versions",
        "products",
        "retailers",
        "sources",
    ):
        op.execute(f"drop table if exists {t} cascade")
    op.execute("drop function if exists ensure_month_partition(text, date)")
