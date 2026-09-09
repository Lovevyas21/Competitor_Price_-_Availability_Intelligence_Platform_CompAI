# The database connection string, and only that. It belongs to this stack because it
# contains the RDS endpoint and password, both of which are regenerated on every apply --
# storing it alongside the hand-entered API keys would mean a stale connection string
# outliving the database it points at.

resource "aws_ssm_parameter" "db_url" {
  name        = "/${var.project}/${var.environment}/DATABASE_URL_OVERRIDE"
  description = "SQLAlchemy connection string. sslmode=require -- rds.force_ssl is on."
  type        = "SecureString"
  overwrite   = true # a previous teardown will have left one behind

  value = format(
    "postgresql+psycopg://%s:%s@%s:%s/%s?sslmode=require",
    var.db_username,
    urlencode(random_password.db.result),
    aws_db_instance.pg.address,
    aws_db_instance.pg.port,
    var.db_name,
  )

  tags = { Name = "${var.project}-database-url" }
}

# dbt reads discrete connection parts, not a URL: `profiles.yml` is templated with
# POSTGRES_HOST/PORT/USER/PASSWORD/DB. Publishing only DATABASE_URL_OVERRIDE left the
# application able to reach the database and dbt unable to, which surfaces as an API
# serving 500s from analytics_marts.* tables that were never built.
locals {
  db_connection_parts = {
    POSTGRES_HOST     = aws_db_instance.pg.address
    POSTGRES_PORT     = tostring(aws_db_instance.pg.port)
    POSTGRES_DB       = var.db_name
    POSTGRES_USER     = var.db_username
    POSTGRES_PASSWORD = random_password.db.result
    DBT_SSLMODE       = "require" # rds.force_ssl = 1
  }
}

resource "aws_ssm_parameter" "db_parts" {
  for_each = local.db_connection_parts

  name      = "/${var.project}/${var.environment}/${each.key}"
  type      = "SecureString"
  value     = each.value
  overwrite = true

  tags = { Name = "${var.project}-${lower(each.key)}" }
}
