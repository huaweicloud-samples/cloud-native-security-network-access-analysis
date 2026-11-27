"""send_findings — publishes network access analysis findings.

It pushes analysis results (produced by ``run_analysis``) to SMN / LTS
via the shared findings sink (SecMaster is disabled — no ingest API). It is exposed as an independent
FunctionGraph function so results can be re-published on demand (replay / manual
trigger) without re-running the analysis.
"""
import logging

from src.engine.analyzer import Finding
from src.shared.findings_sink import push_findings

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    details = (event or {}).get("scope_analysis_details", [])
    findings = []
    for d in details:
        for f in d.get("findings", []):
            try:
                findings.append(Finding(**f))
            except Exception as exc:  # pragma: no cover
                logger.warning("Skipping malformed finding: %s", exc)
    return push_findings(findings, context)
