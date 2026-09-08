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

  # Both of these default to the *unsafe-looking* value on purpose, because this stack
  # is designed to be destroyed. The safe production settings are two blockers:
  #
  #   deletion_protection = true  makes `terraform destroy` fail outright.
  #   skip_final_snapshot = false with a fixed identifier succeeds the first time and
  #   then fails on every subsequent destroy, because the snapshot name already exists.
  #
  # Losing this database is survivable in a way losing most databases is not: bronze
  # lives in the persistent stack's S3 bucket, and the warehouse rebuilds from it with
  # `cpi replay` in about thirty seconds, no upstream traffic and no quota spend. Set
  # both variables the other way for anything holding data that is not reproducible.
  deletion_protection = var.db_deletion_protection
  skip_final_snapshot = var.db_skip_final_snapshot

  # Only used when a snapshot is actually taken. Timestamped so repeated teardowns do
  # not collide on the identifier.
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${var.project}-pg-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"

  performance_insights_enabled    = false # not free on t4g.micro
  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = { Name = "${var.project}-pg" }
}
