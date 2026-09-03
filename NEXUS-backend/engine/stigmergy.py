"""
engine/stigmergy.py
---------------------
Stigmergic signal layer operating directly on the Living Graph's
Infrastructure nodes (Device / Dealer / Guarantor / Bank Account).

Pipeline for one application "touch":
    1. Temporal decay   — existing raw_heat on a node decays exponentially
                           with time since it was last updated.
    2. Risk deposit      — a fresh raw_heat trace is deposited on the
                           Device node associated with the application.
    3. Constrained diffusion — a fraction of that heat spreads outward to
                           1-hop Infrastructure neighbors ONLY (never to
                           Applicant nodes).
    4. Volume normalization — heat is divided down by a function of the
                           dealer's 30-day volume, so high-volume dealers
                           aren't penalized for scale alone.

ZERO-BLEED INVARIANT: this module must never write heat/risk attributes
onto Applicant nodes. Every mutation goes through
`EntityGraph.set_node_attrs`, which enforces that at the graph layer
(see engine/graph.py). Diffusion additionally only ever targets
`EntityGraph.get_infrastructure_neighbors`, which is structurally
incapable of returning an Applicant node.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Dict, Optional

from engine.graph import EntityGraph, NodeType, entity_graph

logger = logging.getLogger("nexus.engine.stigmergy")

# --- Tunable constants ------------------------------------------------------

LAMBDA_DECAY = 0.18      # Exponential decay rate (per hour) applied to node heat.
ALPHA_DIFFUSION = 0.20   # Fraction of a node's heat diffused to 1-hop infra neighbors.


class StigmergyEngine:
    """Temporal decay, risk-trace deposit, constrained diffusion, and volume normalization over a Living Graph."""

    def __init__(
        self,
        graph: EntityGraph,
        lambda_decay: float = LAMBDA_DECAY,
        alpha: float = ALPHA_DIFFUSION,
    ) -> None:
        self._graph = graph
        self._lambda = lambda_decay
        self._alpha = alpha

    # ------------------------------------------------------------------
    # 1. Temporal decay
    # ------------------------------------------------------------------
    def apply_temporal_decay(self, node_id: str) -> float:
        """
        Decay a node's raw_heat since it was last touched:

            heat = raw_heat * exp(-lambda * delta_hours)

        Only ever called on Infrastructure nodes in practice; if it were
        ever pointed at an Applicant node, `set_node_attrs` would reject
        the write (Applicant nodes never carry `raw_heat` to decay).
        """
        graph = self._graph.graph
        if node_id not in graph:
            return 0.0

        data = graph.nodes[node_id]
        now = time.time()
        last_updated = data.get("last_updated", now)
        delta_hours = max(0.0, (now - last_updated) / 3600.0)

        current_heat = data.get("raw_heat", 0.0)
        decayed_heat = current_heat * math.exp(-self._lambda * delta_hours)

        self._graph.set_node_attrs(node_id, raw_heat=decayed_heat, last_updated=now)
        return decayed_heat

    # ------------------------------------------------------------------
    # 2. Risk trace deposit
    # ------------------------------------------------------------------
    def deposit_risk_trace(self, device_node_id: str, is_suspicious_event: bool) -> float:
        """
        Deposit a risk trace on the Device node tied to an application:

            raw_heat += 1.0   if is_suspicious_event
            raw_heat += 0.5   otherwise

        Existing heat is decayed first so the deposit reflects
        elapsed-time-adjusted intensity rather than stale accumulation.
        """
        decayed_heat = self.apply_temporal_decay(device_node_id)
        deposit_amount = 1.0 if is_suspicious_event else 0.5
        new_heat = decayed_heat + deposit_amount

        self._graph.set_node_attrs(device_node_id, raw_heat=new_heat, last_updated=time.time())
        logger.debug(
            "Deposited risk trace on %s (suspicious=%s) -> raw_heat=%.4f",
            device_node_id, is_suspicious_event, new_heat,
        )
        return new_heat

    # ------------------------------------------------------------------
    # 3. Constrained diffusion
    # ------------------------------------------------------------------
    def diffuse_heat(self, source_node_id: str) -> Dict[str, float]:
        """
        Spread `alpha` fraction of the source node's raw_heat evenly across
        its 1-hop Infrastructure neighbors ONLY.

        Applicant nodes are structurally excluded via
        `EntityGraph.get_infrastructure_neighbors` (line 1 of defense), and
        `set_node_attrs`'s zero-bleed guard would reject a write to one
        even if it somehow appeared in the neighbor list (line 2).
        """
        graph = self._graph.graph
        if source_node_id not in graph:
            return {}

        source_heat = graph.nodes[source_node_id].get("raw_heat", 0.0)
        diffusion_pool = source_heat * self._alpha

        neighbors = self._graph.get_infrastructure_neighbors(source_node_id)
        if not neighbors or diffusion_pool <= 0.0:
            return {}

        share_per_neighbor = diffusion_pool / len(neighbors)
        diffused: Dict[str, float] = {}

        for neighbor_id in neighbors:
            decayed_neighbor_heat = self.apply_temporal_decay(neighbor_id)
            updated_heat = decayed_neighbor_heat + share_per_neighbor
            self._graph.set_node_attrs(neighbor_id, raw_heat=updated_heat, last_updated=time.time())
            diffused[neighbor_id] = updated_heat
            logger.debug("Diffused %.4f heat: %s -> %s", share_per_neighbor, source_node_id, neighbor_id)

        return diffused

    # ------------------------------------------------------------------
    # 4. Volume normalization
    # ------------------------------------------------------------------
    def normalize_by_volume(self, node_id: str, dealer_30d_volume: Optional[int]) -> float:
        """
        Normalize an Infrastructure node's raw_heat against dealer volume:

            heat = raw_heat / log2(2 + dealer_30d_volume)
        """
        graph = self._graph.graph
        if node_id not in graph:
            return 0.0

        raw_heat = graph.nodes[node_id].get("raw_heat", 0.0)
        volume = dealer_30d_volume if dealer_30d_volume is not None else 0
        normalized_heat = raw_heat / math.log2(2 + volume)

        self._graph.set_node_attrs(node_id, heat=normalized_heat)
        return normalized_heat

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def process_application_event(
        self,
        applicant_id: str,
        device_hash: str,
        dealer_id: str,
        guarantor_id: Optional[str],
        bank_hash: str,
        is_suspicious_event: bool,
    ) -> Dict[str, float]:
        """
        Full stigmergic pass for one application touch: deposit -> diffuse
        -> normalize. Requires `EntityGraph.upsert_application` to have
        already been called for this application, so the Device/Dealer/
        Guarantor/Bank nodes and their edges already exist.

        Returns the normalized `heat` for every node touched (device +
        whichever 1-hop infra neighbors received diffused heat).
        """
        graph = self._graph.graph
        device_node = self._graph.node_id(NodeType.DEVICE, device_hash)
        dealer_node = self._graph.node_id(NodeType.DEALER, dealer_id)

        if device_node not in graph:
            logger.warning(
                "Device node %s not found — call upsert_application before "
                "process_application_event.", device_node,
            )
            return {}

        dealer_30d_volume = graph.nodes[dealer_node].get("dealer_30d_volume", 0) if dealer_node in graph else 0

        self.deposit_risk_trace(device_node, is_suspicious_event)
        diffused_nodes = self.diffuse_heat(device_node)

        normalized: Dict[str, float] = {}
        for node_id in [device_node, *diffused_nodes.keys()]:
            normalized[node_id] = self.normalize_by_volume(node_id, dealer_30d_volume)

        return normalized

    # ------------------------------------------------------------------
    # Feature-layer convenience accessor (used by engine/features.py)
    # ------------------------------------------------------------------
    def aggregate_for_application(
        self,
        device_hash: str,
        dealer_id: str,
        guarantor_id: Optional[str],
        bank_hash: str,
    ) -> Dict[str, float]:
        """Roll up current (normalized) heat across an application's Infrastructure nodes, for model features."""
        graph = self._graph.graph
        node_ids = {
            "device_hash": self._graph.node_id(NodeType.DEVICE, device_hash),
            "dealer_id": self._graph.node_id(NodeType.DEALER, dealer_id),
            "guarantor_id": self._graph.node_id(NodeType.GUARANTOR, guarantor_id) if guarantor_id else None,
            "bank_hash": self._graph.node_id(NodeType.BANK_ACCOUNT, bank_hash),
        }

        readings: Dict[str, float] = {}
        for name, node_id in node_ids.items():
            if node_id and node_id in graph:
                node_data = graph.nodes[node_id]
                readings[name] = node_data.get("heat", node_data.get("raw_heat", 0.0))
            else:
                readings[name] = 0.0

        readings["max_pheromone"] = max(readings.values(), default=0.0)
        readings["sum_pheromone"] = sum(readings.values())
        return readings


# Module-level singleton, bound to the shared Living Graph in engine.graph.
# In production, back this with a shared/persistent store so heat survives
# process restarts and is consistent across API workers.
stigmergy_engine = StigmergyEngine(entity_graph)
