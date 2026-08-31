# Networking: EC2 in a public subnet, RDS in private subnets with no route to the
# internet. There is deliberately no NAT gateway -- it would cost roughly $32/month,
# more than the rest of this stack combined, and nothing in a private subnet needs
# outbound internet. The workers run on the public-subnet instance.

data "aws_caller_identity" "current" {}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 0)
  availability_zone       = var.availability_zones[0]
  map_public_ip_on_launch = true

  tags = { Name = "${var.project}-public-a" }
}

# Two private subnets in different AZs: an RDS subnet group requires it even when the
# instance itself is Single-AZ.
resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${var.project}-private-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# --- security groups -------------------------------------------------------
resource "aws_security_group" "app" {
  name        = "${var.project}-app"
  description = "Application host: outbound only, plus optional SSH."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-app" }
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "Outbound to source APIs, S3 and package registries."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Only created when an explicit CIDR is supplied. No default open SSH.
resource "aws_vpc_security_group_ingress_rule" "app_ssh" {
  for_each = toset(var.ssh_ingress_cidrs)

  security_group_id = aws_security_group.app.id
  description       = "SSH from an explicitly allowed address"
  cidr_ipv4         = each.value
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

resource "aws_security_group" "db" {
  name        = "${var.project}-db"
  description = "RDS: reachable only from the application security group."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-db" }
}

# Source is the app security group, not a CIDR: the rule keeps holding if the
# instance is replaced and its address changes.
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the application host only"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
