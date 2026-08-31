variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "cpi"
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
  default     = "prod"
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
    Set this to your own address, or leave empty and use SSM Session Manager.
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
  type    = number
  default = 7
}

# --- budget ----------------------------------------------------------------
variable "monthly_budget_inr" {
  description = "Budget alarm threshold. The build document recommends INR 400-2000."
  type        = number
  default     = 3000
}

variable "alert_email" {
  description = "Where budget and CloudWatch alarms are sent."
  type        = string
  default     = ""
}
