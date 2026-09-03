"""
engine/features.py
---------------------
Feature engineering layer. Combines raw application attributes with
graph-derived (engine.graph) and stigmergic (engine.stigmergy) signals
into a single feature vector consumable by engine.model.

Feature set
-----------
    normalized_device_heat   Volume-normalized stigmergic heat on the
                              application's Device node, clamped to [0, 1].
    connected_hotspots        Count of Infrastructure nodes within 2 hops
                              of the applicant (in the shared-entity graph)
                              whose normalized heat is >= HOTSPOT_THRESHOLD.
    credit_score               Applicant credit score, as submitted.
    dti_ratio                   Applicant debt-to-income ratio, as submitted.

Keeping this as its own module lets us version feature logic
independently of both the model and the graph/stigmergy internals, and
gives us a single place to keep the online (API) and offline
(training) feature pipelines in sync.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

from engine.graph import EntityGraph, NodeType, entity_graph
from engine.stigmergy import stigmergy_engine

logger = logging.getLogger("nexus.engine.features")

# Canonical, ordered feature list — must match the column order the
# model in engine.model was trained on.
FEATURE_COLUMNS = [
    "normalized_device_heat",
    "connected_hotspots",
    "credit_score",
    "dti_ratio",
]

# A node counts as a "hotspot" once its normalized heat crosses this level.
HOTSPOT_HEAT_THRESHOLD = 0.75

# How many hops out from the applicant to look for hotspot infrastructure.
HOTSPOT_SEARCH_DEPTH = 2


def _get_normalized_device_heat(device_hash: str) -> float:
    """
    Read the current (volume-normalized) heat on an application's Device
    node, clamped to [0, 1] so it behaves as a well-scaled model input
    regardless of how large raw stigmergic accumulation gets.
    """
    graph = entity_graph.graph
    device_node = entity_graph.node_id(NodeType.DEVICE, device_hash)

    if device_node not in graph:
        return 0.0

    heat = graph.nodes[device_node].get("heat", 0.0)
    return max(0.0, min(1.0, float(heat)))


def _count_connected_hotspots(
    applicant_id: str,
    depth: int = HOTSPOT_SEARCH_DEPTH,
    threshold: float = HOTSPOT_HEAT_THRESHOLD,
) -> int:
    """
    Count Infrastructure nodes within `depth` hops of the applicant (in the
    shared-entity graph) whose normalized `heat` attribute is >= `threshold`.

    Only Infrastructure nodes are counted — Applicant nodes never carry a
    `heat` attribute (see the zero-bleed invariant in engine/graph.py) so
    they are naturally excluded, but we filter on node type explicitly
    here too for clarity and defense-in-depth.
    """
    graph = entity_graph.graph
    applicant_node = entity_graph.node_id(NodeType.APPLICANT, applicant_id)

    if applicant_node not in graph:
        return 0

    # networkx import kept local to avoid pulling it in at module import
    # time for callers that only need the lighter graph helpers.
    import networkx as nx

    lengths = nx.single_source_shortest_path_length(graph, applicant_node, cutoff=depth)

    hotspot_count = 0
    for node_id, dist in lengths.items():
        if dist == 0:
            continue  # skip the applicant node itself
        data = graph.nodes[node_id]
        if data.get("type") in {t.value for t in (
            NodeType.DEVICE, NodeType.DEALER, NodeType.GUARANTOR, NodeType.BANK_ACCOUNT
        )}:
            if data.get("heat", 0.0) >= threshold:
                hotspot_count += 1

    return hotspot_count


def build_feature_vector(
    applicant_id: str,
    device_hash: str,
    dealer_id: str,
    guarantor_id: Optional[str],
    bank_hash: str,
    credit_score: float,
    dti_ratio: float,
    dealer_30d_volume: int,
    is_suspicious_event: bool,
) -> pd.DataFrame:
    """
    Assemble a single-row feature DataFrame for one loan application.

    NOTE: `dealer_30d_volume` and `is_suspicious_event` are accepted for
    signature compatibility with the API layer and because they drive the
    upstream stigmergy pipeline (volume normalization, deposit sizing),
    but they are not themselves included as model features — their
    influence flows into `normalized_device_heat` instead.

    TODO: this currently reads network/stigmergy state in-process. In
    production, consider precomputing these via a feature store /
    streaming job so the API path stays low-latency.
    """
    logger.info("Building feature vector for applicant_id=%s", applicant_id)

    row: Dict[str, Any] = {
        "normalized_device_heat": _get_normalized_device_heat(device_hash),
        "connected_hotspots": _count_connected_hotspots(applicant_id),
        "credit_score": credit_score,
        "dti_ratio": dti_ratio,
    }

    df = pd.DataFrame([row], columns=FEATURE_COLUMNS)
    return df


def feature_importance_labels() -> Dict[str, str]:
    """
    Human-readable labels for each feature, used when translating SHAP
    output into "top_drivers" strings for the API response.

    TODO: refine copy with risk/compliance team; consider i18n.
    """
    return {
        "normalized_device_heat": "Device heat reuse across concurrent applications",
        "connected_hotspots": "Connected fraud hotspots in the shared-entity network",
        "credit_score": "Applicant credit score",
        "dti_ratio": "Debt-to-income ratio",
    }
