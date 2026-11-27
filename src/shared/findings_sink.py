"""Findings sink — sends analysis results to Huawei Cloud security surfaces.

Delivery targets:
  * **LTS** (日志服务)        -> structured JSON logs (FunctionGraph streams
    function logs to LTS automatically; we just emit the JSON). Always on.
  * **SMN** (消息通知服务)    -> publish a human-readable summary (notification).
  * **SecMaster** (安全云脑)  -> DISABLED. SecMaster v2 SDK only exposes
    ``create_alert_rule`` (which provisions a *detection rule* / ISAP job), not
    an ad-hoc ``CreateAlert`` ingestion endpoint. Findings live in LTS + SMN.
  * **LTS** (日志服务)        -> structured JSON logs (FunctionGraph streams
    function logs to LTS automatically; we just emit the JSON).

All targets are opt-in via environment variables so the function always
produces LTS output even if SecMaster/SMN are not configured. Failures on a
single target are logged and do not abort the run.
"""
from __future__ import annotations

import json
import logging
import os
from typing import List

from huaweicloudsdkcore.exceptions import exceptions

from src.engine.analyzer import Finding

logger = logging.getLogger(__name__)


def send_to_secmaster(findings: List[Finding], context=None) -> dict:
    """Disabled — see module docstring (SecMaster v2 has no findings ingestion API).

    Kept as a no-op so callers don't need to branch. Findings are delivered via
    LTS (always) and SMN (opt-in) instead.
    """
    logger.info(
        "SecMaster sink disabled: SecMaster v2 has no ad-hoc finding ingestion "
        "API (only create_alert_rule). Findings are delivered via LTS + SMN."
    )
    return {"enabled": False, "reason": "no_secmaster_findings_api"}


def send_to_smn(summary: dict, context=None) -> dict:
    topic_urn = os.environ.get("SMN_TOPIC_URN")
    if not topic_urn:
        logger.info("SMN_TOPIC_URN not set; skipping SMN notification.")
        return {"enabled": False}
    from huaweicloudsdksmn.v2 import (
        PublishMessageRequest,
        PublishMessageRequestBody,
    )  # noqa: WPS433
    from .huawei_clients import smn_client

    client = smn_client(context)
    try:
        body = PublishMessageRequestBody(
            subject="VPC Network Access Analysis Findings",
            message=json.dumps(summary, ensure_ascii=False),
        )
        req = PublishMessageRequest(topic_urn=topic_urn)
        req.body = body
        client.publish_message(req)
        return {"enabled": True}
    except exceptions.ClientRequestException as e:  # pragma: no cover
        logger.error(f"SMN publish failed: {e.error_code}")
        return {"enabled": True, "error": e.error_code}


def push_findings(findings: List[Finding], context=None) -> dict:
    """Push findings to all configured surfaces and always emit LTS JSON."""
    summary = {
        "schema": "vpc-network-access-analysis/1.0",
        "total_findings": len(findings),
        "findings": [vars(f) for f in findings],
    }
    # LTS: FunctionGraph streams these logs to the function's LTS log stream.
    logger.info("NETWORK_ACCESS_FINDINGS " + json.dumps(summary, ensure_ascii=False))

    secmaster = send_to_secmaster(findings, context)
    smn = send_to_smn(summary, context)
    return {"lts": True, "secmaster": secmaster, "smn": smn, "total": len(findings)}
