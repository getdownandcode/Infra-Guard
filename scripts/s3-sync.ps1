param(
    [string]$Bucket = $env:S3_STATE_BUCKET,
    [string]$SyncRoot = $(if ($env:SYNC_ROOT) { $env:SYNC_ROOT } else { "." })
)

$ErrorActionPreference = "Stop"

if (-not $Bucket) {
    $Bucket = "infra-guard-state"
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw "AWS CLI was not found in PATH. Install AWS CLI v2 or open a terminal where 'aws' works."
}

$startTime = Get-Date
$syncRootPath = Resolve-Path -LiteralPath $SyncRoot
$s3Dest = "s3://$Bucket/terraform/"

Write-Host "Starting state synchronization to $s3Dest..."

$prometheusData = Join-Path $syncRootPath "monitoring/prometheus_data"
if (Test-Path -LiteralPath $prometheusData -PathType Container) {
    Write-Host "Prometheus TSDB snapshot export is only supported by scripts/s3-sync.sh."
}

$terraformState = Join-Path $syncRootPath "terraform/terraform.tfstate"
if (-not (Test-Path -LiteralPath $terraformState -PathType Leaf)) {
    $terraformState = Join-Path $syncRootPath "terraform.tfstate"
}

if (Test-Path -LiteralPath $terraformState -PathType Leaf) {
    aws s3 cp $terraformState "${s3Dest}terraform.tfstate" --sse AES256
    Write-Host "Terraform state synchronized."
} else {
    Write-Host "No terraform.tfstate found, skipping."
}

$dashboardDir = Join-Path $syncRootPath "monitoring/grafana/provisioning/dashboards"
if (Test-Path -LiteralPath $dashboardDir -PathType Container) {
    aws s3 sync $dashboardDir "s3://$Bucket/grafana/dashboards/" --sse AES256
    Write-Host "Grafana dashboards synchronized."
}

$jenkinsDir = Join-Path $syncRootPath "jenkins"
if (Test-Path -LiteralPath $jenkinsDir -PathType Container) {
    aws s3 sync $jenkinsDir "s3://$Bucket/jenkins/" --exclude "*" --include "*.xml" --sse AES256
    Write-Host "Jenkins job configs synchronized."
}

$logsDir = Join-Path $syncRootPath "logs"
if (Test-Path -LiteralPath $logsDir -PathType Container) {
    aws s3 sync $logsDir "s3://$Bucket/cleanup-logs/" --delete --sse AES256
    Write-Host "Cleanup logs synchronized."
}

$duration = [int]((Get-Date) - $startTime).TotalSeconds
$metricsDir = Join-Path $syncRootPath "monitoring/textfile"
$metricsFile = Join-Path $metricsDir "s3_sync.prom"
New-Item -ItemType Directory -Force -Path $metricsDir | Out-Null
$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
@"
# HELP s3_sync_last_success_timestamp Unix timestamp of the latest successful S3 sync.
# TYPE s3_sync_last_success_timestamp gauge
s3_sync_last_success_timestamp $timestamp
# HELP s3_sync_success Whether the latest S3 sync completed successfully.
# TYPE s3_sync_success gauge
s3_sync_success 1
"@ | Set-Content -Path $metricsFile -NoNewline
Write-Host "Wrote Prometheus metrics to $metricsFile."
Write-Host "Sync completed in $duration seconds."
