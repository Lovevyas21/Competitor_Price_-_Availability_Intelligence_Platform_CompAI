# Third-party credentials. Persistent on purpose: these are typed in by hand, out of
# band, and a stack that wiped them on every `destroy` would mean re-entering an API key
# before every demo -- which is exactly the friction that ends with a key pasted into a
# committed file.
#
# SSM rather than Secrets Manager: SecureString parameters are free at this scale, while
# Secrets Manager is ~$0.40 per secret per month for rotation nobody here needs.

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
  ]
}

resource "aws_ssm_parameter" "placeholders" {
  for_each = toset(local.placeholder_secrets)

  name  = "/${var.project}/${var.environment}/${each.value}"
  type  = "SecureString"
  value = "unset"

  # The whole point is that the real value is set outside Terraform. State is not a
  # place to keep a third-party API key.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.project}-${lower(each.value)}" }
}
