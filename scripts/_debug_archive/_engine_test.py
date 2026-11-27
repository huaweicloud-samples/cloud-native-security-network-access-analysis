import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkvpc.v2 import VpcClient
from huaweicloudsdkvpc.v2.region.vpc_region import VpcRegion
from engine.topology import Topology
from engine.scope import Scope
from engine.analyzer import _analyze_cross_vpc

ak=os.environ['HW_ACCESS_KEY']; sk=os.environ['HW_SECRET_KEY']; proj=os.environ['HW_PROJECT_ID']; reg=os.environ['HW_REGION_NAME']
client = VpcClient.new_builder().with_credentials(BasicCredentials(ak,sk,proj)).with_region(VpcRegion.value_of(reg)).build()
topo = Topology(client)

VPC_A = "e0aff54e-8a07-4516-b203-ebd049034251"
VPC_B = "4ae9889a-9b6a-4619-9b83-40e54eacb556"

d = json.load(open(os.path.join(os.path.dirname(__file__), "..", "src", "scopes", "all_vpc_egress_to_port.json")))
d["match"]["source"]["value"] = VPC_A
d["match"]["destination"]["value"] = VPC_B
scope = Scope.from_dict(d)
f = _analyze_cross_vpc(scope, topo)
print("cross_vpc findings:", len(f))
for x in f:
    print("  DIR", x.direction, "| SRC", x.source, "-> DST", x.destination, "| PORTS", x.ports)
    print("  detail:", x.detail)
