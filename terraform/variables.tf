variable "aws_region" {
  description = "AWS region used for the Infra-Guard test environment."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Name prefix for test resources."
  type        = string
  default     = "infra-guard-test"
}

variable "state_bucket_name" {
  description = "Optional globally unique S3 bucket name. Leave empty to generate one."
  type        = string
  default     = ""
}

variable "instance_type" {
  description = "Small EC2 instance type used for the stopped-instance cleanup test."
  type        = string
  default     = "t3.micro"
}

variable "common_tags" {
  description = "Extra tags applied to all resources."
  type        = map(string)
  default     = {}
}
