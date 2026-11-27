# =============================================================================
# VPC Network Access Analyzer Automation — Huawei Cloud (Terraform)
#
# 架构说明：
#   FunctionGraph (run_analysis) --[TIMER 12h]--> reads VPC topology,
#   runs the self-built reachability analyzer, sinks findings to
#   SMN / LTS (SecMaster sink disabled — 无对应 ingest API)。
#   check_analysis & send_findings are deployed as independent functions
#   （详见 docs/）。
#
# Build the code packages first:  bash ../scripts/package.sh
# Then:  terraform init && terraform plan && terraform apply
# =============================================================================

resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# OBS bucket hosting the function code packages + SDK dependency layer
# -----------------------------------------------------------------------------
resource "huaweicloud_obs_bucket" "code" {
  bucket        = "${var.name_prefix}-code-${random_id.suffix.hex}"
  acl           = "private"
  force_destroy = true

  tags = {
    created_by = "vpc-network-access-analysis"
    purpose    = "vpcaa-functiongraph-packages"
  }
}

# Per-function code packages (SDK is bundled inside each zip by
# scripts/build_packages.py, so no separate fgs dependency layer is needed).
resource "huaweicloud_obs_bucket_object" "run_analysis" {
  bucket = huaweicloud_obs_bucket.code.bucket
  key    = "run_analysis.zip"
  source = "${path.module}/${var.package_dir}/run_analysis.zip"
  etag   = filemd5("${path.module}/${var.package_dir}/run_analysis.zip")
}

resource "huaweicloud_obs_bucket_object" "check_analysis" {
  bucket = huaweicloud_obs_bucket.code.bucket
  key    = "check_analysis.zip"
  source = "${path.module}/${var.package_dir}/check_analysis.zip"
  etag   = filemd5("${path.module}/${var.package_dir}/check_analysis.zip")
}

resource "huaweicloud_obs_bucket_object" "send_findings" {
  bucket = huaweicloud_obs_bucket.code.bucket
  key    = "send_findings.zip"
  source = "${path.module}/${var.package_dir}/send_findings.zip"
  etag   = filemd5("${path.module}/${var.package_dir}/send_findings.zip")
}

# -----------------------------------------------------------------------------
# IAM agency: delegate VPC read + SMN publish access to FunctionGraph
# -----------------------------------------------------------------------------
# SECURE PATH (create_agency = true): FunctionGraph assumes this agency at
# runtime so the functions need no long-term AK/SK.
#
# CAVEAT: in accounts where the deploying IAM user lacks agency-trust
# permissions, FunctionGraph rejects the agency with FSS.1501 ("agency does not
# exist") even though the agency exists in IAM. For such accounts set
# create_agency = false and the functions fall back to HW_ACCESS_KEY /
# HW_SECRET_KEY injected into their environment (the runtime code in
# src/shared/huawei_clients.py already supports this). This deployment uses the
# fallback path because the deploying user (GT-dgcmy) gets 403 on
# iam:agencies:list and FunctionGraph cannot resolve the agency.
resource "huaweicloud_identity_agency" "fg" {
  count                 = var.create_agency ? 1 : 0
  name                  = var.agency_name
  description           = "Agency for FunctionGraph to read VPC topology and push findings"
  duration              = "FOREVER"
  delegated_service_name = "functiongraph"

  project_role {
    project = var.region
    roles = [
      "VPC ReadOnlyAccess",
      "SMN FullAccess",
    ]
  }
}

# Resolve the project id for the region (required by BasicCredentials; the
# region name alone yields 401 "get token error"). Non-secret. Sourced from a
# variable because there is no project-id data source; for cn-north-4 the
# project id equals the account's cn-north-4 project UUID.


# -----------------------------------------------------------------------------
# LTS log group / stream for function logs
# -----------------------------------------------------------------------------
resource "huaweicloud_lts_group" "vpcaa" {
  group_name = "${var.name_prefix}-func-logs"
  ttl_in_days = 7
}

resource "huaweicloud_lts_stream" "vpcaa" {
  group_id    = huaweicloud_lts_group.vpcaa.id
  stream_name = "${var.name_prefix}-stream"
}

# -----------------------------------------------------------------------------
# SMN topic for findings notifications
# -----------------------------------------------------------------------------
resource "huaweicloud_smn_topic" "findings" {
  name = var.smn_topic_name
}

