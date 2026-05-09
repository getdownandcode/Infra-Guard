# Terraform Documentation

This project includes a Terraform test environment under `terraform/`. It creates AWS resources that match the Infra-Guard cleanup workflow so you can test S3 setup, EC2 cleanup, EBS cleanup, Elastic IP cleanup, security group cleanup, CloudWatch logs, and IAM permissions.

## Prerequisites

Install and verify these tools:

```powershell
aws --version
terraform -version
python --version
docker --version
```

Configure AWS credentials before provisioning anything:

```powershell
aws configure
aws sts get-caller-identity
```

Set the default region used by this repo:

```powershell
$env:AWS_DEFAULT_REGION = "ap-south-1"
```

## What Terraform Creates

The Terraform files create:

- a versioned and encrypted S3 bucket for state backups and cleanup logs
- a CloudWatch log group named `/infra-guard/cleanup`
- an IAM role, policy, and instance profile for an Infra-Guard runner
- a small VPC and subnet
- a stopped EC2 instance tagged `infra-guard:cleanup=true`
- an unattached EBS volume
- an unused Elastic IP
- an EBS snapshot
- an orphan security group with no ingress rules

The cleanup test resources are intentionally safe to delete. They are tagged with `Project=Infra-Guard`, `Environment=test`, and `ManagedBy=terraform`.

The cleanup script scans a whole AWS region by default. The test commands below use `--resource-tag-key infra-guard:test-suite --resource-tag-value terraform` so only resources created by this Terraform fixture are eligible.

## Create The Test Environment

From the project root:

```powershell
cd D:\project_x\terraform
terraform init
terraform fmt
terraform validate
terraform plan -out infra-guard-test.tfplan
terraform apply "infra-guard-test.tfplan"
```

After apply, get the generated S3 bucket name:

```powershell
$env:S3_STATE_BUCKET = $(terraform -chdir=terraform output -raw state_bucket_name)
$env:AWS_DEFAULT_REGION = $(terraform -chdir=terraform output -raw aws_region)
```

The EC2 instance uses user data to stop itself after boot. Wait until it is stopped before testing stopped-instance cleanup:

```powershell
$instanceId = terraform -chdir=terraform output -raw stopped_instance_id
aws ec2 wait instance-stopped --instance-ids $instanceId --region $env:AWS_DEFAULT_REGION
```

## Bootstrap Or Repair The S3 Bucket

On Windows PowerShell:

```powershell
cd D:\project_x
.\scripts\bootstrap_s3.ps1
```

On Git Bash, WSL, Linux, or Jenkins:

```bash
cd /path/to/project_x
export AWS_DEFAULT_REGION=ap-south-1
export S3_STATE_BUCKET="$(cd terraform && terraform output -raw state_bucket_name)"
bash scripts/bootstrap_s3.sh
```

## Install Python Dependencies

From the project root:

```powershell
cd D:\project_x
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run A Full Dry Run

Use zero thresholds so the Terraform-created resources are immediately eligible:

```powershell
python scripts\cleanup.py `
  --dry-run `
  --region $env:AWS_DEFAULT_REGION `
  --log-bucket $env:S3_STATE_BUCKET `
  --resource-tag-key infra-guard:test-suite `
  --resource-tag-value terraform `
  --ebs-min-age-hours 0 `
  --stopped-instance-min-age-days 0 `
  --snapshot-min-age-days 0
```

or Use :
```powershell
python scripts\cleanup.py --dry-run --region $env:AWS_DEFAULT_REGION --log-bucket $env:S3_STATE_BUCKET --resource-tag-key "infra-guard:test-suite" --resource-tag-value "terraform" --ebs-min-age-hours 0 --stopped-instance-min-age-days 0 --snapshot-min-age-days 0 
```

Confirm the output includes dry-run actions for:

- deleting the unattached EBS volume
- releasing the unused Elastic IP
- terminating the stopped EC2 instance
- deleting the EBS snapshot
- deleting the orphaned security group
- writing cleanup logs to CloudWatch and S3
- writing local Prometheus metrics to `monitoring/textfile/infra_guard.prom`

## Run The Real Cleanup Test

This command deletes the Terraform-created cleanup targets:

```powershell
python scripts\cleanup.py `
  --confirm `
  --region $env:AWS_DEFAULT_REGION `
  --log-bucket $env:S3_STATE_BUCKET `
  --resource-tag-key infra-guard:test-suite `
  --resource-tag-value terraform `
  --ebs-min-age-hours 0 `
  --stopped-instance-min-age-days 0 `
  --snapshot-min-age-days 0
```

or use :
```powershell
python scripts\cleanup.py --confirm --region $env:AWS_DEFAULT_REGION --log-bucket $env:S3_STATE_BUCKET --resource-tag-key "infra-guard:test-suite" --resource-tag-value "terraform" --ebs-min-age-hours 0 --stopped-instance-min-age-days 0 --snapshot-min-age-days 0
```

After cleanup, verify logs were uploaded:

```powershell
aws s3 ls s3://$env:S3_STATE_BUCKET/cleanup-logs/ --region $env:AWS_DEFAULT_REGION
aws logs describe-log-streams --log-group-name /infra-guard/cleanup --region $env:AWS_DEFAULT_REGION
```

Dry-run mode does not upload S3 logs or CloudWatch logs. It only prints the planned actions and writes local Prometheus metrics.

## Run The Monitoring Stack

The monitoring stack runs locally with Docker:

```powershell
cd D:\project_x\monitoring
docker compose up -d
docker compose ps
```

If you ran cleanup or S3 sync before starting Docker, restart the monitoring stack once so `node_exporter` picks up the local textfile metrics mount:

```powershell
docker compose up -d --force-recreate node_exporter
```

Open:

```text
Grafana:    http://localhost:3000
Prometheus: http://localhost:9090
cAdvisor:   http://localhost:8080
```

Grafana defaults to:

```text
admin / admin
```

## Sync Project State To S3

On Windows PowerShell:

```powershell
cd D:\project_x
$env:S3_STATE_BUCKET = $(terraform -chdir=terraform output -raw state_bucket_name)
$env:AWS_DEFAULT_REGION = $(terraform -chdir=terraform output -raw aws_region)
.\scripts\s3-sync.ps1
```

On Git Bash, WSL, Linux, or Jenkins:

```bash
cd /path/to/project_x
export AWS_DEFAULT_REGION=ap-south-1
export S3_STATE_BUCKET="$(cd terraform && terraform output -raw state_bucket_name)"
bash scripts/s3-sync.sh
```

## Clean Up Everything

If you ran `cleanup.py --confirm`, some Terraform-managed resources may already be deleted. Terraform will refresh state and clean up what remains:

```powershell
cd D:\project_x\terraform
terraform destroy
```

If Terraform reports that a cleanup target was already deleted, run the destroy command again after the refresh completes.

## Cost Notes

This environment uses small resources, but it can still create AWS charges:

- EC2 instance storage
- EBS volumes and snapshots
- Elastic IP while allocated
- S3 storage and requests
- CloudWatch Logs storage

Run `terraform destroy` when testing is complete.
