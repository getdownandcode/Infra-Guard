#!/bin/bash
set -e

S3_BUCKET=${S3_STATE_BUCKET:-"infra-guard-state"}
AWS_REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-"ap-south-1"}}

echo "Ensuring s3://${S3_BUCKET} exists in ${AWS_REGION}..."

if aws s3api head-bucket --bucket "${S3_BUCKET}" 2>/dev/null; then
    echo "Bucket already exists and is accessible."
else
    if [ "${AWS_REGION}" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "${S3_BUCKET}"
    else
        aws s3api create-bucket \
            --bucket "${S3_BUCKET}" \
            --region "${AWS_REGION}" \
            --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
    fi
fi

aws s3api put-bucket-versioning \
    --bucket "${S3_BUCKET}" \
    --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
    --bucket "${S3_BUCKET}" \
    --server-side-encryption-configuration '{
      "Rules": [
        {
          "ApplyServerSideEncryptionByDefault": {
            "SSEAlgorithm": "AES256"
          }
        }
      ]
    }'

aws s3api put-bucket-lifecycle-configuration \
    --bucket "${S3_BUCKET}" \
    --lifecycle-configuration '{
      "Rules": [
        {
          "ID": "archive-old-noncurrent-state",
          "Status": "Enabled",
          "Filter": { "Prefix": "" },
          "NoncurrentVersionTransitions": [
            {
              "NoncurrentDays": 90,
              "StorageClass": "GLACIER"
            }
          ],
          "NoncurrentVersionExpiration": {
            "NewerNoncurrentVersions": 30,
            "NoncurrentDays": 365
          }
        }
      ]
    }'

echo "Bucket versioning, AES-256 encryption, and lifecycle policy are configured."
