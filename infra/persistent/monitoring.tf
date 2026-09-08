# Budget alarm and the notification topic. Both persistent, for the same reason: an SNS
# email subscription must be confirmed by clicking a link, and a budget only becomes
# useful once it has a month of history. Recreating either per demo would make the one
# guard that matters -- an unnoticed bill -- the least reliable thing in the stack.

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Forecast first. By the time actual spend crosses the line the month is already
  # spent; a forecast breach is the only warning that arrives while it can still be
  # acted on -- which for this stack means running `terraform destroy`.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alert_email == "" ? [] : [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_email == "" ? [] : [var.alert_email]
  }
}
