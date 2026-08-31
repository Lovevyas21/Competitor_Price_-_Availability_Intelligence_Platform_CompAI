# RDS PostgreSQL. Private, encrypted, and never given a public address.

resource "random_password" "db" {
  length  = 32
  special = true
  # RDS rejects these in a master password.
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_db_subnet_group" "private" {
  name       = "${var.project}-db-subnets"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${var.project}-db-subnets" }
}

# pgvector ships with RDS PostgreSQL but must be enabled per database with
# `create extension vector` -- Alembic migration 0001 does that on first deploy.
resource "aws_db_parameter_group" "pg" {
  name        = "${var.project}-pg16"
  family      = "postgres16"
  description = "Force TLS and log slow queries."

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "pg" {
  identifier     = "${var.project}-pg"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 3 # storage autoscaling headroom
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.private.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.pg.name

  # The instance has no public address and lives in subnets with no internet route.
  publicly_accessible = false
  multi_az            = false # single-AZ: this is a portfolio budget, not an SLA

  backup_retention_period = var.db_backup_retention_days
  backup_window           = "18:00-19:00" # ~23:30 IST, off-peak for the operator
  maintenance_window      = "sun:19:30-sun:20:30"

  auto_minor_version_upgrade = true
  deletion_protection        = true

  # A final snapshot is cheap insurance against a mistaken destroy.
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-pg-final"

  performance_insights_enabled    = false # not free on t4g.micro
  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = { Name = "${var.project}-pg" }
}
