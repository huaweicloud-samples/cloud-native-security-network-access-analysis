"""Huawei Cloud VPC topology reader.

Fetches the configuration needed to reason about reachability: VPCs, subnets,
route tables (+ routes), security groups (+ rules) and ports (ENIs).
Results are cached per object so the analyzer can query them cheaply.

It is a **configuration-level** reader only — it does NOT perform live traffic
capture.

SDK usage notes (important):
  * Route tables, subnets, security groups, ports and routes all live in the
    **v2** VPC SDK. The v3 SDK dropped them, so importing them from v3 raises
    ``ImportError`` and breaks the whole engine.
  * ``RouteTableListResp`` only carries the subnet *associations* — it has NO
    ``routes`` field. The actual routes are a separate API, ``list_vpc_routes``
    (``ListVpcRoutesRequest`` -> ``routes: list[VpcRoute]``), where each
    ``VpcRoute`` has ``destination`` + ``nexthop`` (no ``type``). We derive a
    ``type`` (``egress`` / ``static``) from the destination so the analyzer's
    reachability primitives keep working.
  * Huawei Cloud has no separate "network ACL" concept (security groups cover
    both directions), so ``network_acls`` always returns an empty list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from huaweicloudsdkvpc.v2 import (  # noqa: F401  (v2 carries all list APIs)
    ListPortsRequest,
    ListRouteTablesRequest,
    ListSecurityGroupRulesRequest,
    ListSecurityGroupsRequest,
    ListSubnetsRequest,
    ListVpcsRequest,
    ListVpcRoutesRequest,
    VpcClient,
)


@dataclass
class _RouteView:
    """Normalised route the analyzer's predicates can reason about."""

    destination: str
    type: str  # "egress" (internet) | "static" (peering/vpc/vpn/other)
    nexthop: Optional[str] = None


