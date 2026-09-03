"""
engine/explainability.py
---------------------------
Turns raw model output into analyst-readable explanations:

  * top_drivers     — ranked, human-readable list of the features that
                       pushed this application's risk_score up (or down),
                       via SHAP.
  * counterfactual   — a plain-English "what would need to change" string,
                       useful for adverse-action notices and analyst review.

NOTE: `shap.TreeExplainer` is wired up against the live model. The
counterfactual logic performs a real (if simple) 1-D search over a single
actionable feature at a time — holding the others fixed — rather than a
full multi-feature counterfactual optimizer (e.g. DiCE).
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd
import shap

from engine.features import FEATURE_COLUMNS, feature_importance_labels
from engine.model import (
    HIGH_RISK_LOWER_BOUND,
    LOW_RISK_UPPER_BOUND,
    fraud_risk_model,
)

logger = logging.getLogger("nexus.engine.explainability")

_labels = feature_importance_labels()

# Lazily constructed — SHAP explainer setup has some overhead, so we
# build it once against the module-level model singleton.
_explainer: Optional[shap.TreeExplainer] = None

# Human-readable driver phrasing per (feature, direction). "up" means the
# feature pushed risk_score higher; "down" means it pulled risk_score lower.
_DRIVER_PHRASES = {
    ("normalized_device_heat", "up"): "High device heat reuse detected across concurrent applications",
    ("normalized_device_heat", "down"): "Low device heat reuse across concurrent applications",
    ("connected_hotspots", "up"): "Multiple connected fraud hotspots detected in the shared-entity network",
    ("connected_hotspots", "down"): "No connected fraud hotspots detected in the shared-entity network",
    ("credit_score", "up"): "Credit score below the typical range for approved applications",
    ("credit_score", "down"): "Strong credit score relative to typical applications",
    ("dti_ratio", "up"): "Elevated debt-to-income ratio",
    ("dti_ratio", "down"): "Healthy, well-controlled debt-to-income ratio",
}

# Actionable features + search bounds/step for counterfactual search, in
# priority order (most naturally "explainable to an investigator" first).
_COUNTERFACTUAL_SEARCH_SPACE = {
    "normalized_device_heat": {"low": 0.0, "high": 1.0, "step": 0.01, "fmt": lambda v: f"{v:.2f}"},
    "dti_ratio": {"low": 0.0, "high": 1.5, "step": 0.01, "fmt": lambda v: f"{v:.2f}"},
    "credit_score": {"low": 300.0, "high": 850.0, "step": 1.0, "fmt": lambda v: f"{int(round(v))}"},
    "connected_hotspots": {"low": 0.0, "high": 10.0, "step": 1.0, "fmt": lambda v: f"{int(round(v))}"},
}

_COUNTERFACTUAL_PHRASE = {
    "normalized_device_heat": "device heat was below {value}",
    "dti_ratio": "the debt-to-income ratio was below {value}",
    "credit_score": "the credit score was above {value}",
    "connected_hotspots": "connected hotspots dropped below {value}",
}


def _get_explainer() -> shap.TreeExplainer:
    global _explainer
    if _explainer is None:
        logger.info("Constructing SHAP TreeExplainer for fraud risk model")
        _explainer = shap.TreeExplainer(fraud_risk_model.underlying)
    return _explainer


def _row_shap_values(feature_df: pd.DataFrame) -> np.ndarray:
    """Return a flat array of per-feature SHAP contributions for the single input row."""
    explainer = _get_explainer()
    shap_values = explainer.shap_values(feature_df[FEATURE_COLUMNS])

    row_values = np.array(shap_values)
    # shap_values may come back shaped (n_rows, n_features) or, for some
    # model/output configs, as a list-like of per-class arrays — normalize
    # down to a single 1-D row of per-feature contributions.
    if row_values.ndim == 3:
        row_values = row_values[0]
    if row_values.ndim == 2:
        row_values = row_values[0]
    return row_values


def compute_top_drivers(feature_df: pd.DataFrame, top_n: int = 3) -> List[str]:
    """
    Compute the top_n features (by absolute SHAP value) driving this
    application's risk score, rendered as human-readable investigator
    driver strings (e.g. "High device heat reuse detected across
    concurrent applications").
    """
    row_values = _row_shap_values(feature_df)

    ranked_idx = np.argsort(-np.abs(row_values))[:top_n]
    drivers = []
    for idx in ranked_idx:
        feature_name = FEATURE_COLUMNS[idx]
        direction = "up" if row_values[idx] > 0 else "down"
        phrase = _DRIVER_PHRASES.get((feature_name, direction))
        if phrase is None:
            label = _labels.get(feature_name, feature_name)
            phrase = f"{label} {'increased' if direction == 'up' else 'decreased'} risk"
        drivers.append(phrase)

    return drivers


def _tier_for_score(risk_score: float) -> str:
    return fraud_risk_model.tier_for_score(risk_score)


def _search_counterfactual_value(
    feature_df: pd.DataFrame,
    feature_name: str,
    current_value: float,
    target_max_score: float,
) -> Optional[float]:
    """
    Binary-search a single feature's value (holding all others fixed) for
    the closest value to `current_value` that brings risk_score at or
    below `target_max_score`. Returns None if no value in the search
    bounds achieves the target.
    """
    bounds = _COUNTERFACTUAL_SEARCH_SPACE[feature_name]
    low, high = bounds["low"], bounds["high"]

    def score_with(value: float) -> float:
        trial = feature_df.copy()
        trial.loc[trial.index[0], feature_name] = value
        return fraud_risk_model.score(trial)

    # Determine search direction: does decreasing or increasing the
    # feature reduce risk? Probe both ends of the bounds.
    score_at_low = score_with(low)
    score_at_high = score_with(high)

    if score_at_low <= target_max_score and score_at_low <= score_at_high:
        target_bound, other_bound = low, high
        decreasing = current_value >= low
    elif score_at_high <= target_max_score:
        target_bound, other_bound = high, low
        decreasing = False
    else:
        return None  # neither extreme achieves the target risk level

    lo, hi = sorted((target_bound, current_value))
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if score_with(mid) <= target_max_score:
            if target_bound < current_value:
                lo = lo  # keep searching toward current_value from below
                hi = mid
            else:
                lo = mid
        else:
            if target_bound < current_value:
                lo = mid
            else:
                hi = mid

    candidate = hi if target_bound < current_value else lo
    return candidate


def generate_counterfactual(feature_df: pd.DataFrame, risk_score: float) -> str:
    """
    Produce a plain-English counterfactual statement describing what
    would most plausibly reduce this application's risk score to a lower
    tier (e.g. "If device heat was below 0.30, application would drop to
    LOW RISK").
    """
    current_tier = _tier_for_score(risk_score)
    if current_tier == "LOW RISK":
        return "Application is already in the lowest risk tier; no counterfactual change is needed."

    target_max_score = HIGH_RISK_LOWER_BOUND if current_tier == "HIGH RISK" else LOW_RISK_UPPER_BOUND
    target_tier = "MEDIUM RISK" if current_tier == "HIGH RISK" else "LOW RISK"

    row_values = _row_shap_values(feature_df)
    row = feature_df.iloc[0]

    # Consider actionable features that are currently pushing risk *up*,
    # ranked by SHAP magnitude, and try each until one yields a workable
    # counterfactual value.
    ranked_idx = np.argsort(-np.abs(row_values))
    for idx in ranked_idx:
        feature_name = FEATURE_COLUMNS[idx]
        if feature_name not in _COUNTERFACTUAL_SEARCH_SPACE:
            continue
        if row_values[idx] <= 0:
            continue  # this feature isn't pushing risk up; skip

        current_value = float(row[feature_name])
        candidate_value = _search_counterfactual_value(
            feature_df, feature_name, current_value, target_max_score
        )
        if candidate_value is None:
            continue

        fmt = _COUNTERFACTUAL_SEARCH_SPACE[feature_name]["fmt"]
        phrase = _COUNTERFACTUAL_PHRASE[feature_name].format(value=fmt(candidate_value))
        return f"If {phrase}, application would drop to {target_tier}."

    return (
        "Risk is being driven by a combination of network and behavioral signals; "
        "no single feature change would reliably move this application to a lower risk tier."
    )
