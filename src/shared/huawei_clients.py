"""Huawei Cloud SDK client factory.

Credentials are taken from the FunctionGraph runtime ``context`` (temporary
agency credentials) when available, otherwise from environment variables
(only for local testing). Real AK/SK are never hard-coded; they are injected
by the runtime or the environment.

NOTE: the SDK *modules* are imported under aliases (``vpc_sdk`` / ``smn_sdk`` /
``secmaster_sdk``) so the function names below (``vpc_client`` / ``smn_client`` /
``secmaster_client``) do NOT shadow the modules and break
``module.ClientClass.new_builder()`` at call time.
"""
from __future__ import annotations

import os

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.region.region import Region
# VPC: route tables / subnets / security groups / ports / routes all live in
# the **v2** VPC SDK. The v3 SDK dropped them, so importing them from v3 makes
# the whole engine fail at import time.
from huaweicloudsdkvpc.v2 import vpc_client as vpc_sdk
from huaweicloudsdksmn.v2 import smn_client as smn_sdk
from huaweicloudsdksecmaster.v2 import secmaster_client as secmaster_sdk

# Per-service global endpoints (Huawei Cloud). ``{region}`` is substituted.
_ENDPOINTS = {
    "vpc": "https://vpc.{region}.myhuaweicloud.com",
    "smn": "https://smn.{region}.myhuaweicloud.com",
    "secmaster": "https://secmaster.{region}.myhuaweicloud.com",
}


def _region(context=None) -> str:
    if context is not None:
        r = getattr(context, "getRegion", lambda: None)()
        if r:
            return r
    return os.environ.get("HW_REGION_NAME", "cn-north-4")


def _region_obj(service: str, context=None) -> Region:
    """Build a ``Region`` object (required by ``with_region`` — a plain string is rejected)."""
    region = _region(context)
    endpoint = _ENDPOINTS[service].format(region=region)
    return Region(region, endpoint)


def build_credentials(context=None) -> BasicCredentials:
    ak = sk = token = None
    if context is not None:
        ak = context.getAccessKey()
        sk = context.getSecretKey()
        token = context.getSecurityToken()
    if not ak or not sk:
        ak = os.environ.get("HW_ACCESS_KEY")
        sk = os.environ.get("HW_SECRET_KEY")
        token = os.environ.get("HW_SECURITY_TOKEN")
    # BasicCredentials(ak, sk, project_id) — the 3rd positional is the *project
    # id*, NOT a region or security token. For cn-north-4 the default project
    # id equals the region name; allow override via HW_PROJECT_ID.
    project_id = os.environ.get("HW_PROJECT_ID") or _region(context)
    cred = BasicCredentials(ak, sk, project_id)
    if token:
        cred = cred.with_security_token(token)
    return cred


def vpc_client(context=None):
    return (
        vpc_sdk.VpcClient.new_builder()
        .with_credentials(build_credentials(context))
        .with_region(_region_obj("vpc", context))
        .build()
    )


def smn_client(context=None):
    return (
        smn_sdk.SmnClient.new_builder()
        .with_credentials(build_credentials(context))
        .with_region(_region_obj("smn", context))
        .build()
    )


def secmaster_client(context=None):
    return (
        secmaster_sdk.SecMasterClient.new_builder()
        .with_credentials(build_credentials(context))
        .with_region(_region_obj("secmaster", context))
        .build()
    )
