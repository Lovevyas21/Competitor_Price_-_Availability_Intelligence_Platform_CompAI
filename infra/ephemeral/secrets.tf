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
