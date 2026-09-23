# Infra-Guard

Infra-Guard is a lightweight AWS cost and health optimizer. It detects and deletes idle
AWS resources with a safety-first workflow: dry-run by default, explicit `--confirm` to
mutate, and tag-based opt-outs. Jenkins automates the weekly run, S3 stores versioned
state and log backups, and Prometheus plus Grafana visualize the results.

The project uses AWS credentials from the current shell, Jenkins credentials store, or an
EC2 instance profile. It does not hardcode an AWS account.

## What it cleans

- Unattached EBS volumes older than 24 hours
- Unused Elastic IPs
- Stopped EC2 instances older than 7 days, only when tagged `infra-guard:cleanup=true`
- Owned EBS snapshots older than 30 days, unless referenced by an AMI or tagged `keep=true`
- Orphaned non-default security groups with no ingress rules and no attached ENIs

Any supported resource tagged `infra-guard:skip=true` is ignored.

## AWS connection

Verify the active account before running anything that can mutate AWS:

```bash
aws sts get-caller-identity
aws configure list
```

## S3 state bucket

Create or repair the versioned state bucket (versioning, AES-256 encryption, Glacier
lifecycle for old noncurrent versions):

```bash
export AWS_DEFAULT_REGION=ap-south-1
export S3_STATE_BUCKET=infra-guard-state
bash scripts/bootstrap_s3.sh
```

## Cleanup workflow

Dry-run is the default safe operating mode:

```bash
python3 scripts/cleanup.py --dry-run --log-bucket "$S3_STATE_BUCKET"
```

Actual cleanup requires explicit confirmation:

```bash
python3 scripts/cleanup.py --confirm --log-bucket "$S3_STATE_BUCKET"
```

Useful options:

- `--region` — AWS region override
- `--resource-tag-key` / `--resource-tag-value` — restrict cleanup to tagged resources
- `--ebs-min-age-hours`, `--stopped-instance-min-age-days`, `--snapshot-min-age-days` — age thresholds
- `--metrics-file` — Prometheus textfile output path (default `monitoring/textfile/infra_guard.prom`)

The run log is uploaded to S3 under the `cleanup-logs/` prefix. Exit code is non-zero
if any deletion or release fails.

## Test environment

`terraform/` provisions a low-cost, disposable fixture (stopped instance, unattached
volume, unused EIP, old snapshot, orphan security group) so you can exercise the cleanup
safely. See [terraform/README.md](terraform/README.md).

## S3 state sync

```bash
bash scripts/s3-sync.sh
```

Uploads Terraform state and Grafana dashboards to the state bucket, and writes sync
metrics to `monitoring/textfile/s3_sync.prom`.

## Monitoring

```bash
cd monitoring
docker compose up -d
```

- Prometheus: `http://localhost:9090`
- node_exporter: `http://localhost:9100` (exposes the textfile metrics)
- Grafana: `http://localhost:3000` (defaults to `admin`/`admin`)

See [monitoring/README.md](monitoring/README.md).

## Jenkins

The root `Jenkinsfile` is the source of truth. Jenkins builds `Dockerfile.jenkins-agent`
so the AWS CLI, Python, boto3, Bash, and Docker Compose are available without installing
tools during the run. Jenkins must provide AWS credentials through its credentials store,
instance profile, or environment. The pipeline lints the scripts, validates the AWS
identity, bootstraps S3, runs cleanup in dry-run mode, applies cleanup on `main` or the
weekly cron, syncs state to S3, and deploys the monitoring stack.