# -----------------------------------------------------------------------------
# FunctionGraph functions
# -----------------------------------------------------------------------------
locals {
  code_url = {
    run   = format("https://%s/%s", huaweicloud_obs_bucket.code.bucket_domain_name, huaweicloud_obs_bucket_object.run_analysis.key)
    check = format("https://%s/%s", huaweicloud_obs_bucket.code.bucket_domain_name, huaweicloud_obs_bucket_object.check_analysis.key)
    send  = format("https://%s/%s", huaweicloud_obs_bucket.code.bucket_domain_name, huaweicloud_obs_bucket_object.send_findings.key)
  }

  envs = {
    HW_REGION_NAME          = var.region
    HW_PROJECT_ID           = var.project_id
    HW_ACCESS_KEY           = var.hw_access_key
    HW_SECRET_KEY           = var.hw_secret_key
    SMN_TOPIC_URN           = huaweicloud_smn_topic.findings.topic_urn
    VPCA_ID                 = var.vpc_a_id
    VPCB_ID                 = var.vpc_b_id
  }

  # Per-function env: include the code package etag so a rebuilt function zip
  # (which changes the OBS object etag) forces the function to re-deploy and
  # re-pull code from OBS. Without this, terraform sees no diff and the
  # function keeps stale code.
  fn_envs = {
    run = merge(local.envs, { CODE_ETAG = huaweicloud_obs_bucket_object.run_analysis.etag })
    check = merge(local.envs, { CODE_ETAG = huaweicloud_obs_bucket_object.check_analysis.etag })
    send = merge(local.envs, { CODE_ETAG = huaweicloud_obs_bucket_object.send_findings.etag })
  }
}

resource "huaweicloud_fgs_function" "run_analysis" {
  name           = "${var.name_prefix}-run-analysis"
  app            = "default"
  runtime        = var.function_runtime
  timeout        = var.function_timeout
  memory_size    = var.function_memory_size
  handler        = "app.lambda_handler"
  code_type      = "obs"
  code_url       = local.code_url.run
  agency         = var.create_agency ? huaweicloud_identity_agency.fg[0].name : null
  user_data      = jsonencode(local.fn_envs.run)
  enable_lts_log = true
  log_group_id    = huaweicloud_lts_group.vpcaa.id
  log_stream_name = "${var.name_prefix}-stream"

  # FunctionGraph does NOT reliably re-pull code from OBS on an in-place update;
  # only a fresh create does. Recreate the function whenever its code package
  # (the OBS object etag) changes so deployments always ship the new code.
  lifecycle {
    replace_triggered_by = [huaweicloud_obs_bucket_object.run_analysis]
  }
}

resource "huaweicloud_fgs_function" "check_analysis" {
  name           = "${var.name_prefix}-check-analysis"
  app            = "default"
  runtime        = var.function_runtime
  timeout        = var.function_timeout
  memory_size    = var.function_memory_size
  handler        = "app.lambda_handler"
  code_type      = "obs"
  code_url       = local.code_url.check
  agency         = var.create_agency ? huaweicloud_identity_agency.fg[0].name : null
  user_data      = jsonencode(local.fn_envs.check)
  enable_lts_log = true
  log_group_id    = huaweicloud_lts_group.vpcaa.id
  log_stream_name = "${var.name_prefix}-stream"

  lifecycle {
    replace_triggered_by = [huaweicloud_obs_bucket_object.check_analysis]
  }
}

resource "huaweicloud_fgs_function" "send_findings" {
  name           = "${var.name_prefix}-send-findings"
  app            = "default"
  runtime        = var.function_runtime
  timeout        = var.function_timeout
  memory_size    = var.function_memory_size
  handler        = "app.lambda_handler"
  code_type      = "obs"
  code_url       = local.code_url.send
  agency         = var.create_agency ? huaweicloud_identity_agency.fg[0].name : null
  user_data      = jsonencode(local.fn_envs.send)
  enable_lts_log = true
  log_group_id    = huaweicloud_lts_group.vpcaa.id
  log_stream_name = "${var.name_prefix}-stream"

  lifecycle {
    replace_triggered_by = [huaweicloud_obs_bucket_object.send_findings]
  }
}

# -----------------------------------------------------------------------------
# Timer trigger (定时调度，rate(12 hours))
# -----------------------------------------------------------------------------
resource "huaweicloud_fgs_trigger" "schedule" {
  function_urn = huaweicloud_fgs_function.run_analysis.urn
  type         = "TIMER"
  status       = "ACTIVE"

  timer {
    name          = "${var.name_prefix}-schedule"
    schedule_type = "Rate"
    schedule      = var.schedule_expression
  }
}
