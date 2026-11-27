variable "region" {
  description = "Huawei Cloud region, e.g. cn-north-4"
  type        = string
  default     = "cn-north-4"
}

variable "name_prefix" {
  description = "Prefix for all created resources"
  type        = string
  default     = "vpcaa"
}

variable "function_runtime" {
  description = "FunctionGraph Python runtime"
  type        = string
  default     = "Python3.9"
}

variable "function_memory_size" {
  description = "Function memory size in MB"
  type        = number
  default     = 256
}

variable "function_timeout" {
  description = "Function timeout in seconds (max 300)"
  type        = number
  default     = 300
}

variable "schedule_expression" {
  description = "Timer trigger Rate schedule. '12h' == every 12 hours."
  type        = string
  default     = "12h"
}

variable "agency_name" {
  description = "IAM agency name delegated to FunctionGraph"
  type        = string
  default     = "vpcaa-fg-agency"
}

variable "create_agency" {
  description = "Create an IAM agency and delegate it to FunctionGraph for credential-free runtime auth. NOTE: in accounts where the deploying IAM user lacks agency trust permissions, FunctionGraph returns FSS.1501 ('agency does not exist'); set this to false and the functions fall back to HW_ACCESS_KEY/HW_SECRET_KEY from the environment instead."
  type        = bool
  default     = false
}

variable "hw_access_key" {
  description = "Huawei Cloud AK. Injected into the functions' environment (user_data). Prefer passing via -var at apply time; never commit a literal."
  type        = string
  sensitive   = true
  default     = ""
}

variable "hw_secret_key" {
  description = "Huawei Cloud SK. Injected into the functions' environment (user_data). Prefer passing via -var at apply time; never commit a literal."
  type        = string
  sensitive   = true
  default     = ""
}

variable "package_dir" {
  description = "Local directory (relative to this file) containing the built zip packages"
  type        = string
  default     = "build"
}

variable "smn_topic_name" {
  description = "SMN topic name for findings notifications"
  type        = string
  default     = "vpcaa-findings"
}

variable "project_id" {
  description = "Huawei Cloud project id (UUID) for the target region. Required by BasicCredentials; the region name alone yields 401 'get token error'. Resolve via the console (My Credentials -> project id) or `openstack project list`."
  type        = string
  default     = "cc2cb3d01b0c46798d77c4cd8ecf6b7e"
}

variable "vpc_a_id" {
  description = "Real VPC ID substituted into the cross-VPC scope template at runtime (env VPCA_ID). Leave empty to keep the REPLACE_VPC_A_ID placeholder (cross_vpc scope then yields 0 findings)."
  type        = string
  default     = ""
}

variable "vpc_b_id" {
  description = "Real VPC ID substituted into the cross-VPC scope template at runtime (env VPCB_ID). Leave empty to keep the REPLACE_VPC_B_ID placeholder (cross_vpc scope then yields 0 findings)."
  type        = string
  default     = ""
}
