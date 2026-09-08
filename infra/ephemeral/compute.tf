# A single EC2 host running the docker compose stack. The build document's reasoning
# holds: Fargate's own compute is cheap, but the surrounding ALB + NAT + CloudWatch
# overhead is ~$90/month per environment -- several times this entire stack.

data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-6.1-arm64"]
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/${var.environment}/app"
  retention_in_days = 14 # long enough to debug, short enough to stay cheap

  tags = { Name = "${var.project}-app-logs" }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  key_name               = var.key_pair_name

  user_data                   = local.user_data
  user_data_replace_on_change = false # changing bootstrap must not recreate the host

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only -- IMDSv1 is how instance creds get stolen
  }

  lifecycle {
    ignore_changes = [ami] # a new AMI release must not silently replace the host
  }

  tags = { Name = "${var.project}-app" }
}

locals {
  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail

    dnf update -y
    dnf install -y docker git
    systemctl enable --now docker
    usermod -aG docker ec2-user

    # Compose v2 as a CLI plugin.
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL \
      "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    install -d -o ec2-user -g ec2-user /srv/cpi

    # Secrets are fetched at boot from SSM into a root-only env file. They are never
    # baked into the image and never written to the repo.
    cat >/usr/local/bin/cpi-fetch-env <<'SCRIPT'
    #!/bin/bash
    set -euo pipefail
    aws ssm get-parameters-by-path \
      --path "/${var.project}/${var.environment}" \
      --with-decryption --recursive \
      --region "${var.region}" \
      --query "Parameters[].[Name,Value]" --output text \
    | while IFS=$'\t' read -r name value; do
        [ "$value" = "unset" ] && continue
        echo "$(basename "$name")=$value"
      done > /srv/cpi/.env.tmp
    mv /srv/cpi/.env.tmp /srv/cpi/.env
    chmod 600 /srv/cpi/.env
    SCRIPT
    chmod 700 /usr/local/bin/cpi-fetch-env

    echo "BRONZE_BACKEND=s3" >> /srv/cpi/.env.static
    echo "BRONZE_S3_BUCKET=${data.aws_s3_bucket.bronze.bucket}" >> /srv/cpi/.env.static
    echo "ENV=${var.environment}" >> /srv/cpi/.env.static
  EOT
}
