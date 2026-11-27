output "run_analysis_function_urn" {
  description = "URN of the entry function (timer-triggered)"
  value       = huaweicloud_fgs_function.run_analysis.urn
}

output "check_analysis_function_urn" {
  value = huaweicloud_fgs_function.check_analysis.urn
}

output "send_findings_function_urn" {
  value = huaweicloud_fgs_function.send_findings.urn
}

output "timer_trigger_name" {
  description = "Name of the 12h timer trigger"
  value       = huaweicloud_fgs_trigger.schedule.timer[0].name
}

output "agency_name" {
  description = "IAM agency delegated to FunctionGraph (only when create_agency = true)"
  value       = var.create_agency ? huaweicloud_identity_agency.fg[0].name : null
}

output "smn_topic_urn" {
  description = "SMN topic for findings notifications"
  value       = huaweicloud_smn_topic.findings.topic_urn
}

output "code_bucket" {
  value = huaweicloud_obs_bucket.code.bucket
}
