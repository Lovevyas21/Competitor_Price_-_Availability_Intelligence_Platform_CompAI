resource "aws_ssm_parameter" "db_url" {
  name        = "/${var.project}/${var.environment}/DATABASE_URL_OVERRIDE"
  description = "SQLAlchemy connection string. sslmode=require -- rds.force_ssl is on."
  type        = "SecureString"
  overwrite   = true

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

locals {
  db_connection_parts = {
    POSTGRES_HOST     = aws_db_instance.pg.address
    POSTGRES_PORT     = tostring(aws_db_instance.pg.port)
    POSTGRES_DB       = var.db_name
    POSTGRES_USER     = var.db_username
    POSTGRES_PASSWORD = random_password.db.result
    DBT_SSLMODE       = "require"
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
