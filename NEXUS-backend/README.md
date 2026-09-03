# Project NEXUS — Fraud Intelligence Engine (Backend)

Early-warning fraud intelligence engine for lending. This backend detects
emerging fraud rings by combining tabular risk signals with a **shared-entity
graph** (device/dealer/guarantor/bank linkages) and a **stigmergic signal
layer** (decaying "pheromone" trails deposited by suspicious events), then
scores applications with an XGBoost model and explains each score with SHAP.

> **Status:** scaffold / placeholder implementation. Model, graph, and
> stigmergy layers use synthetic data and in-memory state so the API is
> runnable end-to-end during frontend integration. See `TODO` comments
> throughout `engine/` for what needs real implementations before production.

## Directory structure

```
NEXUS-backend/
├── main.py                  FastAPI app: schemas, endpoints, CORS, logging
├── requirements.txt
├── README.md
├── engine/
│   ├── __init__.py
│   ├── graph.py              Shared-entity graph (NetworkX)
│   ├── stigmergy.py          Pheromone-style decaying signal accumulation
│   ├── features.py           Feature engineering (tabular + graph + stigmergy)
│   ├── model.py               XGBoost model wrapper + risk tiering
│   └── explainability.py     SHAP-based top drivers + counterfactual generation
└── data/                    Place model artifacts / datasets here
```

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`, with interactive docs
at `http://localhost:8000/docs`.

CORS is configured to allow all origins, so the React frontend can call this
API directly during development. **Lock `allow_origins` down before
deploying to production** (see `main.py`).

## Endpoints

### `POST /analyze-loan`

Scores a loan application for fraud risk.

**Request body:**

```json
{
  "application_id": "APP-100234",
  "applicant_id": "APPLICANT-88213",
  "device_hash": "dvc_9f3a2b",
  "dealer_id": "DEALER-047",
  "guarantor_id": "GUAR-1123",
  "bank_hash": "bnk_77c1e4",
  "credit_score": 612,
  "dti_ratio": 0.47,
  "dealer_30d_volume": 138,
  "is_suspicious_event": true
}
```

**Response body:**

```json
{
  "application_id": "APP-100234",
  "applicant_id": "APPLICANT-88213",
  "risk_score": 0.7231,
  "risk_tier": "HIGH",
  "top_drivers": [
    "Flagged suspicious event on this application increased risk",
    "Debt-to-income ratio increased risk",
    "Peak fraud-signal accumulation on linked entities increased risk"
  ],
  "network": {
    "applicant_id": "APPLICANT-88213",
    "nodes": [...],
    "edges": [...],
    "shared_entity_count": 0,
    "ring_score": 0.0
  },
  "counterfactual": "Reducing the debt-to-income ratio from 0.47 to below 0.40 would likely move this application to a lower risk tier."
}
```

### `GET /network/{applicant_id}`

Returns the shared-entity network neighborhood around an applicant
(nodes/edges), for the React frontend's graph visualization component.

### `GET /risk/{applicant_id}`

Returns the most recently cached risk assessment for an applicant.

## What's a placeholder vs. real

| Component | Current state | Needed for production |
|---|---|---|
| `engine/model.py` | Synthetic-data XGBoost fit at startup | Trained, validated, versioned model artifact loaded from `data/` or a model registry |
| `engine/graph.py` | In-memory NetworkX graph, empty neighborhoods | Persistent graph store (Neo4j/TigerGraph) or rehydrated NetworkX snapshot; real BFS/ring detection |
| `engine/stigmergy.py` | In-memory decaying pheromone dict | Redis/feature-store backed, shared across processes |
| `engine/explainability.py` | SHAP wired to live model; counterfactual is heuristic | Proper counterfactual search (e.g. DiCE) respecting actionable/immutable features |
| Risk cache in `main.py` | In-memory dict | Persistent datastore (Postgres/DynamoDB) with audit history |
| CORS | `allow_origins=["*"]` | Restrict to deployed frontend origin(s) |

## Logging

Basic logging is configured in `main.py` via `logging.basicConfig`, with
per-module loggers (`nexus.main`, `nexus.engine.*`) at `INFO` level. Adjust
`level=` in `main.py` for more/less verbosity during development.
