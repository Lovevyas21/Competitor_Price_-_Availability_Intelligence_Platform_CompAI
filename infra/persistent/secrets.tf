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
    "GEMINI_API_KEY",
    "SHOWCASE_ENABLED",
  ]
}

resource "aws_ssm_parameter" "placeholders" {
  for_each = toset(local.placeholder_secrets)

  name  = "/${var.project}/${var.environment}/${each.value}"
  type  = "SecureString"
  value = "unset"

  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.project}-${lower(each.value)}" }
}
