data "aws_caller_identity" "current" {}

data "aws_ssm_parameter" "amazon_linux_2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  bucket_name = var.state_bucket_name != "" ? var.state_bucket_name : "${var.project_name}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"

  tags = merge(
    {
      Project                  = "Infra-Guard"
      Environment              = "test"
      ManagedBy                = "terraform"
      "infra-guard:test-suite" = "terraform"
    },
    var.common_tags
  )
}

resource "aws_s3_bucket" "state" {
  bucket        = local.bucket_name
  force_destroy = true

  tags = merge(local.tags, {
    Name = "${var.project_name}-state"
  })
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "archive-old-noncurrent-state"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_transition {
      noncurrent_days = 90
      storage_class   = "GLACIER"
    }

    noncurrent_version_expiration {
      newer_noncurrent_versions = 30
      noncurrent_days           = 365
    }
  }
}

resource "aws_cloudwatch_log_group" "cleanup" {
  name              = "/infra-guard/cleanup"
  retention_in_days = 14

  tags = local.tags
}

resource "aws_vpc" "test" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.tags, {
    Name = "${var.project_name}-vpc"
  })
}

resource "aws_subnet" "test" {
  vpc_id                  = aws_vpc.test.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = false

  tags = merge(local.tags, {
    Name = "${var.project_name}-subnet"
  })
}

resource "aws_security_group" "instance" {
  name        = "${var.project_name}-instance"
  description = "Security group attached to the stopped test instance."
  vpc_id      = aws_vpc.test.id

  egress {
    description = "Allow outbound traffic for package metadata during boot."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, {
    Name                 = "${var.project_name}-instance"
    "infra-guard:skip"   = "true"
    "infra-guard:reason" = "Attached security group should not be deleted."
  })
}

resource "aws_security_group" "orphan_cleanup_target" {
  name        = "${var.project_name}-orphan-cleanup-target"
  description = "Unattached security group with no ingress rules for Infra-Guard cleanup testing."
  vpc_id      = aws_vpc.test.id

  tags = merge(local.tags, {
    Name                 = "${var.project_name}-orphan-cleanup-target"
    "infra-guard:target" = "orphan-security-group"
  })
}

resource "aws_iam_role" "cleanup_runner" {
  name = "${var.project_name}-cleanup-runner"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "cleanup_runner" {
  name = "${var.project_name}-cleanup-policy"
  role = aws_iam_role.cleanup_runner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketVersioning"
        ]
        Resource = [
          aws_s3_bucket.state.arn,
          "${aws_s3_bucket.state.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeVolumes",
          "ec2:DeleteVolume",
          "ec2:DescribeAddresses",
          "ec2:ReleaseAddress",
          "ec2:DescribeInstances",
          "ec2:TerminateInstances",
          "ec2:DescribeSnapshots",
          "ec2:DeleteSnapshot",
          "ec2:DescribeImages",
          "ec2:DescribeSecurityGroups",
          "ec2:DeleteSecurityGroup",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeTags"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:log-group:/infra-guard/cleanup*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "cleanup_runner" {
  name = "${var.project_name}-cleanup-runner"
  role = aws_iam_role.cleanup_runner.name
}

resource "aws_instance" "stopped_cleanup_target" {
  ami                                  = data.aws_ssm_parameter.amazon_linux_2023.value
  instance_type                        = var.instance_type
  subnet_id                            = aws_subnet.test.id
  vpc_security_group_ids               = [aws_security_group.instance.id]
  iam_instance_profile                 = aws_iam_instance_profile.cleanup_runner.name
  associate_public_ip_address          = false
  instance_initiated_shutdown_behavior = "stop"

  user_data = <<-EOF
    #!/bin/bash
    shutdown -h now
  EOF

  root_block_device {
    volume_size = 8
    volume_type = "gp3"

    tags = merge(local.tags, {
      Name               = "${var.project_name}-instance-root"
      "infra-guard:skip" = "true"
    })
  }

  tags = merge(local.tags, {
    Name                  = "${var.project_name}-stopped-cleanup-target"
    "infra-guard:cleanup" = "true"
    "infra-guard:target"  = "stopped-instance"
  })
}

resource "aws_ebs_volume" "unattached_cleanup_target" {
  availability_zone = aws_subnet.test.availability_zone
  size              = 1
  type              = "gp3"

  tags = merge(local.tags, {
    Name                 = "${var.project_name}-unattached-cleanup-target"
    "infra-guard:target" = "unattached-ebs-volume"
  })
}

resource "aws_ebs_volume" "snapshot_source" {
  availability_zone = aws_subnet.test.availability_zone
  size              = 1
  type              = "gp3"

  tags = merge(local.tags, {
    Name               = "${var.project_name}-snapshot-source"
    "infra-guard:skip" = "true"
  })
}

resource "aws_ebs_snapshot" "old_snapshot_cleanup_target" {
  volume_id = aws_ebs_volume.snapshot_source.id

  tags = merge(local.tags, {
    Name                 = "${var.project_name}-snapshot-cleanup-target"
    "infra-guard:target" = "old-ebs-snapshot"
  })
}

resource "aws_eip" "unused_cleanup_target" {
  domain = "vpc"

  tags = merge(local.tags, {
    Name                 = "${var.project_name}-unused-eip-cleanup-target"
    "infra-guard:target" = "unused-elastic-ip"
  })
}