class Topology:
    def __init__(self, client: VpcClient):
        self.client = client
        self._vpcs: Optional[List] = None
        self._subnets: Dict[str, List] = {}
        self._route_tables: Dict[str, List] = {}
        self._routes: Dict[str, List[_RouteView]] = {}
        self._security_groups: Dict[str, List] = {}
        self._ports: Dict[str, List] = {}
        self._acls: Dict[str, List] = {}

    # ------------------------------------------------------------------ #
    # Generic paginated list helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def _list_all(req_fn: Callable, call_fn: Callable, extract_fn: Callable, limit: int = 1000):
        items: List = []
        marker = None
        while True:
            req = req_fn()
            if marker:
                try:
                    req.marker = marker
                except Exception:
                    pass
            try:
                resp = call_fn(req)
            except Exception:
                break
            batch = extract_fn(resp) or []
            items.extend(batch)
            if len(batch) < limit:
                break
            nxt = getattr(resp, "page_info", None)
            marker = getattr(nxt, "next_marker", None) if nxt else None
            if not marker:
                break
        return items

    # ------------------------------------------------------------------ #
    # Fetchers (lazy + cached)
    # ------------------------------------------------------------------ #
    def vpcs(self) -> List:
        if self._vpcs is None:
            self._vpcs = self._list_all(
                lambda: ListVpcsRequest(),
                self.client.list_vpcs,
                lambda r: getattr(r, "vpcs", None),
            )
        return self._vpcs

    def subnets(self, vpc_id: str) -> List:
        if vpc_id not in self._subnets:
            self._subnets[vpc_id] = self._list_all(
                lambda: ListSubnetsRequest(vpc_id=vpc_id),
                self.client.list_subnets,
                lambda r: getattr(r, "subnets", None),
            )
        return self._subnets[vpc_id]

    def route_tables(self, vpc_id: str) -> List:
        if vpc_id not in self._route_tables:
            self._route_tables[vpc_id] = self._list_all(
                lambda: ListRouteTablesRequest(vpc_id=vpc_id),
                self.client.list_route_tables,
                lambda r: getattr(r, "route_tables", None),
            )
        return self._route_tables[vpc_id]

    def routes(self, vpc_id: str) -> List[_RouteView]:
        """Real route entries for the VPC (the source of truth for reachability).

        ``RouteTableListResp`` has no ``routes`` field, so we use ``list_vpc_routes``.
        Each ``VpcRoute`` only exposes ``destination`` + ``nexthop``; we synthesise
        a ``type`` so the analyzer's predicates (which expect a ``type``) keep working.
        """
        if vpc_id not in self._routes:
            raw = self._list_all(
                lambda: ListVpcRoutesRequest(vpc_id=vpc_id),
                self.client.list_vpc_routes,
                lambda r: getattr(r, "routes", None),
            )
            out: List[_RouteView] = []
            for rv in raw:
                dest = getattr(rv, "destination", None)
                nexthop = getattr(rv, "nexthop", None)
                if dest in ("0.0.0.0/0", "::/0"):
                    rtype = "egress"
                else:
                    rtype = "static"
                out.append(_RouteView(destination=dest, type=rtype, nexthop=nexthop))
            self._routes[vpc_id] = out
        return self._routes[vpc_id]

    def security_groups(self, vpc_id: str) -> List:
        if vpc_id not in self._security_groups:
            sgs = self._list_all(
                lambda: ListSecurityGroupsRequest(vpc_id=vpc_id),
                self.client.list_security_groups,
                lambda r: getattr(r, "security_groups", None),
            )
            for sg in sgs:
                try:
                    resp = self.client.list_security_group_rules(
                        ListSecurityGroupRulesRequest(security_group_id=sg.id)
                    )
                    sg.rules = getattr(resp, "security_group_rules", None) or []
                except Exception:
                    sg.rules = []
            self._security_groups[vpc_id] = sgs
        return self._security_groups[vpc_id]

    def ports(self, subnet_id: str, vpc_id: str = None) -> List:
        if subnet_id not in self._ports:
            # Huawei's ListPortsRequest has NO subnet_id filter. Ports belong to a
            # *network* (one per VPC) and reference the subnet via fixed_ips[].subnet_id.
            # Resolve the subnet's neutron_network_id, list ports on that network,
            # then keep only the ports actually attached to this subnet.
            #
            # Match caveat (Huawei Cloud reality): a VPC subnet exposes TWO ids —
            # ``id`` (used by the VPC API) and ``neutron_subnet_id`` (used by the
            # neutron/port API). A real ENI's ``fixed_ips[].subnet_id`` carries the
            # *neutron* id, which differs from the VPC ``id``. So we accept a port
            # whose ``subnet_id`` equals EITHER, otherwise the analyzer would never
            # see any real port and every scope would silently yield 0 findings.
            network_id = None
            match_subnet_ids = {subnet_id}
            if vpc_id:
                for sub in self.subnets(vpc_id):
                    if getattr(sub, "id", None) == subnet_id:
                        network_id = getattr(sub, "neutron_network_id", None)
                        nid = getattr(sub, "neutron_subnet_id", None)
                        if nid:
                            match_subnet_ids.add(nid)
                        break
            raw = self._list_all(
                lambda: ListPortsRequest(network_id=network_id)
                if network_id
                else ListPortsRequest(),
                self.client.list_ports,
                lambda r: getattr(r, "ports", None),
            )
            out: List = []
            for p in raw:
                fips = getattr(p, "fixed_ips", None) or []
                if any(getattr(fip, "subnet_id", None) in match_subnet_ids for fip in fips):
                    out.append(p)
            self._ports[subnet_id] = out
        return self._ports[subnet_id]

    def network_acls(self, vpc_id: str) -> List:
        # Huawei Cloud has no standalone network ACL service; security groups
        # cover both ingress and egress. Always empty.
        return []

    # ------------------------------------------------------------------ #
    # Index helpers
    # ------------------------------------------------------------------ #
    def _find_sg(self, sg_id: str):
        for sgs in self._security_groups.values():
            for sg in sgs:
                if sg.id == sg_id:
                    return sg
        # The account-default security group has vpc_id="default" (a sentinel, not
        # a real VPC id), so it is NOT returned when we query SGs per-VPC. Fall
        # back to an account-wide fetch so rules attached to that SG are可见.
        if "___account_wide___" not in self._security_groups:
            try:
                all_sgs = self._list_all(
                    lambda: ListSecurityGroupsRequest(),
                    self.client.list_security_groups,
                    lambda r: getattr(r, "security_groups", None),
                )
                for sg in all_sgs:
                    try:
                        resp = self.client.list_security_group_rules(
                            ListSecurityGroupRulesRequest(security_group_id=sg.id)
                        )
                        sg.rules = getattr(resp, "security_group_rules", None) or []
                    except Exception:
                        sg.rules = []
                self._security_groups["___account_wide___"] = all_sgs
            except Exception:
                self._security_groups["___account_wide___"] = []
        for sg in self._security_groups["___account_wide___"]:
            if sg.id == sg_id:
                return sg
        return None

    def route_table_of_subnet(self, subnet_id: str, vpc_id: str):
        for rt in self.route_tables(vpc_id):
            assoc = getattr(rt, "subnets", None) or []
            ids = [getattr(s, "id", s) for s in assoc]
            if subnet_id in ids:
                return rt
        rts = self.route_tables(vpc_id)
        return rts[0] if rts else None

    # ------------------------------------------------------------------ #
    # Reachability primitives (configuration-level, see degradation notes)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _route_matches(routes: List[_RouteView], predicate: Callable[[_RouteView], bool]) -> bool:
        for r in routes or []:
            if predicate(r):
                return True
        return False

    def internet_reachable(self, subnet_id: str, vpc_id: str) -> bool:
        """True if the VPC has a default route (0.0.0.0/0) toward the internet.

        Huawei Cloud models this as a route whose destination is 0.0.0.0/0; we
        synthesise ``type="egress"`` for it (see :meth:`routes`). EIP-bound
        instances also egress via the IGW; we treat any 0.0.0.0/0 internet route
        as "internet reachable".
        """
        routes = self.routes(vpc_id)

        def pred(r: _RouteView) -> bool:
            return r.destination in ("0.0.0.0/0", "::/0") and r.type in ("egress", "nat", "igw", None)

        return self._route_matches(routes, pred)

    def route_to_cidr(self, subnet_id: str, vpc_id: str, cidr: str) -> bool:
        routes = self.routes(vpc_id)

        def pred(r: _RouteView) -> bool:
            return r.destination == cidr

        return self._route_matches(routes, pred)

    def route_to_vpc(self, subnet_id: str, vpc_id: str, target_vpc_id: str) -> bool:
        """Same VPC, or a non-internet route that can reach ``target_vpc_id``."""
        if vpc_id == target_vpc_id:
            return True
        routes = self.routes(vpc_id)

        def pred(r: _RouteView) -> bool:
            return r.type in ("peering", "vpc", "vpn", "static") and r.destination not in (
                "0.0.0.0/0",
                "::/0",
            )

        return self._route_matches(routes, pred)

    # ------------------------------------------------------------------ #
    # Security-group / port helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _port_ranges_overlap(pmin, pmax, port: Optional[int]) -> bool:
        if port is None:
            return True
        lo = pmin if pmin is not None else 1
        hi = pmax if pmax is not None else (pmin if pmin is not None else 65535)
        return lo <= port <= hi

    def ingress_open_ranges(self, port, from_cidr: str = "0.0.0.0/0") -> List[tuple]:
        """Return (port_min, port_max) tuples allowed for INGRESS from ``from_cidr``."""
        out: List[tuple] = []
        for sg_id in getattr(port, "security_groups", None) or []:
            sg = self._find_sg(sg_id)
            if not sg:
                continue
            for rule in getattr(sg, "rules", None) or []:
                if getattr(rule, "direction", None) != "ingress":
                    continue
                if getattr(rule, "action", "allow") != "allow":
                    continue
                rip = getattr(rule, "remote_ip_prefix", None)
                rg = getattr(rule, "remote_group_id", None)
                # Huawei models "allow from anywhere" as remote_ip_prefix=None AND
                # remote_group_id=None (no restriction at all). Treat that as matching
                # any requested CIDR instead of skipping it.
                if rip is not None and rg is None and rip not in (from_cidr, "::/0"):
                    continue
                pmin = getattr(rule, "port_range_min", None)
                pmax = getattr(rule, "port_range_max", None)
                if pmin is None and pmax is None:
                    out.append((0, 65535))
                else:
                    out.append((pmin or 1, pmax or pmin or 1))
        return out

    def egress_open_ranges(self, port, to_cidr: str = "0.0.0.0/0") -> List[tuple]:
        """Return (port_min, port_max) tuples allowed for EGRESS to ``to_cidr``."""
        out: List[tuple] = []
        for sg_id in getattr(port, "security_groups", None) or []:
            sg = self._find_sg(sg_id)
            if not sg:
                continue
            for rule in getattr(sg, "rules", None) or []:
                if getattr(rule, "direction", None) != "egress":
                    continue
                if getattr(rule, "action", "allow") != "allow":
                    continue
                rip = getattr(rule, "remote_ip_prefix", None)
                rg = getattr(rule, "remote_group_id", None)
                # Huawei models "allow to anywhere" as remote_ip_prefix=None AND
                # remote_group_id=None (no restriction at all). Treat that as matching
                # any requested CIDR instead of skipping it.
                if rip is not None and rg is None and rip not in (to_cidr, "::/0"):
                    continue
                pmin = getattr(rule, "port_range_min", None)
                pmax = getattr(rule, "port_range_max", None)
                if pmin is None and pmax is None:
                    out.append((0, 65535))
                else:
                    out.append((pmin or 1, pmax or pmin or 1))
        return out
