#!/usr/bin/env python3
"""Synchronously invoke the deployed run_analysis function and print its output."""
import os, sys, json
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkfunctiongraph.v2 import (
    FunctionGraphClient, InvokeFunctionRequest,
)
from huaweicloudsdkfunctiongraph.v2.region.functiongraph_region import FunctionGraphRegion

ak = os.environ["HW_ACCESS_KEY"]
sk = os.environ["HW_SECRET_KEY"]
region = os.environ["HW_REGION_NAME"]
project = os.environ["HW_PROJECT_ID"]
urn = "urn:fss:{region}:{proj}:function:default:vpcaa-run-analysis:latest".format(
    region=region, proj=project)

cred = BasicCredentials(ak, sk, project)
client = (FunctionGraphClient.new_builder()
          .with_credentials(cred)
          .with_region(FunctionGraphRegion.value_of(region))
          .build())

req = InvokeFunctionRequest(function_urn=urn, body=json.dumps({}))
resp = client.invoke_function(req)
raw = getattr(resp, "raw_content", None)
if raw:
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = str(raw)
    print("=== raw_content ===")
    print(text)
else:
    print("=== raw_content empty; full resp ===")
    print(resp.to_dict())
