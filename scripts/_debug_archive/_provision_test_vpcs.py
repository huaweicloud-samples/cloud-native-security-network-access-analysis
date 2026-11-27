"""Provision two test VPCs + subnet + port + peering + route in cn-north-4.

Idempotent: reuses resources that already exist (by name), so re-runs are safe.
Goal: make the cross-VPC scope (all_vpc_egress_to_port) actually produce a
finding. No ECS is created (ports/ENIs are free) — a bare port attached to the
default security group (which allows all egress) is enough for the engine.

AK/SK are injected via env vars; nothing secret is written here.
"""
import os
import sys
import time

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkvpc.v2.region.vpc_region import VpcRegion
from huaweicloudsdkvpc.v2 import (
    VpcClient,
    ListVpcsRequest,
    ListSubnetsRequest,
    ListVpcPeeringsRequest,
    ListVpcRoutesRequest,
    ListPortsRequest,
    ListSecurityGroupsRequest,
    ShowVpcRequest,
    CreateVpcRequest,
    CreateVpcRequestBody,
    CreateVpcOption,
    CreateSubnetRequest,
    CreateSubnetRequestBody,
    CreateSubnetOption,
    CreateVpcPeeringRequest,
    CreateVpcPeeringRequestBody,
    CreateVpcPeeringOption,
    VpcInfo,
    AcceptVpcPeeringRequest,
    CreateVpcRouteRequest,
    CreateVpcRouteRequestBody,
    CreateVpcRouteOption,
    CreatePortRequest,
    CreatePortRequestBody,
    CreatePortOption,
    FixedIp,
)

AK = os.environ["HW_ACCESS_KEY"]
SK = os.environ["HW_SECRET_KEY"]
REGION = os.environ["HW_REGION_NAME"]
PROJECT = os.environ["HW_PROJECT_ID"]

CIDR_A = "192.168.10.0/24"
CIDR_B = "192.168.20.0/24"
SUBNET_A = "192.168.10.0/26"
GW_A = "192.168.10.1"
PORT_IP = "192.168.10.2"

cred = BasicCredentials(AK, SK, PROJECT)
client = VpcClient.new_builder().with_credentials(cred).with_region(VpcRegion.value_of(REGION)).build()


def vpc_by_name(name):
    for v in (client.list_vpcs(ListVpcsRequest()).vpcs or []):
        if v.name == name:
            return v
    return None


