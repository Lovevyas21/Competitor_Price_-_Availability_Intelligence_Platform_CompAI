output "bronze_bucket" {
  description = "Raw payload bucket. Survives every teardown; the source for `cpi replay`."
  value       = aws_s3_bucket.bronze.bucket
}

output "ecr_repository_url" {
  description = "Set as the ECR_REPOSITORY repository variable in GitHub Actions."
  value       = aws_ecr_repository.app.repository_url
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "secrets_path" {
  description = "Fill these in with: aws ssm put-parameter --name <path> --value <v> --type SecureString --overwrite"
  value       = "/${var.project}/${var.environment}/"
}

output "monthly_cost_usd" {
  description = "What this stack costs while nothing is deployed."
  value       = "S3 (a few GB) ~0.10, ECR (<1GB) ~0.10, SSM + SNS + Budgets free => under $0.50/month"
}
