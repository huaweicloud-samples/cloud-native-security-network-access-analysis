"""Network Access Scope model.

A scope declares what network paths are expected to be **absent**; any actual
path that matches the configured rule but is NOT excluded becomes a finding.

This dataclass is the contract the analyzer (``analyzer.py``) consumes. It uses
a simple configuration-level schema: ``match`` (direction / source /
destination / ports) and ``exclude`` (cidrs / ports).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Endpoint:
    """One side of a path.

    type:
      - ``internet`` : the public internet (via IGW / NAT / EIP)
      - ``vpc``      : every resource inside a VPC (``value`` = vpc id, or ``ALL``)
      - ``subnet``   : a specific subnet (``value`` = subnet id)
      - ``instance`` : compute ENIs / ports (``value`` = vpc id, or ``ALL``)
      - ``cidr``     : an explicit CIDR (``value`` = CIDR string)
    """

    type: str
    value: Optional[str] = None


@dataclass
class Match:
    direction: str  # "egress" | "ingress" | "cross_vpc"
    source: Endpoint
    destination: Endpoint
    ports: List[int] = field(default_factory=list)  # restrict to these dest ports (empty = any)


@dataclass
class Exclude:
    cidrs: List[str] = field(default_factory=list)  # destination CIDRs to ignore
    ports: List[int] = field(default_factory=list)  # destination ports to ignore


@dataclass
class Scope:
    scope_id: str
    description: str
    match: Match
    exclude: Exclude = field(default_factory=Exclude)

    @classmethod
    def from_dict(cls, d: dict) -> "Scope":
        m = d["match"]
        src = m["source"]
        dst = m["destination"]
        match = Match(
            direction=m["direction"],
            source=Endpoint(type=src["type"], value=src.get("value")),
            destination=Endpoint(type=dst["type"], value=dst.get("value")),
            ports=[int(p) for p in m.get("ports", [])],
        )
        ex = d.get("exclude", {}) or {}
        exclude = Exclude(
            cidrs=ex.get("cidrs", []) or [],
            ports=[int(p) for p in ex.get("ports", []) or []],
        )
        return cls(
            scope_id=d.get("scope_id", d.get("name", "unnamed")),
            description=d.get("description", ""),
            match=match,
            exclude=exclude,
        )


def load_scopes(directory: str) -> List[Scope]:
    """Load every ``*.json`` scope file in ``directory``."""
    scopes: List[Scope] = []
    if not os.path.isdir(directory):
        return scopes
    # Let deployment-specific VPC IDs be injected via env so the committed scope
    # templates can keep REPLACE_VPC_A_ID / REPLACE_VPC_B_ID placeholders (no
    # account-specific values committed). Unset env -> placeholder unchanged.
    tok = {
        "REPLACE_VPC_A_ID": os.environ.get("VPCA_ID") or "REPLACE_VPC_A_ID",
        "REPLACE_VPC_B_ID": os.environ.get("VPCB_ID") or "REPLACE_VPC_B_ID",
    }
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for placeholder, value in tok.items():
            if placeholder in text:
                text = text.replace(placeholder, value)
        data = json.loads(text)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "scopes" in data:
            items = data["scopes"]
        else:
            items = [data]
        for item in items:
            scopes.append(Scope.from_dict(item))
    return scopes
