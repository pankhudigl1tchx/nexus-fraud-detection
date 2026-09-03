"""
engine/model.py
------------------
Model layer for NEXUS's fraud risk scoring. Wraps an XGBoost classifier
and exposes a simple `score()` interface to the API layer.

Training
--------
On startup, `_train_model()` builds a synthetic dataset of 500 historical
loan applications made up of two generating processes:

  * ~65% "normal" applications — healthy credit, modest DTI, little to no
    device-heat reuse, and no connected hotspots. Labeled non-fraud.
  * ~35% "fraudulent" applications — patterns consistent with ring fraud:
    elevated device-heat reuse (the same device/dealer/bank infrastructure
    showing up hot across concurrent applications), multiple connected
    hotspots, and often (but not always) weaker credit/DTI profiles.
    Labeled fraud.

NOTE: This is a placeholder training set, not a fitted-on-real-data
model. Replace `_train_model()` with real historical-outcome training
data (and proper train/validation/test splits, calibration, etc.)
before this is used for real underwriting decisions.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import xgboost as xgb

from engine.features import FEATURE_COLUMNS

logger = logging.getLogger("nexus.engine.model")

# Risk tier cut points on the [0, 1] risk_score scale.
#   LOW    : risk_score < 0.35
#   MEDIUM : 0.35 <= risk_score <= 0.65
#   HIGH   : risk_score > 0.65
LOW_RISK_UPPER_BOUND = 0.35
HIGH_RISK_LOWER_BOUND = 0.65

N_HISTORICAL_APPLICATIONS = 500
FRAUD_RATE = 0.35


def _generate_synthetic_training_data(
    n_samples: int = N_HISTORICAL_APPLICATIONS,
    fraud_rate: float = FRAUD_RATE,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Generate a synthetic dataset of historical loan applications, drawn
    from two distinct generating distributions (normal vs. fraudulent),
    so the placeholder model learns directionally sane decision
    boundaries rather than fitting pure noise.
    """
    rng = np.random.default_rng(seed=seed)

    n_fraud = int(round(n_samples * fraud_rate))
    n_normal = n_samples - n_fraud

    # --- Normal applications ------------------------------------------------
    normal = pd.DataFrame(
        {
            "normalized_device_heat": np.clip(rng.beta(1.5, 8.0, n_normal), 0.0, 1.0),
            "connected_hotspots": rng.choice([0, 0, 0, 1], size=n_normal),
            "credit_score": rng.normal(690, 60, n_normal).clip(300, 850),
            "dti_ratio": np.clip(rng.normal(0.32, 0.10, n_normal), 0.0, 1.5),
        }
    )
    normal_labels = pd.Series(np.zeros(n_normal, dtype=int))

    # --- Fraudulent applications ---------------------------------------------
    # Ring-fraud-like profile: hot, reused infrastructure and multiple
    # connected hotspots, with credit/DTI skewed weaker on average but
    # overlapping with normal (fraud isn't always low-credit).
    fraud = pd.DataFrame(
        {
            "normalized_device_heat": np.clip(rng.beta(6.0, 2.0, n_fraud), 0.0, 1.0),
            "connected_hotspots": rng.integers(1, 7, n_fraud),
            "credit_score": rng.normal(600, 90, n_fraud).clip(300, 850),
            "dti_ratio": np.clip(rng.normal(0.55, 0.18, n_fraud), 0.0, 1.5),
        }
    )
    fraud_labels = pd.Series(np.ones(n_fraud, dtype=int))

    features = pd.concat([normal, fraud], ignore_index=True)[FEATURE_COLUMNS]
    labels = pd.concat([normal_labels, fraud_labels], ignore_index=True)

    # Shuffle so the model doesn't see a block of all-normal followed by
    # all-fraud rows during any internal validation splitting.
    shuffle_idx = rng.permutation(n_samples)
    features = features.iloc[shuffle_idx].reset_index(drop=True)
    labels = labels.iloc[shuffle_idx].reset_index(drop=True)

    return features, labels


def _train_model() -> xgb.XGBClassifier:
    """
    Train an XGBoost classifier on the synthetic 500-application
    historical dataset described above.

    TODO: replace this entirely once a real trained model artifact
    (versioned, validated, monitored) is available in `data/`.
    """
    logger.warning(
        "No trained model artifact found — training an in-memory XGBoost "
        "model on a synthetic 500-application dataset. DO NOT use this "
        "for real underwriting decisions."
    )

    features, labels = _generate_synthetic_training_data()

    model = xgb.XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
    )
    model.fit(features, labels)

    logger.info(
        "Trained fraud risk model on %d synthetic historical applications "
        "(%d normal / %d fraudulent).",
        len(features),
        int((labels == 0).sum()),
        int((labels == 1).sum()),
    )
    return model


class FraudRiskModel:
    """Thin wrapper around the underlying XGBoost model."""

    def __init__(self) -> None:
        self._model: xgb.XGBClassifier = _train_model()

    def score(self, feature_df: pd.DataFrame) -> float:
        """
        Return a risk_score in [0, 1] for a single-row feature DataFrame.

        TODO: add batch scoring support and confidence intervals.
        """
        proba = self._model.predict_proba(feature_df[FEATURE_COLUMNS])[:, 1]
        return float(proba[0])

    def tier_for_score(self, risk_score: float) -> str:
        """
        Classify a risk_score into an investigator-facing risk tier:
            LOW RISK    : risk_score < 0.35
            MEDIUM RISK : 0.35 <= risk_score <= 0.65
            HIGH RISK   : risk_score > 0.65
        """
        if risk_score < LOW_RISK_UPPER_BOUND:
            return "LOW RISK"
        if risk_score <= HIGH_RISK_LOWER_BOUND:
            return "MEDIUM RISK"
        return "HIGH RISK"

    @property
    def underlying(self) -> xgb.XGBClassifier:
        """Expose the raw model, e.g. for SHAP explainer construction."""
        return self._model


# Module-level singleton loaded once at process startup.
fraud_risk_model = FraudRiskModel()
