# Infra-Guard Deployment and Validation

## AWS Connection

The project does not store AWS credentials. It uses the active AWS CLI or Jenkins
environment credentials.

Verify the active account before running anything that can mutate AWS:

```bash
aws sts get-caller-identity
aws configure list
```

## S3 State Bucket

Create or repair the versioned state bucket:

```bash
export AWS_DEFAULT_REGION=ap-south-1
export S3_STATE_BUCKET=infra-guard-state
bash scripts/bootstrap_s3.sh
```

On Windows PowerShell, use the native script so it can use the Windows AWS CLI:

```powershell
$env:AWS_DEFAULT_REGION = "ap-south-1"
$env:S3_STATE_BUCKET = "infra-guard-state"
.\scripts\bootstrap_s3.ps1
```

This configures:

- bucket creation when missing
- versioning
- AES-256 default encryption
- lifecycle transition of older noncurrent versions to Glacier

## Cleanup Workflow

Dry-run is the default safe operating mode:

```bash
python3 scripts/cleanup.py --dry-run --log-bucket infra-guard-state
```

Actual cleanup requires explicit confirmation:

```bash
python3 scripts/cleanup.py --confirm --log-bucket infra-guard-state
```

The cleanup script targets:

- unattached EBS volumes older than 24 hours
- unused Elastic IPs
- stopped EC2 instances older than 7 days only when tagged `infra-guard:cleanup=true`
- owned EBS snapshots older than 30 days, unless tagged `keep=true`
- orphaned non-default security groups with no ingress rules and no attached ENIs

Any supported resource tagged `infra-guard:skip=true` is ignored.

## S3 State Sync

```bash
bash scripts/s3-sync.sh
```

The sync uploads Terraform state when present, Grafana dashboards, Prometheus snapshots,
Jenkins XML exports, and cleanup logs.

## Monitoring Stack

```bash
cd monitoring
docker compose up -d
```

- Prometheus: `http://<host-ip>:9090`
- Grafana: `http://<host-ip>:3000`

Grafana defaults to `admin/admin` unless overridden by environment.

## Jenkins

Use the root `Jenkinsfile` as the source of truth. Jenkins builds
`Dockerfile.jenkins-agent` so AWS CLI, Python, boto3, Bash, and Docker Compose are
available without installing tools during the run. Jenkins must provide AWS credentials
through its credentials store, instance profile, or environment. The pipeline validates
the AWS identity, bootstraps S3, runs cleanup in dry-run mode, applies cleanup on `main`
or weekly cron runs, syncs state to S3, and deploys the monitoring stack.
