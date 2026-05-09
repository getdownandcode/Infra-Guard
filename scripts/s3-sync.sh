#!/bin/bash
set -e

START_TIME=$(date +%s)
S3_BUCKET=${S3_STATE_BUCKET:-"infra-guard-state"}
S3_DEST="s3://${S3_BUCKET}/terraform/"
SYNC_ROOT=${SYNC_ROOT:-"."}

echo "Starting state synchronization to ${S3_DEST}..."

if [ -d "${SYNC_ROOT}/monitoring/prometheus_data" ]; then
    echo "Taking Prometheus TSDB snapshot..."
    mkdir -p snapshots/prometheus
    tar -czf "snapshots/prometheus/tsdb_$(date +%Y%m%d).tar.gz" "${SYNC_ROOT}/monitoring/prometheus_data" || true
    aws s3 sync snapshots/prometheus "s3://${S3_BUCKET}/prometheus/snapshots/"
fi

if [ -f "${SYNC_ROOT}/terraform.tfstate" ]; then
    aws s3 cp "${SYNC_ROOT}/terraform.tfstate" "${S3_DEST}terraform.tfstate" --sse AES256
    echo "Terraform state synchronized."
else
    echo "No terraform.tfstate found, skipping."
fi

if [ -d "${SYNC_ROOT}/monitoring/grafana/provisioning/dashboards" ]; then
    aws s3 sync "${SYNC_ROOT}/monitoring/grafana/provisioning/dashboards" "s3://${S3_BUCKET}/grafana/dashboards/" --sse AES256
    echo "Grafana dashboards synchronized."
fi

if [ -d "${SYNC_ROOT}/jenkins" ]; then
    aws s3 sync "${SYNC_ROOT}/jenkins" "s3://${S3_BUCKET}/jenkins/" --exclude "*" --include "*.xml" --sse AES256
    echo "Jenkins job configs synchronized."
fi

if [ -d "${SYNC_ROOT}/logs" ]; then
    aws s3 sync "${SYNC_ROOT}/logs" "s3://${S3_BUCKET}/cleanup-logs/" --delete --sse AES256
    echo "Cleanup logs synchronized."
fi

mkdir -p "${SYNC_ROOT}/monitoring/textfile"
cat > "${SYNC_ROOT}/monitoring/textfile/s3_sync.prom" <<METRICS
# HELP s3_sync_last_success_timestamp Unix timestamp of the latest successful S3 sync.
# TYPE s3_sync_last_success_timestamp gauge
s3_sync_last_success_timestamp $(date +%s)
# HELP s3_sync_success Whether the latest S3 sync completed successfully.
# TYPE s3_sync_success gauge
s3_sync_success 1
METRICS
echo "Wrote Prometheus metrics to ${SYNC_ROOT}/monitoring/textfile/s3_sync.prom."

echo "Sync completed in $(($(date +%s) - START_TIME)) seconds."
