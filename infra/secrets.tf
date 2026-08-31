# Secrets live in SSM Parameter Store, not in code, not in the AMI, not in .env on disk.
#
# SSM rather than Secrets Manager: SecureString parameters are free at this scale, while
# Secrets Manager is ~$0.40 per secret per month. For a handful of values with no need
# for automatic rotation, that cost buys nothing.

resource "aws_ssm_parameter" "db_url" {
  name        = "/${var.project}/${var.environment}/DATABASE_URL_OVERRIDE"
  description = "SQLAlchemy connection string. sslmode=require -- rds.force_ssl is on."
  type        = "SecureString"

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

# Placeholders: created empty so IAM policy and application wiring are complete, then
# filled in out of band. Terraform state is not a place to keep third-party API keys.
locals {
  placeholder_secrets = [
    "BESTBUY_API_KEY",
    "EBAY_CLIENT_ID",
    "EBAY_CLIENT_SECRET",
    "DIGIKEY_CLIENT_ID",
    "DIGIKEY_CLIENT_SECRET",
    "SLACK_WEBHOOK_URL",
    "API_KEY",
    "LLM_MODEL",
  ]
}

resource "aws_ssm_parameter" "placeholders" {
  for_each = toset(local.placeholder_secrets)

  name  = "/${var.project}/${var.environment}/${each.value}"
  type  = "SecureString"
  value = "unset"

  # The whole point is that the real value is set outside Terraform.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.project}-${lower(each.value)}" }
}
