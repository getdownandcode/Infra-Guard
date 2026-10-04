#!/bin/bash
set -e

START_TIME=$(date +%s)
AWS_REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-"ap-south-1"}}
SYNC_ROOT=${SYNC_ROOT:-"."}

if [ -z "${S3_STATE_BUCKET}" ]; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    if [ -n "${ACCOUNT_ID}" ]; then
        S3_BUCKET="infra-guard-state-${ACCOUNT_ID}-${AWS_REGION}"
    else
        S3_BUCKET="infra-guard-state"
    fi
else
    S3_BUCKET="${S3_STATE_BUCKET}"
fi

S3_DEST="s3://${S3_BUCKET}/terraform/"

write_metrics() {
    local success=$1
    mkdir -p "${SYNC_ROOT}/monitoring/textfile"
    cat > "${SYNC_ROOT}/monitoring/textfile/s3_sync.prom.tmp" <<METRICS
# HELP s3_sync_last_success_timestamp Unix timestamp of the latest successful S3 sync.
# TYPE s3_sync_last_success_timestamp gauge
s3_sync_last_success_timestamp $(date +%s)
# HELP s3_sync_success Whether the latest S3 sync completed successfully.
# TYPE s3_sync_success gauge
s3_sync_success ${success}
METRICS
    mv "${SYNC_ROOT}/monitoring/textfile/s3_sync.prom.tmp" "${SYNC_ROOT}/monitoring/textfile/s3_sync.prom"
}

trap 'write_metrics 0' ERR

echo "Starting state synchronization to ${S3_DEST}..."

TFSTATE=""
if [ -f "${SYNC_ROOT}/terraform/terraform.tfstate" ]; then
    TFSTATE="${SYNC_ROOT}/terraform/terraform.tfstate"
elif [ -f "${SYNC_ROOT}/terraform.tfstate" ]; then
    TFSTATE="${SYNC_ROOT}/terraform.tfstate"
fi

if [ -n "${TFSTATE}" ]; then
    aws s3 cp "${TFSTATE}" "${S3_DEST}terraform.tfstate" --region "${AWS_REGION}" --sse AES256
    echo "Terraform state synchronized."
else
    echo "No terraform.tfstate found, skipping."
fi

if [ -d "${SYNC_ROOT}/monitoring/grafana/provisioning/dashboards" ]; then
    aws s3 sync "${SYNC_ROOT}/monitoring/grafana/provisioning/dashboards" "s3://${S3_BUCKET}/grafana/dashboards/" --region "${AWS_REGION}" --sse AES256
    echo "Grafana dashboards synchronized."
fi

write_metrics 1
trap - ERR

echo "Wrote Prometheus metrics to ${SYNC_ROOT}/monitoring/textfile/s3_sync.prom."
echo "Sync completed in $(($(date +%s) - START_TIME)) seconds."
