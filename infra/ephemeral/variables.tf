# `project` and `environment` must match the persistent stack: this stack finds the
# bronze bucket, the alerts topic and the secrets path by deriving their names from
# these, rather than through a shared state file.
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

# --- compute ---------------------------------------------------------------
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

# --- database --------------------------------------------------------------
variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_engine_version" {
  description = "Must be a version offering pgvector (15.9+, 16.5+, 17.1+)."
  type        = string
  default     = "16.6"
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

# --- teardown behaviour ----------------------------------------------------
# See the comment in database.tf. These default to destroy-friendly because this stack
# exists to be torn down between demos, and because bronze in the persistent stack makes
# the database reproducible rather than precious.
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
