variable "project" {
  type    = string
  default = "cpi"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "region" {
  description = "AWS region. ap-south-1 (Mumbai) is closest to the operator."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "availability_zones" {
  description = "Two AZs are required for an RDS subnet group, even for Single-AZ."
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]
}

variable "instance_type" {
  description = "Graviton is roughly 20% cheaper than the x86 equivalent."
  type        = string
  default     = "t4g.small"
}

variable "ssh_ingress_cidrs" {
  description = <<-EOT
    CIDRs allowed to reach SSH. Deliberately empty by default: an open 0.0.0.0/0 SSH
    rule is the single most common way a portfolio deployment gets compromised.
    Leave empty and use SSM Session Manager.
  EOT
  type        = list(string)
  default     = []
}

variable "key_pair_name" {
  description = "Existing EC2 key pair. Null means SSM Session Manager only."
  type        = string
  default     = null
}

variable "db_instance_class" {
  description = <<-EOT
    db.t3.micro rather than the cheaper Graviton db.t4g.micro, which is not a preference
    but a availability finding: ap-south-1 returned "Insufficient instance capacity for
    instance type db.t4g.micro" and left the instance retrying in `insufficient-capacity`
    for over twenty minutes. Burstable Graviton database classes are frequently
    constrained in this region.

    Capacity is real-time and regional, so `describe-orderable-db-instance-options` will
    happily list a class that cannot actually be launched right now. If a create hangs in
    `creating`, read the reason rather than waiting:
      aws rds describe-events --source-identifier <id> --source-type db-instance
  EOT
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_engine_version" {
  description = <<-EOT
    Must be a version offering pgvector (15.9+, 16.5+, 17.1+) *and* actually offered in
    the target region -- those are different lists. 16.6 was pinned here and does not
    exist in ap-south-1, which `validate` and `plan` both accept happily and `apply`
    rejects several minutes in.

    16.15 matches the Docker image used in development, so the same Postgres runs in both
    places. Check before changing:
      aws rds describe-orderable-db-instance-options --engine postgres         --engine-version <v> --db-instance-class <class> --region <region>
  EOT
  type        = string
  default     = "16.15"
}

variable "db_name" {
  type    = string
  default = "cpi"
}

variable "db_username" {
  type    = string
  default = "cpi"
}

variable "db_backup_retention_days" {
  description = "0 disables automated backups. Reasonable here: the warehouse is rebuilt from bronze, not restored."
  type        = number
  default     = 1
}

variable "db_deletion_protection" {
  description = "true blocks `terraform destroy` entirely. Set true for anything holding irreproducible data."
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  description = "false takes a snapshot on destroy, which costs storage and slows teardown."
  type        = bool
  default     = true
}
