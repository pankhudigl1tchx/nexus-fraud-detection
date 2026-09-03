"""
engine/graph.py
----------------
The "Living Graph": connects Applicants to shared Infrastructure —
Device, Dealer, Guarantor, and Bank Account nodes.

Structure per application:
    Applicant -- Device
    Applicant -- Dealer
    Applicant -- Guarantor   (if present)
    Applicant -- BankAccount
    + a clique among whichever Infrastructure nodes co-occur on that
      application (Device<->Dealer, Device<->BankAccount, etc.)

The Infrastructure clique is what makes "1-hop" diffusion meaningful in
engine/stigmergy.py: entities that show up together on the same loan
application become directly connected, so heat can spread between them
without ever passing back through an Applicant node.

ZERO-BLEED INVARIANT
---------------------
Applicant nodes are identity/reference nodes ONLY. They must never carry
`raw_heat`, `heat`, `risk`, or `normalized_heat` attributes. All
fraud-signal state lives exclusively on Infrastructure nodes. This is
enforced structurally (Applicant nodes are never touched by diffusion —
see `get_infrastructure_neighbors`) AND defensively at the point of
mutation (`set_node_attrs` raises `ZeroBleedViolation` on any attempt to
write a forbidden key onto an Applicant node).

NOTE: This is an in-memory NetworkX graph. In production this should be
backed by a persistent graph store (e.g. Neo4j, TigerGraph) or a
periodically-rehydrated NetworkX snapshot loaded from a feature store.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import networkx as nx

logger = logging.getLogger("nexus.engine.graph")


class NodeType(str, Enum):
    APPLICANT = "applicant"
    DEVICE = "device"
    DEALER = "dealer"
    GUARANTOR = "guarantor"
    BANK_ACCOUNT = "bank_account"


INFRASTRUCTURE_TYPES: Set[NodeType] = {
    NodeType.DEVICE,
    NodeType.DEALER,
    NodeType.GUARANTOR,
    NodeType.BANK_ACCOUNT,
}
_INFRASTRUCTURE_TYPE_VALUES: Set[str] = {t.value for t in INFRASTRUCTURE_TYPES}

# Attributes that must never appear on an Applicant node.
FORBIDDEN_APPLICANT_ATTRS: Set[str] = {"raw_heat", "heat", "risk", "normalized_heat"}


class ZeroBleedViolation(RuntimeError):
    """Raised when an operation would place heat/risk data onto an Applicant node."""


class EntityGraph:
    """The Living Graph: Applicants <-> Infrastructure, with an Infrastructure clique per application."""

    def __init__(self) -> None:
        self._graph = nx.Graph()

    @property
    def graph(self) -> nx.Graph:
        return self._graph

    @staticmethod
    def node_id(node_type: NodeType, value: str) -> str:
        return f"{node_type.value}::{value}"

    def _assert_zero_bleed(self, node_id: str, attrs: Dict[str, Any]) -> None:
        node_data = self._graph.nodes.get(node_id)
        if node_data is not None and node_data.get("type") == NodeType.APPLICANT.value:
            violating = FORBIDDEN_APPLICANT_ATTRS.intersection(attrs.keys())
            if violating:
                raise ZeroBleedViolation(
                    f"Refusing to set {sorted(violating)} on Applicant node '{node_id}': "
                    "Applicant nodes must never carry heat/risk attributes."
                )

    def add_applicant(self, applicant_id: str) -> str:
        node_id = self.node_id(NodeType.APPLICANT, applicant_id)
        if node_id not in self._graph:
            self._graph.add_node(node_id, type=NodeType.APPLICANT.value, applicant_id=applicant_id)
        return node_id

    def add_infrastructure_node(self, node_type: NodeType, value: str, **extra_attrs: Any) -> str:
        if node_type not in INFRASTRUCTURE_TYPES:
            raise ValueError(f"{node_type} is not an Infrastructure node type")
        node_id = self.node_id(node_type, value)
        if node_id not in self._graph:
            self._graph.add_node(
                node_id,
                type=node_type.value,
                value=value,
                raw_heat=0.0,
                heat=0.0,
            )
        for key, val in extra_attrs.items():
            if val is not None:
                self._graph.nodes[node_id][key] = val
        return node_id

    def set_node_attrs(self, node_id: str, **attrs: Any) -> None:
        """Guarded attribute setter. Enforces the zero-bleed invariant on every write."""
        if node_id not in self._graph:
            raise KeyError(f"Unknown node: {node_id}")
        self._assert_zero_bleed(node_id, attrs)
        self._graph.nodes[node_id].update(attrs)

    def upsert_application(
        self,
        application_id: str,
        applicant_id: str,
        device_hash: str,
        dealer_id: str,
        guarantor_id: Optional[str],
        bank_hash: str,
        dealer_30d_volume: Optional[int] = None,
    ) -> Dict[str, Optional[str]]:
        """
        Wire one application into the Living Graph: Applicant<->Infrastructure
        edges, plus an Infrastructure<->Infrastructure clique for whichever
        entities co-occur on this application.
        """
        applicant_node = self.add_applicant(applicant_id)

        device_node = self.add_infrastructure_node(NodeType.DEVICE, device_hash)
        dealer_node = self.add_infrastructure_node(
            NodeType.DEALER, dealer_id, dealer_30d_volume=dealer_30d_volume
        )
        bank_node = self.add_infrastructure_node(NodeType.BANK_ACCOUNT, bank_hash)
        guarantor_node = (
            self.add_infrastructure_node(NodeType.GUARANTOR, guarantor_id) if guarantor_id else None
        )

        infra_nodes = [n for n in (device_node, dealer_node, guarantor_node, bank_node) if n is not None]

        for infra_node in infra_nodes:
            self._graph.add_edge(
                applicant_node, infra_node, relation="applied_with", application_id=application_id
            )

        for i in range(len(infra_nodes)):
            for j in range(i + 1, len(infra_nodes)):
                self._graph.add_edge(
                    infra_nodes[i], infra_nodes[j], relation="co_occurred", application_id=application_id
                )

        logger.debug("Upserted application %s into Living Graph", application_id)
        return {
            "applicant": applicant_node,
            "device": device_node,
            "dealer": dealer_node,
            "guarantor": guarantor_node,
            "bank_account": bank_node,
        }

    def get_infrastructure_neighbors(self, node_id: str) -> List[str]:
        """1-hop neighbors of `node_id`, restricted to Infrastructure node types. Never returns Applicant nodes."""
        if node_id not in self._graph:
            return []
        return [
            neighbor
            for neighbor in self._graph.neighbors(node_id)
            if self._graph.nodes[neighbor].get("type") in _INFRASTRUCTURE_TYPE_VALUES
        ]

    def get_applicant_infrastructure(self, applicant_id: str) -> List[str]:
        """All Infrastructure nodes directly linked to a given applicant."""
        return self.get_infrastructure_neighbors(self.node_id(NodeType.APPLICANT, applicant_id))

    def get_neighborhood(self, applicant_id: str, depth: int = 2) -> Dict[str, Any]:
        """
        Ego-graph around an applicant, shaped for the React frontend's
        graph visualization (nodes/edges). Applicant nodes never expose a
        `heat` field in this payload; Infrastructure nodes do.
        """
        node_id = self.node_id(NodeType.APPLICANT, applicant_id)
        if node_id not in self._graph:
            return {
                "applicant_id": applicant_id,
                "nodes": [],
                "edges": [],
                "shared_entity_count": 0,
                "ring_score": 0.0,
            }

        ego = nx.ego_graph(self._graph, node_id, radius=depth)

        nodes_payload = []
        for n, data in ego.nodes(data=True):
            if data.get("type") == NodeType.APPLICANT.value:
                nodes_payload.append({"id": n, "type": data.get("type"), "label": data.get("applicant_id")})
            else:
                nodes_payload.append(
                    {
                        "id": n,
                        "type": data.get("type"),
                        "label": data.get("value"),
                        "heat": round(data.get("heat", 0.0), 4),
                    }
                )

        edges_payload = [
            {"source": u, "target": v, "relation": d.get("relation")} for u, v, d in ego.edges(data=True)
        ]

        infra_neighbors = self.get_infrastructure_neighbors(node_id)
        # An infra node is "shared" if it has degree > 1, i.e. it touches
        # more than just this one applicant.
        shared_entity_count = sum(1 for infra in infra_neighbors if self._graph.degree[infra] > 1)
        ring_score = min(1.0, shared_entity_count / 8.0) if infra_neighbors else 0.0

        return {
            "applicant_id": applicant_id,
            "nodes": nodes_payload,
            "edges": edges_payload,
            "shared_entity_count": shared_entity_count,
            "ring_score": round(ring_score, 4),
        }

    def find_shared_entity_rings(self, min_shared: int = 2) -> List[Dict[str, Any]]:
        """Infrastructure nodes touched by >= min_shared distinct applicants — candidate fraud rings."""
        rings = []
        for node, data in self._graph.nodes(data=True):
            if data.get("type") in _INFRASTRUCTURE_TYPE_VALUES:
                applicant_neighbors = [
                    n
                    for n in self._graph.neighbors(node)
                    if self._graph.nodes[n].get("type") == NodeType.APPLICANT.value
                ]
                if len(applicant_neighbors) >= min_shared:
                    rings.append(
                        {
                            "entity": node,
                            "applicant_count": len(applicant_neighbors),
                            "applicants": applicant_neighbors,
                        }
                    )
        return rings


# Module-level singleton used by the API layer. In production this should
# be dependency-injected and backed by a real persistence layer.
entity_graph = EntityGraph()


# ---------------------------------------------------------------------------
# Unit tests — run with `pytest engine/graph.py -v` or `python engine/graph.py`
# ---------------------------------------------------------------------------

def _build_sample_graph() -> EntityGraph:
    g = EntityGraph()
    g.upsert_application(
        application_id="APP-1",
        applicant_id="A1",
        device_hash="DEV-1",
        dealer_id="DEALER-1",
        guarantor_id="GUAR-1",
        bank_hash="BANK-1",
        dealer_30d_volume=40,
    )
    return g


def test_applicant_node_has_no_heat_attrs_on_creation():
    g = _build_sample_graph()
    applicant_node = g.node_id(NodeType.APPLICANT, "A1")
    data = g.graph.nodes[applicant_node]
    assert FORBIDDEN_APPLICANT_ATTRS.isdisjoint(data.keys()), (
        f"Applicant node acquired forbidden attrs: {FORBIDDEN_APPLICANT_ATTRS.intersection(data.keys())}"
    )


def test_infrastructure_nodes_form_a_clique_per_application():
    g = _build_sample_graph()
    device_node = g.node_id(NodeType.DEVICE, "DEV-1")
    dealer_node = g.node_id(NodeType.DEALER, "DEALER-1")
    guarantor_node = g.node_id(NodeType.GUARANTOR, "GUAR-1")
    bank_node = g.node_id(NodeType.BANK_ACCOUNT, "BANK-1")

    device_neighbors = set(g.get_infrastructure_neighbors(device_node))
    assert {dealer_node, guarantor_node, bank_node}.issubset(device_neighbors)


def test_get_infrastructure_neighbors_excludes_applicant_nodes():
    g = _build_sample_graph()
    device_node = g.node_id(NodeType.DEVICE, "DEV-1")
    applicant_node = g.node_id(NodeType.APPLICANT, "A1")

    # Applicant IS a direct graph neighbor of Device...
    assert applicant_node in g.graph.neighbors(device_node)
    # ...but must never appear in the *infrastructure*-filtered neighbor list.
    assert applicant_node not in g.get_infrastructure_neighbors(device_node)


def test_set_node_attrs_blocks_heat_on_applicant():
    g = _build_sample_graph()
    applicant_node = g.node_id(NodeType.APPLICANT, "A1")
    try:
        g.set_node_attrs(applicant_node, raw_heat=5.0)
        raised = False
    except ZeroBleedViolation:
        raised = True
    assert raised, "Expected ZeroBleedViolation when writing raw_heat onto an Applicant node"


def test_set_node_attrs_allows_heat_on_infrastructure():
    g = _build_sample_graph()
    device_node = g.node_id(NodeType.DEVICE, "DEV-1")
    g.set_node_attrs(device_node, raw_heat=2.5, heat=1.1)
    assert g.graph.nodes[device_node]["raw_heat"] == 2.5
    assert g.graph.nodes[device_node]["heat"] == 1.1


def test_diffusion_never_writes_heat_onto_applicant_nodes():
    """
    End-to-end check: after a full deposit + diffusion + normalization pass
    via engine.stigmergy, no Applicant node in the graph has gained a
    heat-related attribute.
    """
    # Local import to avoid a module-level circular dependency: engine.stigmergy
    # imports from engine.graph, not the other way around.
    from engine.stigmergy import StigmergyEngine

    g = _build_sample_graph()
    stigmergy = StigmergyEngine(g)
    stigmergy.process_application_event(
        applicant_id="A1",
        device_hash="DEV-1",
        dealer_id="DEALER-1",
        guarantor_id="GUAR-1",
        bank_hash="BANK-1",
        is_suspicious_event=True,
    )

    for node, data in g.graph.nodes(data=True):
        if data.get("type") == NodeType.APPLICANT.value:
            assert FORBIDDEN_APPLICANT_ATTRS.isdisjoint(data.keys()), (
                f"Zero-bleed invariant violated: {node} acquired "
                f"{FORBIDDEN_APPLICANT_ATTRS.intersection(data.keys())}"
            )
        elif data.get("type") in _INFRASTRUCTURE_TYPE_VALUES:
            assert "raw_heat" in data and "heat" in data


def test_diffusion_only_reaches_1hop_infrastructure_neighbors():
    from engine.stigmergy import StigmergyEngine

    g = _build_sample_graph()
    stigmergy = StigmergyEngine(g)
    stigmergy.process_application_event(
        applicant_id="A1",
        device_hash="DEV-1",
        dealer_id="DEALER-1",
        guarantor_id="GUAR-1",
        bank_hash="BANK-1",
        is_suspicious_event=True,
    )

    dealer_node = g.node_id(NodeType.DEALER, "DEALER-1")
    guarantor_node = g.node_id(NodeType.GUARANTOR, "GUAR-1")
    bank_node = g.node_id(NodeType.BANK_ACCOUNT, "BANK-1")

    assert g.graph.nodes[dealer_node]["raw_heat"] > 0.0
    assert g.graph.nodes[guarantor_node]["raw_heat"] > 0.0
    assert g.graph.nodes[bank_node]["raw_heat"] > 0.0


if __name__ == "__main__":
    # Allow `python engine/graph.py` to be run directly (not just via pytest)
    # by ensuring the project root is on sys.path so `engine.stigmergy` resolves.
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    _test_fns = [obj for name, obj in list(globals().items()) if name.startswith("test_") and callable(obj)]
    _passed = 0
    for _fn in _test_fns:
        _fn()
        _passed += 1
        print(f"PASSED: {_fn.__name__}")
    print(f"\n{_passed}/{len(_test_fns)} tests passed.")
