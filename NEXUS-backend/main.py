"""
Project NEXUS — Early-Warning Fraud Intelligence Engine (Backend)
====================================================================
FastAPI application entrypoint.

Run locally with:
    uvicorn main:app --reload --port 8000

Endpoints:
    POST /analyze-loan          Score a loan application for fraud risk.
    GET  /network/{applicant_id} Fetch the shared-entity network around an applicant.
    GET  /risk/{applicant_id}    Fetch the most recent risk assessment for an applicant.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engine.explainability import compute_top_drivers, generate_counterfactual
from engine.features import build_feature_vector
from engine.graph import entity_graph
from engine.model import fraud_risk_model
from engine.stigmergy import stigmergy_engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("nexus.main")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Project NEXUS — Fraud Intelligence Engine",
    description="Early-warning fraud intelligence engine for lending applications.",
    version="0.1.0",
)

# Allow all origins for React frontend integration during development.
# TODO: lock this down to the deployed frontend origin(s) before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store of the most recent risk assessment per applicant, used
# to back GET /risk/{applicant_id}. Replace with a real datastore
# (Postgres, DynamoDB, etc.) in production.
_risk_assessment_cache: Dict[str, "AnalyzeLoanResponse"] = {}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AnalyzeLoanRequest(BaseModel):
    application_id: str = Field(..., description="Unique identifier for this loan application.")
    applicant_id: str = Field(..., description="Unique identifier for the applicant.")
    device_hash: str = Field(..., description="Hashed device fingerprint used to submit the application.")
    dealer_id: str = Field(..., description="Identifier of the originating dealer.")
    guarantor_id: Optional[str] = Field(None, description="Identifier of the guarantor, if any.")
    bank_hash: str = Field(..., description="Hashed bank account identifier linked to the application.")
    credit_score: float = Field(..., ge=300, le=850, description="Applicant credit score.")
    dti_ratio: float = Field(..., ge=0.0, le=2.0, description="Debt-to-income ratio.")
    dealer_30d_volume: int = Field(..., ge=0, description="Dealer's application volume over the trailing 30 days.")
    is_suspicious_event: bool = Field(False, description="Whether this application triggered a suspicious-event flag.")

    class Config:
        json_schema_extra = {
            "example": {
                "application_id": "APP-100234",
                "applicant_id": "APPLICANT-88213",
                "device_hash": "dvc_9f3a2b",
                "dealer_id": "DEALER-047",
                "guarantor_id": "GUAR-1123",
                "bank_hash": "bnk_77c1e4",
                "credit_score": 612,
                "dti_ratio": 0.47,
                "dealer_30d_volume": 138,
                "is_suspicious_event": True,
            }
        }


class NetworkPayload(BaseModel):
    applicant_id: str
    nodes: List[Dict] = Field(default_factory=list)
    edges: List[Dict] = Field(default_factory=list)
    shared_entity_count: int = 0
    ring_score: float = 0.0


class AnalyzeLoanResponse(BaseModel):
    application_id: str
    applicant_id: str
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Model risk score in [0, 1].")
    risk_tier: str = Field(..., description="Categorical risk tier: LOW, MEDIUM, or HIGH.")
    top_drivers: List[str] = Field(default_factory=list, description="Ranked human-readable risk drivers.")
    network: Dict = Field(default_factory=dict, description="Shared-entity network snapshot for this applicant.")
    counterfactual: str = Field(..., description="Plain-English statement of what would reduce this risk score.")


class RiskLookupResponse(BaseModel):
    applicant_id: str
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None
    last_application_id: Optional[str] = None
    found: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
def health_check() -> Dict[str, str]:
    """Basic liveness check."""
    return {"status": "ok", "service": "nexus-backend"}


@app.post("/analyze-loan", response_model=AnalyzeLoanResponse, tags=["analysis"])
def analyze_loan(request: AnalyzeLoanRequest) -> AnalyzeLoanResponse:
    """
    Score a loan application for fraud risk.

    Pipeline:
      1. Upsert the application into the shared-entity graph.
      2. Deposit stigmergic signal if this application is flagged suspicious.
      3. Build the feature vector (tabular + graph + stigmergy signals).
      4. Score with the fraud risk model.
      5. Explain the score (top drivers + counterfactual).
    """
    logger.info(
        "Analyzing loan application_id=%s applicant_id=%s",
        request.application_id,
        request.applicant_id,
    )

    try:
        entity_graph.upsert_application(
            application_id=request.application_id,
            applicant_id=request.applicant_id,
            device_hash=request.device_hash,
            dealer_id=request.dealer_id,
            guarantor_id=request.guarantor_id,
            bank_hash=request.bank_hash,
            dealer_30d_volume=request.dealer_30d_volume,
        )

        # Deposit -> diffuse -> normalize a stigmergic risk trace on every
        # application touch (deposit amount depends on is_suspicious_event;
        # see engine/stigmergy.py).
        stigmergy_engine.process_application_event(
            applicant_id=request.applicant_id,
            device_hash=request.device_hash,
            dealer_id=request.dealer_id,
            guarantor_id=request.guarantor_id,
            bank_hash=request.bank_hash,
            is_suspicious_event=request.is_suspicious_event,
        )

        feature_df = build_feature_vector(
            applicant_id=request.applicant_id,
            device_hash=request.device_hash,
            dealer_id=request.dealer_id,
            guarantor_id=request.guarantor_id,
            bank_hash=request.bank_hash,
            credit_score=request.credit_score,
            dti_ratio=request.dti_ratio,
            dealer_30d_volume=request.dealer_30d_volume,
            is_suspicious_event=request.is_suspicious_event,
        )

        risk_score = fraud_risk_model.score(feature_df)
        risk_tier = fraud_risk_model.tier_for_score(risk_score)
        top_drivers = compute_top_drivers(feature_df)
        counterfactual = generate_counterfactual(feature_df, risk_score)
        network = entity_graph.get_neighborhood(request.applicant_id)

        response = AnalyzeLoanResponse(
            application_id=request.application_id,
            applicant_id=request.applicant_id,
            risk_score=round(risk_score, 4),
            risk_tier=risk_tier,
            top_drivers=top_drivers,
            network=network,
            counterfactual=counterfactual,
        )

        _risk_assessment_cache[request.applicant_id] = response
        return response

    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to analyze loan application_id=%s", request.application_id)
        raise HTTPException(status_code=500, detail=f"Failed to analyze loan: {exc}") from exc


@app.get("/network/{applicant_id}", response_model=NetworkPayload, tags=["network"])
def get_network(applicant_id: str) -> NetworkPayload:
    """
    Fetch the shared-entity network neighborhood for a given applicant,
    for rendering in the React frontend's graph visualization.
    """
    logger.info("Fetching network for applicant_id=%s", applicant_id)
    try:
        neighborhood = entity_graph.get_neighborhood(applicant_id)
        return NetworkPayload(**neighborhood)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to fetch network for applicant_id=%s", applicant_id)
        raise HTTPException(status_code=500, detail=f"Failed to fetch network: {exc}") from exc


@app.get("/risk/{applicant_id}", response_model=RiskLookupResponse, tags=["risk"])
def get_risk(applicant_id: str) -> RiskLookupResponse:
    """
    Fetch the most recent cached risk assessment for an applicant.

    TODO: back this with a persistent store rather than the in-memory
    cache, so risk history survives restarts and supports auditing.
    """
    logger.info("Fetching cached risk assessment for applicant_id=%s", applicant_id)
    cached = _risk_assessment_cache.get(applicant_id)

    if cached is None:
        return RiskLookupResponse(applicant_id=applicant_id, found=False)

    return RiskLookupResponse(
        applicant_id=applicant_id,
        risk_score=cached.risk_score,
        risk_tier=cached.risk_tier,
        last_application_id=cached.application_id,
        found=True,
    )
