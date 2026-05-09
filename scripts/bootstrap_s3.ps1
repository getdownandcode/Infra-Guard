param(
    [string]$Bucket = $env:S3_STATE_BUCKET,
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } elseif ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { "ap-south-1" })
)

$ErrorActionPreference = "Stop"

if (-not $Bucket) {
    $Bucket = "infra-guard-state"
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw "AWS CLI was not found in PATH. Install AWS CLI v2 or open a terminal where 'aws' works."
}

Write-Host "Ensuring s3://$Bucket exists in $Region..."

aws s3api head-bucket --bucket $Bucket 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Bucket already exists and is accessible."
} else {
    if ($Region -eq "us-east-1") {
        aws s3api create-bucket --bucket $Bucket
    } else {
        aws s3api create-bucket `
            --bucket $Bucket `
            --region $Region `
            --create-bucket-configuration "LocationConstraint=$Region"
    }
}

aws s3api put-bucket-versioning `
    --bucket $Bucket `
    --versioning-configuration Status=Enabled

$encryptionConfig = @{
    Rules = @(
        @{
            ApplyServerSideEncryptionByDefault = @{
                SSEAlgorithm = "AES256"
            }
        }
    )
} | ConvertTo-Json -Depth 5 -Compress

$encryptionFile = New-TemporaryFile
Set-Content -Path $encryptionFile -Value $encryptionConfig -NoNewline

try {
    aws s3api put-bucket-encryption `
        --bucket $Bucket `
        --server-side-encryption-configuration "file://$encryptionFile"
} finally {
    Remove-Item -LiteralPath $encryptionFile -Force
}

$lifecycleConfig = @{
    Rules = @(
        @{
            ID = "archive-old-noncurrent-state"
            Status = "Enabled"
            Filter = @{ Prefix = "" }
            NoncurrentVersionTransitions = @(
                @{
                    NoncurrentDays = 90
                    StorageClass = "GLACIER"
                }
            )
            NoncurrentVersionExpiration = @{
                NewerNoncurrentVersions = 30
                NoncurrentDays = 365
            }
        }
    )
} | ConvertTo-Json -Depth 8 -Compress

$lifecycleFile = New-TemporaryFile
Set-Content -Path $lifecycleFile -Value $lifecycleConfig -NoNewline

try {
    aws s3api put-bucket-lifecycle-configuration `
        --bucket $Bucket `
        --lifecycle-configuration "file://$lifecycleFile"
} finally {
    Remove-Item -LiteralPath $lifecycleFile -Force
}

Write-Host "Bucket versioning, AES-256 encryption, and lifecycle policy are configured."
