output "app_public_ip" {
  description = "Application host address."
  value       = aws_instance.app.public_ip
}

output "app_instance_id" {
  description = "Use with: aws ssm start-session --target <id>"
  value       = aws_instance.app.id
}

output "bronze_bucket" {
  description = "Raw payload bucket; the source for `cpi replay`."
  value       = aws_s3_bucket.bronze.bucket
}

output "db_endpoint" {
  description = "RDS address. Private -- reachable only from the app security group."
  value       = aws_db_instance.pg.address
}

output "database_url_parameter" {
  description = "SSM parameter holding the connection string."
  value       = aws_ssm_parameter.db_url.name
}

# The password itself is never output, even marked sensitive: it would still be written
# to state and printable with `terraform output -json`. Read it from SSM instead.
output "how_to_get_credentials" {
  value = "aws ssm get-parameter --name ${aws_ssm_parameter.db_url.name} --with-decryption"
}

output "estimated_monthly_cost_usd" {
  description = "Rough guide only. Confirm on the AWS Pricing Calculator."
  value       = "RDS db.t4g.micro ~14-16, EC2 t4g.small ~12-15, S3 ~1-2, misc ~1-3 => ~28-36"
}