def wait_vpc(vpc_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st = getattr(client.show_vpc(ShowVpcRequest(vpc_id=vpc_id)), "status", None)
            if st == "OK":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def subnets_of(vpc_id):
    return client.list_subnets(ListSubnetsRequest(vpc_id=vpc_id)).subnets or []


def wait_subnet(vpc_id, subnet_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for s in subnets_of(vpc_id):
            if s.id == subnet_id:
                st = getattr(s, "status", None)
                if st not in ("CREATING",):
                    print(f"   subnet {subnet_id} ready ({st})")
                    return True
        time.sleep(3)
    return False


def get_or_create_vpc(name, cidr):
    v = vpc_by_name(name)
    if v:
        print(f"   reuse VPC {name}: {v.id}")
        return v.id
    r = client.create_vpc(CreateVpcRequest(body=CreateVpcRequestBody(
        vpc=CreateVpcOption(name=name, cidr=cidr, description="test cross-vpc scope"))))
    vid = getattr(r.vpc, "id", None)
    print(f"   created VPC {name}: {vid}")
    wait_vpc(vid)
    return vid


def get_or_create_subnet(name, vpc_id, cidr, gw):
    for s in subnets_of(vpc_id):
        if s.name == name:
            print(f"   reuse Subnet {name}: {s.id}")
            return s.id, getattr(s, "neutron_network_id", None), getattr(s, "neutron_subnet_id", None)
    r = client.create_subnet(CreateSubnetRequest(body=CreateSubnetRequestBody(
        subnet=CreateSubnetOption(name=name, vpc_id=vpc_id, cidr=cidr,
                                  gateway_ip=gw, description="test cross-vpc scope"))))
    s = r.subnet
    print(f"   created Subnet {name}: {s.id}")
    wait_subnet(vpc_id, s.id)
    return s.id, getattr(s, "neutron_network_id", None), getattr(s, "neutron_subnet_id", None)


def get_or_create_peering(name, a_id, b_id):
    for p in (client.list_vpc_peerings(ListVpcPeeringsRequest()).peerings or []):
        if p.name == name:
            print(f"   reuse peering {name}: {p.id}")
            return p.id
    r = client.create_vpc_peering(CreateVpcPeeringRequest(body=CreateVpcPeeringRequestBody(
        peering=CreateVpcPeeringOption(name=name,
                                       request_vpc_info=VpcInfo(vpc_id=a_id),
                                       accept_vpc_info=VpcInfo(vpc_id=b_id)))))
    pid = getattr(r.peering, "id", None)
    print(f"   created peering {name}: {pid}")
    try:
        client.accept_vpc_peering(AcceptVpcPeeringRequest(peering_id=pid))
        print("   peering accepted")
    except exceptions.ClientRequestException as e:
        print(f"   accept note: {e.status_code} {e.error_msg}")
    return pid


def get_or_create_route(vpc_id, dest, nexthop, rtype="peering"):
    for r in (client.list_vpc_routes(ListVpcRoutesRequest(vpc_id=vpc_id)).routes or []):
        if getattr(r, "destination", None) == dest:
            print(f"   reuse route -> {dest}: {r.id}")
            return r.id
    r = client.create_vpc_route(CreateVpcRouteRequest(body=CreateVpcRouteRequestBody(
        route=CreateVpcRouteOption(vpc_id=vpc_id, destination=dest, nexthop=nexthop, type=rtype))))
    rid = getattr(r.route, "id", None)
    print(f"   created route -> {dest}: {rid}")
    return rid


def default_sg_id():
    for sg in (client.list_security_groups(ListSecurityGroupsRequest()).security_groups or []):
        if sg.name in ("default", "Sys-default"):
            return sg.id
    sgs = client.list_security_groups(ListSecurityGroupsRequest()).security_groups or []
    return sgs[0].id if sgs else None


def get_or_create_port(name, net_id, neutron_subnet_id, sg_id, ip):
    for p in (client.list_ports(ListPortsRequest(network_id=net_id)).ports or []):
        if p.name == name:
            print(f"   reuse Port {name}: {p.id}")
            return p.id
    last_err = None
    for attempt in range(6):
        try:
            r = client.create_port(CreatePortRequest(body=CreatePortRequestBody(
                port=CreatePortOption(name=name, network_id=net_id,
                                      fixed_ips=[FixedIp(subnet_id=neutron_subnet_id, ip_address=ip)],
                                      security_groups=[sg_id] if sg_id else None,
                                      admin_state_up=True))))
            pid = getattr(r.port, "id", None)
            print(f"   created Port {name}: {pid}")
            return pid
        except exceptions.ClientRequestException as e:
            last_err = e
            if e.status_code == 404:
                print(f"   port create 404 (subnet not ready), retry {attempt+1}/6")
                time.sleep(8)
                continue
            raise
    raise last_err


def main():
    print("== VPC A", CIDR_A)
    vpc_a = get_or_create_vpc("vpcaa-test-a", CIDR_A)
    print("== VPC B", CIDR_B)
    vpc_b = get_or_create_vpc("vpcaa-test-b", CIDR_B)

    print("== Subnet A")
    sub_a, net_a, neutron_sub_a = get_or_create_subnet("vpcaa-test-subnet-a", vpc_a, SUBNET_A, GW_A)
    print("== Subnet B")
    get_or_create_subnet("vpcaa-test-subnet-b", vpc_b, "192.168.20.0/26", "192.168.20.1")

    print("== default SG")
    sg = default_sg_id()
    print("   SG:", sg)

    print("== Port in Subnet A")
    port = get_or_create_port("vpcaa-test-port-a", net_a, neutron_sub_a, sg, PORT_IP)

    print("== Peering A->B")
    peer = get_or_create_peering("vpcaa-test-peering", vpc_a, vpc_b)

    print("== Route in VPC A ->", CIDR_B)
    get_or_create_route(vpc_a, CIDR_B, peer, rtype="peering")

    print("\n=== RESULT ===")
    print("VPC_A_ID=" + str(vpc_a))
    print("VPC_B_ID=" + str(vpc_b))
    print("SUBNET_A_ID=" + str(sub_a))
    print("PORT_ID=" + str(port))
    print("PEERING_ID=" + str(peer))


if __name__ == "__main__":
    try:
        main()
    except exceptions.ClientRequestException as e:
        print("SDK ERROR", e.status_code, e.error_msg, file=sys.stderr)
        sys.exit(1)
