output "aws_region" {
  description = "AWS region used for the test environment."
  value       = var.aws_region
}

output "state_bucket_name" {
  description = "S3 bucket used for Infra-Guard state and cleanup logs."
  value       = aws_s3_bucket.state.id
}

output "stopped_instance_id" {
  description = "EC2 instance tagged for stopped-instance cleanup."
  value       = aws_instance.stopped_cleanup_target.id
}

output "unattached_volume_id" {
  description = "Unattached EBS volume tagged for cleanup."
  value       = aws_ebs_volume.unattached_cleanup_target.id
}

output "snapshot_id" {
  description = "EBS snapshot tagged for cleanup."
  value       = aws_ebs_snapshot.old_snapshot_cleanup_target.id
}

output "unused_eip_allocation_id" {
  description = "Unused Elastic IP allocation tagged for cleanup."
  value       = aws_eip.unused_cleanup_target.allocation_id
}

output "orphan_security_group_id" {
  description = "Unattached security group with no ingress rules tagged for cleanup."
  value       = aws_security_group.orphan_cleanup_target.id
}
