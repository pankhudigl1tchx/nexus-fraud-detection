"""
Project NEXUS — Early-Warning Fraud Intelligence Engine
---------------------------------------------------------
Core engine package.

Modules:
    graph.py            Shared-entity graph construction (device/dealer/guarantor/bank rings).
    stigmergy.py         Stigmergic signal accumulation ("digital pheromone" trails on shared entities).
    features.py          Feature engineering combining tabular + graph/stigmergy signals.
    model.py              Model loading, training stub, and scoring (XGBoost).
    explainability.py    SHAP-based driver extraction and counterfactual generation.
"""

__version__ = "0.1.0"
