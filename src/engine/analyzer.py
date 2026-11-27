"""Reachability analyzer — configuration-level VPC path analysis.

Given a :class:`Scope` and the live :class:`Topology`, it decides whether an
*unexpected* network path exists and emits a :class:`Finding` for each one.

Design notes / boundaries:
  * This is a **configuration-level** check: it reasons about route tables,
    security groups and (optionally) network ACLs. It does NOT perform full
    transitive graph reasoning (multi-hop routes, multiple NAT hops,
    VPN/DC specifics). It covers the common cases that the built-in scopes
    exercise: same-VPC, peering, internet egress/ingress.
  * ``exclude.cidrs`` for egress-to-internet means "traffic to that CIDR is
    intentionally routed elsewhere, so do not flag it as internet egress".
  * ``exclude.ports`` removes those destination ports from a matched path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .scope import Scope
from .topology import Topology


@dataclass
class Finding:
    scope_id: str
    direction: str
    source: str
    destination: str
    ports: List[str] = field(default_factory=list)
    detail: str = ""


# --------------------------------------------------------------------------- #
# Port-range maths
# --------------------------------------------------------------------------- #
def _intersect_ranges(open_ranges: List[Tuple[int, int]], match_ports: List[int]) -> List[Tuple[int, int]]:
    if not match_ports:
        return list(open_ranges)
    out: List[Tuple[int, int]] = []
    for p in match_ports:
        for lo, hi in open_ranges:
            if lo <= p <= hi:
                out.append((p, p))
    return out


def _exclude_ranges(ranges: List[Tuple[int, int]], exclude_ports: List[int]) -> List[Tuple[int, int]]:
    if not exclude_ports:
        return list(ranges)
    segments = list(ranges)
    for p in exclude_ports:
        nxt: List[Tuple[int, int]] = []
        for lo, hi in segments:
            if p < lo or p > hi:
                nxt.append((lo, hi))
                continue
            if p - 1 >= lo:
                nxt.append((lo, p - 1))
            if p + 1 <= hi:
                nxt.append((p + 1, hi))
        segments = nxt
    # merge adjacent/overlapping segments
    segments.sort()
    merged: List[Tuple[int, int]] = []
    for lo, hi in segments:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _format_ports(ranges: List[Tuple[int, int]]) -> List[str]:
    out: List[str] = []
    for lo, hi in ranges:
        if lo == 0 and hi == 65535:
            out.append("any")
        elif lo == hi:
            out.append(str(lo))
        else:
            out.append(f"{lo}-{hi}")
    return out or ["none"]


def _filtered_ports(open_ranges, match_ports, exclude_ports) -> List[str]:
    r = _intersect_ranges(open_ranges, match_ports)
    r = _exclude_ranges(r, exclude_ports)
    return _format_ports(r)


# --------------------------------------------------------------------------- #
# Analyzers per direction
# --------------------------------------------------------------------------- #
def _analyze_egress(scope: Scope, topo: Topology) -> List[Finding]:
    findings: List[Finding] = []
    ex = scope.exclude
    for vpc in topo.vpcs():
        vid = vpc.id
        for sub in topo.subnets(vid):
            sid = sub.id
            if not topo.internet_reachable(sid, vid):
                continue
            # exclude.cidrs: a more-specific route to that CIDR means the
            # traffic is intentionally routed elsewhere -> not "internet egress".
            if any(topo.route_to_cidr(sid, vid, c) for c in ex.cidrs):
                continue
            for port in topo.ports(sid, vid):
                open_ranges = topo.egress_open_ranges(port)
                ports = _filtered_ports(open_ranges, scope.match.ports, ex.ports)
                if "none" not in ports:
                    findings.append(
                        Finding(
                            scope_id=scope.scope_id,
                            direction="egress",
                            source=port.id,
                            destination="internet",
                            ports=ports,
                            detail=(
                                f"Port {port.id} in subnet {sid} (vpc {vid}) can egress "
                                f"to the internet on ports {ports}"
                            ),
                        )
                    )
    return findings


def _analyze_ingress(scope: Scope, topo: Topology) -> List[Finding]:
    findings: List[Finding] = []
    ex = scope.exclude
    for vpc in topo.vpcs():
        vid = vpc.id
        for sub in topo.subnets(vid):
            sid = sub.id
            # A subnet is reachable from the internet only if it has an
            # internet route (approximation: EIP/ELB presence not individually
            # verified — conservative, may over-report).
            if not topo.internet_reachable(sid, vid):
                continue
            for port in topo.ports(sid, vid):
                open_ranges = topo.ingress_open_ranges(port)
                ports = _filtered_ports(open_ranges, scope.match.ports, ex.ports)
                if "none" not in ports:
                    findings.append(
                        Finding(
                            scope_id=scope.scope_id,
                            direction="ingress",
                            source="internet",
                            destination=port.id,
                            ports=ports,
                            detail=(
                                f"Port {port.id} in subnet {sid} (vpc {vid}) accepts "
                                f"ingress from the internet on ports {ports}"
                            ),
                        )
                    )
    return findings


def _analyze_cross_vpc(scope: Scope, topo: Topology) -> List[Finding]:
    findings: List[Finding] = []
    ex = scope.exclude
    src_vpc = scope.match.source.value
    dst_vpc = scope.match.destination.value
    if src_vpc in (None, "ALL") or dst_vpc in (None, "ALL"):
        return findings
    for vpc in topo.vpcs():
        if vpc.id != src_vpc:
            continue
        vid = vpc.id
        for sub in topo.subnets(vid):
            sid = sub.id
            if not topo.route_to_vpc(sid, vid, dst_vpc):
                continue
            for port in topo.ports(sid, vid):
                open_ranges = topo.egress_open_ranges(port)
                ports = _filtered_ports(open_ranges, scope.match.ports, ex.ports)
                if "none" not in ports:
                    findings.append(
                        Finding(
                            scope_id=scope.scope_id,
                            direction="cross_vpc",
                            source=f"subnet {sid} (vpc {vid})",
                            destination=f"vpc {dst_vpc}",
                            ports=ports,
                            detail=(
                                f"Subnet {sid} in vpc {vid} has a route toward vpc "
                                f"{dst_vpc}; egress allowed on ports {ports}"
                            ),
                        )
                    )
    return findings


_ANALYZERS = {
    "egress": _analyze_egress,
    "ingress": _analyze_ingress,
    "cross_vpc": _analyze_cross_vpc,
}


def analyze(scope: Scope, topo: Topology) -> List[Finding]:
    fn = _ANALYZERS.get(scope.match.direction)
    if fn is None:
        return []
    return fn(scope, topo)


def analyze_all(scopes: List[Scope], topo: Topology) -> List[Finding]:
    findings: List[Finding] = []
    for scope in scopes:
        findings.extend(analyze(scope, topo))
    return findings
