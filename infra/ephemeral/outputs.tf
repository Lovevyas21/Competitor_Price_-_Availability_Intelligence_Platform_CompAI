output "app_public_ip" {
  description = "Application host address."
  value       = aws_instance.app.public_ip
}

output "app_instance_id" {
  description = "Use with: aws ssm start-session --target <id>"
  value       = aws_instance.app.id
}

output "db_endpoint" {
  description = "RDS address. Private -- reachable only from the app security group."
  value       = aws_db_instance.pg.address
}

output "how_to_get_credentials" {
  value = "aws ssm get-parameter --name ${aws_ssm_parameter.db_url.name} --with-decryption"
}

output "how_to_reach_the_database" {
  value = join(" ", [
    "aws ssm start-session --target ${aws_instance.app.id}",
    "--document-name AWS-StartPortForwardingSessionToRemoteHost",
    "--parameters '{\"host\":[\"${aws_db_instance.pg.address}\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"5433\"]}'",
  ])
}

output "hourly_cost_usd" {
  description = "What this stack costs while it is up. Destroy it and this goes to zero."
  value       = "EC2 t4g.small ~0.017/h + RDS db.t4g.micro ~0.016/h + storage => roughly $0.035/hour"
}
