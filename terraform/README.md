# Infra-Guard Terraform Test Environment

This Terraform configuration creates low-cost AWS resources that exercise the Infra-Guard cleanup workflow:

- S3 bucket with versioning, AES-256 encryption, and lifecycle rules
- CloudWatch Logs group for cleanup logs
- IAM role and instance profile with the permissions required by the project
- VPC and subnet for EC2-related resources
- stopped EC2 instance tagged `infra-guard:cleanup=true`
- unattached EBS volume
- unused Elastic IP
- old-snapshot cleanup target
- orphaned security group with no ingress rules

The cleanup targets are intentionally disposable. Run the project cleanup script with zero-day thresholds when you want to test immediate deletion.
