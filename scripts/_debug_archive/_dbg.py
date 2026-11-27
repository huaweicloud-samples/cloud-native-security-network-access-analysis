import os
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkvpc.v2 import (
    VpcClient, ListSecurityGroupsRequest, ListSecurityGroupRulesRequest,
)
from huaweicloudsdkvpc.v2.region.vpc_region import VpcRegion
import huaweicloudsdkvpc.v2 as v2
ak=os.environ['HW_ACCESS_KEY']; sk=os.environ['HW_SECRET_KEY']; proj=os.environ['HW_PROJECT_ID']; reg=os.environ['HW_REGION_NAME']
c=VpcClient.new_builder().with_credentials(BasicCredentials(ak,sk,proj)).with_region(VpcRegion.value_of(reg)).build()
print("CreateSecurityGroupRequest:", hasattr(v2,'CreateSecurityGroupRequest'))
print("CreateSecurityGroupRuleRequest:", hasattr(v2,'CreateSecurityGroupRuleRequest'))
print("CreateSecurityGroupRuleOption:", hasattr(v2,'CreateSecurityGroupRuleOption'))
# inspect Sys-default rules
resp=c.list_security_groups(ListSecurityGroupsRequest())
for g in (resp.security_groups or []):
    if g.name in ("default","Sys-default") or getattr(g,'vpc_id',None)=='default':
        print("SG", g.id, g.name, "vpc_id=", getattr(g,'vpc_id',None))
        rr=c.list_security_group_rules(ListSecurityGroupRulesRequest(security_group_id=g.id))
        for rule in (rr.security_group_rules or []):
            print("   rule", getattr(rule,'direction',None), getattr(rule,'action',None),
                  "proto=",getattr(rule,'protocol',None),
                  "port",getattr(rule,'port_range_min',None),"-",getattr(rule,'port_range_max',None),
                  "remote=",getattr(rule,'remote_ip_prefix',None),"rg=",getattr(rule,'remote_group_id',None))
