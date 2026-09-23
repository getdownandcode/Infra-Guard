# Infra-Guard Terraform Test Environment

This Terraform configuration creates low-cost AWS resources that exercise the Infra-Guard cleanup workflow:

- S3 bucket with versioning, AES-256 encryption, and lifecycle rules
- IAM role and instance profile with the permissions required by the project
- VPC and subnet for EC2-related resources
- stopped EC2 instance tagged `infra-guard:cleanup=true`
- unattached EBS volume
- unused Elastic IP
- old-snapshot cleanup target
- orphaned security group with no ingress rules

The cleanup targets are intentionally disposable. Run the project cleanup script with zero-day thresholds when you want to test immediate deletion.

## Usage

```bash
terraform -chdir=terraform init
terraform -chdir=terraform fmt
terraform -chdir=terraform validate
terraform -chdir=terraform plan -out test.tfplan
terraform -chdir=terraform apply test.tfplan
```

Then point the cleanup script at the generated bucket and fixture resources:

```bash
export S3_STATE_BUCKET=$(terraform -chdir=terraform output -raw state_bucket_name)
python3 scripts/cleanup.py --dry-run \
  --log-bucket "$S3_STATE_BUCKET" \
  --resource-tag-key infra-guard:test-suite --resource-tag-value terraform \
  --ebs-min-age-hours 0 --stopped-instance-min-age-days 0 --snapshot-min-age-days 0
```

Run the same command with `--confirm` instead of `--dry-run` to delete the fixture resources.

When you are done, destroy the environment:

```bash
terraform -chdir=terraform destroy
```
