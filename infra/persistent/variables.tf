variable "project" {
  description = "Name prefix for every resource. Must match the ephemeral stack."
  type        = string
  default     = "cpi"
}

variable "environment" {
  description = "Deployment environment. Must match the ephemeral stack."
  type        = string
  default     = "prod"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "alert_email" {
  description = <<-EOT
    Where budget alarms are sent. The SNS subscription lives in this stack precisely
    because confirming it requires clicking a link in an email: if it were torn down
    with the compute, you would re-confirm it before every demo.
  EOT
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = <<-EOT
    Budget alarm threshold in USD. Sized against a credit balance rather than a salary:
    with $50 of credits and demo-only running, spend should be a few dollars, so a $20
    ceiling is loose enough not to nag and tight enough to catch something left running.
  EOT
  type        = number
  default     = 20
}
