# ⚡ NEXUS | Autonomous & Explainable Graph-AI Fraud Detection System

> **Transforming passive rule-based risk management into active, real-time, explainable AI fraud mitigation.**

---

## 🎯 The Problem (Why NEXUS?)

Traditional fraud detection systems fail modern financial networks:
* **Static Rules** miss evolving fraud patterns, novel tactics, and organized syndicate rings.
* **Black-Box ML Models** flag transactions without explaining *why*, frustrating compliance teams and causing high false-positive rates.
* **Siloed Evaluation** treats each application or transaction in isolation, completely ignoring hidden topological connections between bad actors.

---

## 💡 What is NEXUS?

**NEXUS** is an end-to-end autonomous fraud detection engine that evaluates loan applications and high-risk financial transactions in real time. By uniting **Graph Neural Structures**, **Stigmergic Behavioral Tracking**, and **Explainable AI (SHAP drivers)**, NEXUS identifies individual bad actors, exposes hidden fraud syndicates, and provides human-auditable risk explanations instantly.

---

## 🚀 The Innovation: What Makes NEXUS Different?

| Dimension | Legacy Fraud Systems | NEXUS Autonomous Engine |
| :--- | :--- | :--- |
| **Data Topology** | Tabular, isolated evaluation | **Graph Link Analysis** (detects shared device, IP, and identity rings) |
| **Decision Logic** | Binary pass/fail threshold | **Dynamic Stigmergy & Weighted Risk Scoring** |
| **Explainability** | Black-box outputs | **Real-Time SHAP Drivers** (explains exact risk factors per decision) |
| **Architecture** | Heavy legacy monoliths | **Ultra-Fast Next.js 16 App + Async FastAPI Engine** |

---

## 🛠️ System Architecture & How It Works

### **Data Flow Pipeline**

1. **Frontend Request Layer**  
   The **NEXUS Dashboard** (`Next.js 16 / React 19`) captures loan applications or transaction payloads and dispatches a JSON payload via REST API.

2. **Async Orchestration Layer**  
   The **FastAPI Engine** (`NEXUS-backend/main.py`) processes incoming payloads asynchronously, passing structured input to the specialized AI engines.

3. **Graph & Stigmergy Engine**  
   * **Link Analysis (`NEXUS-backend/engine/graph.py`):** Maps complex non-linear relationships, shared entities, and transaction paths to catch organized fraud rings.
   * **Stigmergy Engine (`NEXUS-backend/engine/stigmergy.py`):** Captures behavioral markers left behind over time to detect adaptive, multi-stage fraud patterns.

4. **ML Risk & Explainability Engine**  
   * **ML Scoring (`NEXUS-backend/engine/model.py`):** Evaluates applicant attributes against machine learning models to generate accurate risk confidence metrics.
   * **Explainable AI (`NEXUS-backend/engine/explainability.py`):** Calculates exact SHAP impact values for every transaction, delivering clear visual risk drivers for instant compliance auditing.

---

## 💻 Tech Stack

* **Frontend:** Next.js 16 (App Router, Webpack), React 19, Tailwind CSS, Shadcn UI, Lucide Icons
* **Backend:** Python 3.11+, FastAPI, Uvicorn, Pydantic
* **AI Engine:** Scikit-Learn, SHAP (SHapley Additive exPlanations), Network Graph Algorithms

---

## ⚡ Quickstart (Local Run)

### 1. Backend Setup (FastAPI - Port 8000)
```bash
# Navigate to project root
cd Nexus2

# Activate Virtual Environment
.\venv\Scripts\Activate.ps1

# Install Backend Dependencies
pip install -r NEXUS-backend/requirements.txt

# Start FastAPI Server
uvicorn NEXUS-backend.main:app --reload --port 8000
