# Infra-Guard

Infra-Guard is a lightweight AWS cost and health optimizer. It uses Jenkins for
automation, Python/boto3 for safe AWS cleanup, S3 for versioned state backups, and
Prometheus plus Grafana for observability.

The project uses the AWS credentials from the current shell, Jenkins agent, or EC2
instance profile. It does not hardcode an AWS account.

See `DEPLOYMENT.md` for setup and validation commands.
