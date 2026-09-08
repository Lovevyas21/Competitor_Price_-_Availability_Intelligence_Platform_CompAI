# Image repository. Persistent because images must outlive the compute they run on --
# tearing this down with the instance would mean rebuilding and pushing before every
# demo, and losing the ability to roll back to a previous tag.

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "MUTABLE" # `latest` is re-pointed on each deploy

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "${var.project}-ecr" }
}

# Untagged layers accumulate on every rebuild and are pure cost. Tagged images are kept
# to a small window so a rollback target always exists without paying to store history.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged layers quickly"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 3
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the last 10 tagged images for rollback"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}
