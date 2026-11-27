"""run_analysis — starts a network access scope analysis task.

It loads the configured scopes, reads the live VPC topology, runs the
reachability analyzer for every scope, and sinks the findings to
SMN / LTS (SecMaster is disabled — no ingest API). Because the analyzer is
synchronous, this single function performs the whole analysis in one run.
"""
import logging
import os

from src.engine.analyzer import analyze_all
from src.engine.scope import load_scopes
from src.engine.topology import Topology
from src.shared.findings_sink import push_findings
from src.shared.huawei_clients import vpc_client

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCOPES_DIR = os.path.join(HERE, "src", "scopes")


def lambda_handler(event, context):
    scopes_dir = os.environ.get("SCOPES_DIR") or DEFAULT_SCOPES_DIR
    scopes = load_scopes(scopes_dir)
    logger.info("Loaded %d network access scopes from %s", len(scopes), scopes_dir)

    client = vpc_client(context)
    topo = Topology(client)

    findings = analyze_all(scopes, topo)

    details = []
    for scope in scopes:
        sf = [f for f in findings if f.scope_id == scope.scope_id]
        details.append(
            {
                "scope_id": scope.scope_id,
                "status": "succeeded",
                "findings_count": len(sf),
                "findings": [vars(f) for f in sf],
            }
        )

    result = {
        "scope_analysis_details": details,
        "total_findings": len(findings),
    }

    # 投递发现到 LTS/SMN。
    result["sink"] = push_findings(findings, context)
    return result
