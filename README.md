# Agent Sentinel — AI Agent Misbehavior Detection & Recovery

> Making autonomous AI systems safer, explainable, controllable, and recoverable.

A working safety layer for autonomous AI agents. An agent proposes actions; this system
observes every one of them, scores how far it deviates from learned normal behaviour,
checks it against policy, assigns a risk score, explains itself, decides whether to allow,
monitor, hold for a human, block, or stop the agent — and when something gets through,
rolls the environment back and verifies the result.

**The pitch in one line:** the agent can act autonomously; this system makes sure those
actions stay inside safe boundaries.

---

## Table of contents

1. [The problem](#the-problem)
2. [The solution](#the-solution)
3. [Safety boundary](#safety-boundary)
4. [Architecture](#architecture)
5. [Features](#features)
6. [Tech stack](#tech-stack)
7. [ML approach](#ml-approach)
8. [Risk engine](#risk-engine)
9. [Policy engine](#policy-engine)
10. [Recovery & verification](#recovery--verification)
11. [Installation](#installation)
12. [Running the project](#running-the-project)
13. [Demo script (3 minutes)](#demo-script-3-minutes)
14. [Scenarios](#scenarios)
15. [API documentation](#api-documentation)
16. [Database schema](#database-schema)
17. [Project structure](#project-structure)
18. [Testing](#testing)
19. [Screenshots](#screenshots)
20. [Limitations & future work](#limitations--future-work)

---

## The problem

An autonomous agent with tool access can act outside its intended task because of faulty
reasoning, unexpected input, prompt injection, goal misalignment, excessive permissions, or
simply getting stuck in a loop. The failure modes that matter are not crashes — they are
*plausible-looking actions on the wrong resource*: reading a file it shouldn't, escalating
its own permissions, exporting data, dropping a table.

Guardrails written as a fixed allow-list miss behaviour nobody thought to enumerate. A
model-only detector flags legitimate work and can be talked around. Neither is enough alone.

## The solution

A layered runtime safety envelope around the agent:

```
OBSERVE → DETECT → ASSESS RISK → EXPLAIN → ALLOW/BLOCK/PAUSE → RECOVER → VERIFY → AUDIT
```

| Layer | Answers | Implementation |
|---|---|---|
| **ML behaviour detection** | *How unusual is this?* | Isolation Forest on 16 behavioural features |
| **Policy enforcement** | *Is this permitted?* | Declarative rules in `agent_policy.json` |
| **Risk scoring** | *How much does it matter?* | Weighted fusion of anomaly + consequence |
| **Explanation** | *Why did you stop me?* | Generated from the factors that actually fired |
| **Human oversight** | *Should a person decide?* | Blocking approval queue for HIGH-consequence actions |
| **Recovery + verification** | *Did we actually get back to safe?* | Rollback, then re-inspect and report the truth |

No layer is trusted alone. That is the central architectural claim of the project.

## Safety boundary

**This is a controlled simulation.** Every "dangerous" action is simulated inside a sandbox
that lives in SQLite rows. `DELETE_DATABASE` flips a string from `HEALTHY` to `DELETED`. It
never touches a real database, file, service, permission, or host.

The project requires **no** passwords, API keys, cloud credentials, production
infrastructure, or sensitive data. The behavioural dataset is **synthetic**, generated
locally by a script in this repo, and is labelled as such throughout the UI and the code.

## Architecture

```
  ┌──────────────────────── React Dashboard ────────────────────────┐
  │  Simulation Lab · Agent Monitor · Incidents · Approvals · Audit  │
  └───────────────▲──────────────────────────────▲──────────────────┘
        REST /api │                              │ WebSocket /ws/events
  ┌───────────────┴──────────────────────────────┴──────────────────┐
  │                        FastAPI  ·  Agent Sentinel                │
  │                                                                  │
  │   Agent Simulator ──► attempted action ──► SAFETY PIPELINE       │
  │                                                │                 │
  │        ┌───────────────────────────────────────┤                 │
  │        ▼                                       ▼                 │
  │  Feature Extractor                       Policy Engine           │
  │  (16 behavioural features)               (agent_policy.json)     │
  │        ▼                                       │                 │
  │  Isolation Forest ──► anomaly 0–1 ─────────────┤                 │
  │                                                ▼                 │
  │                                        Risk Engine (0–100)       │
  │                                                ▼                 │
  │                                     Explanation Engine           │
  │                                                ▼                 │
  │      ALLOW │ MONITOR │ REQUIRE_APPROVAL │ BLOCK │ BLOCK+STOP     │
  │                                                ▼                 │
  │        Incident ──► Recovery ──► State Verification              │
  │                                                ▼                 │
  │                       Audit Logger  (SQLite, append-only)        │
  └──────────────────────────────────────────────────────────────────┘
```

The whole pipeline is one function — `backend/app/services/pipeline.py::evaluate_action` —
used identically by the simulator, the REST API, and the tests. There is no separate "demo
path".

## Features

- **Live simulation lab** — pick a scenario, watch the pipeline run over WebSocket
- **Real ML scoring** — every anomaly score is a live Isolation Forest inference, with the
  raw score and full feature vector visible in the UI
- **Explainable interventions** — each row expands into risk factors, weights, policy
  violations, and a generated natural-language explanation
- **Behavioural sequence visualisation** — learned profile vs. observed chain, deviations
  highlighted
- **Human-in-the-loop approvals** — high-consequence actions block until a person decides;
  duplicate decisions are rejected
- **Automated recovery with honest verification** — the environment is re-inspected after
  rollback; "verified" is only reported when every check passes
- **Audit replay** — step through an incident's timeline like a recording
- **Filterable audit trail** with CSV export
- **Model evaluation page** — precision/recall/F1/FPR read from the training report, plus an
  explanation of why accuracy is the wrong headline metric here
- **Graceful degradation** — if the model artifact is missing, the safety layer still runs on
  a transparent heuristic and labels every score as such

## Tech stack

**Backend** — Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite, Uvicorn
**ML** — scikit-learn (Isolation Forest), pandas, numpy, joblib
**Frontend** — React 18, TypeScript, Vite, Tailwind CSS, Recharts, lucide-react
**Realtime** — WebSocket (`/ws/events`) with automatic reconnect and backoff

## ML approach

**Framing.** This is *one-class novelty detection*, not classification. We know what
sanctioned agent behaviour looks like; we cannot enumerate every way an agent can go wrong.
The model is therefore trained **only on normal behaviour** and never sees a label.

**Features** (`backend/ml/features.py`, 16 dimensions):

| Feature | Meaning |
|---|---|
| `permission_level` | Ordinal privilege requested (public → restricted) |
| `resource_sensitivity` | How sensitive the touched resource is |
| `action_severity` | Blast radius if the action executed |
| `task_relevance` | How well the action serves the assigned task |
| `sequence_deviation` | Unlikelihood of the `prev_action → action` transition |
| `repeated_action_count` | Identical actions already seen this session |
| `time_since_prev` | Normalised inter-action interval |
| `tool_rarity` | How unusual this tool is for the agent |
| `step_position` | Position in the session |
| `is_destructive` | Irreversibility flag |
| `cat_*` (6) | One-hot action category |

**Score normalisation.** Isolation Forest's `score_samples` is unbounded, higher = more
normal. It is mapped to a 0–1 anomaly score with a logistic curve:

```
anomaly = 1 / (1 + exp((raw − t) / s))
```

- `t` = 5th percentile of the raw scores of the normal training data, so ~95% of normal
  behaviour lands below 0.5
- `s` = standard deviation of those raw scores ÷ 4, controlling saturation sharpness

Both constants are stored **inside the model artifact**, so runtime scoring is bit-identical
to training. The model is loaded once at startup and is never retrained on boot.

**Measured results** (held-out 30% split of the synthetic dataset — reproduce with
`python -m backend.ml.train_model`):

| Metric | Value |
|---|---|
| Precision | 0.830 |
| Recall | 0.938 |
| F1 | 0.881 |
| Accuracy | 0.943 |
| False positive rate | 0.055 |
| False negative rate | 0.062 |
| Mean anomaly — normal actions | 0.065 |
| Mean anomaly — abnormal actions | 0.901 |

Trained on 4,594 normal actions; evaluated on 2,536 held-out records (567 abnormal).

**On accuracy.** Accuracy is a weak metric here: the classes are imbalanced and the model is
unsupervised. Precision, recall and especially the false-positive rate are what matter — a
5.5% FPR means a model-only guardrail would block legitimate agent work several times an
hour. That is exactly why the model is *an input to* the decision and never the decision.

## Risk engine

Risk is **not** the anomaly score rescaled. It is a weighted fusion (weights live in
`agent_policy.json` and are editable without touching code):

```
risk = 0.30·anomaly + 0.18·resource_sensitivity + 0.16·permission_risk
     + 0.22·action_severity + 0.14·task_relevance_gap
     + policy_violation_penalty
```

with a floor of 88 for any destructive, explicitly-denied operation. Levels:

| Range | Level | Default action |
|---|---|---|
| 0–29 | LOW | Allow |
| 30–59 | MEDIUM | Allow + monitor |
| 60–84 | HIGH | Human approval |
| 85–100 | CRITICAL | Block (+ stop the agent if irreversible) |

The UI shows every factor, its weight, and its point contribution, so the number is always
traceable.

## Policy engine

`backend/app/policies/agent_policy.json` — six deterministic checks per action:

1. Is the action in the agent's sanctioned capability set?
2. Is it on the permanent deny-list?
3. Is the resource inside the declared task scope?
4. Is task relevance above the floor?
5. Does it exceed the privilege ceiling?
6. Is it destructive?

Plus two enforcement nuances that matter for realism:

- **Blocking ≠ halting.** A denied but *reversible* action (e.g. a permission change) is
  blocked while the agent keeps running under suspicion, so the system can observe where the
  behaviour goes next. Only a CRITICAL *irreversible* attempt stops the agent outright.
- **Repeat-offender rule.** One block is not proof of compromise; a pattern is. After
  `max_blocked_actions_per_session` (default 3) blocked attempts, the agent is paused for
  human review.

## Recovery & verification

1. Snapshot the compromised simulated state
2. Restore every resource to its known-good baseline
3. **Re-inspect** each resource and compare against baseline
4. Report `RECOVERY VERIFIED` only if every check passes, `RECOVERY FAILED` otherwise
5. Record every step as `RecoveryEvent` rows and audit entries

Verification never assumes success — `backend/tests/test_pipeline.py::test_verification_reports_failure_honestly`
asserts it reports failure when the world is still broken.

## Installation

Requires **Python 3.11+** and **Node 18+**.

### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.ml.generate_dataset
python -m backend.ml.train_model
python -m backend.app.database.seed
cd frontend; npm install; cd ..
```

Or run the helper script:

```powershell
.\scripts\setup.ps1
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m backend.ml.generate_dataset
python -m backend.ml.train_model
python -m backend.app.database.seed
cd frontend && npm install && cd ..
```

Or: `bash scripts/setup.sh`

All commands are run from the **project root** — the backend is a package, so `python -m ...`
and `uvicorn backend.app.main:app` both resolve from there.

## Running the project

Two terminals, both from the project root.

**Terminal 1 — backend** (http://127.0.0.1:8000, docs at `/docs`):

```bash
uvicorn backend.app.main:app --reload
```

**Terminal 2 — frontend** (http://localhost:5173):

```bash
cd frontend && npm run dev
```

Vite proxies `/api` and `/ws` to the backend, so no CORS configuration is needed in
development.

### Docker

```bash
docker compose up --build
```

The backend image generates the dataset, trains the model and seeds demo data at build time.

### Regenerating data and model

```bash
python -m backend.ml.generate_dataset --sessions 1200 --seed 42
python -m backend.ml.train_model --contamination 0.02 --n-estimators 250
python -m backend.app.database.seed          # resets the demo database
```

## Demo script (3 minutes)

1. Open **http://localhost:5173** → click **Launch Simulation**
2. Select **Critical Misbehaviour** → **Start simulation**
3. Watch the pipeline stages light up as the agent works:
   - `CHECK_SERVER_HEALTH` → **ALLOWED**, anomaly 0.00, risk 10
   - `MODIFY_PERMISSION` → **BLOCKED**, anomaly 0.97, risk 100 — privilege escalation
   - `EXPORT_DATA` → **BLOCKED**, anomaly 0.95, risk 100 — attempted exfiltration
   - `DELETE_DATABASE` → **BLOCKED**, agent **STOPPED** — irreversible, so the agent halts
4. Expand the `DELETE_DATABASE` row — show the risk factor bars, the six policy violations,
   and the generated explanation
5. Point at **Simulated environment**: `db/primary` is still `HEALTHY` — the block landed
   *before* execution
6. Watch recovery run automatically: restoration → verification → **RECOVERY VERIFIED**
7. Open **Audit Trail** → filter by `ACTION BLOCKED` → the complete evidence chain

For the human-in-the-loop story, run the **Human Approval** scenario and approve or reject
`FAILOVER_DATABASE` on the Human Approval page.

## Scenarios

| Scenario | Sequence | Expected outcome |
|---|---|---|
| **Normal Operation** | health → status → log → temp → ticket | All allowed, risk LOW, agent healthy |
| **Abnormal Behaviour** | health → log → unauthorised file → sensitive data → export | Deviation detected, reads blocked, agent SUSPICIOUS then PAUSED by the repeat-offender rule |
| **Critical Misbehaviour** | health → permission → export → delete DB | CRITICAL, destructive action blocked pre-execution, agent stopped, incident, auto-recovery, verification |
| **Human Approval** | health → status → failover DB | Held pending a human decision; approve or reject, both audited |

## API documentation

Interactive docs at **http://127.0.0.1:8000/docs**.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Service + model status |
| GET | `/api/agents` | Agents with current task/action |
| POST | `/api/agents/start` | Start an agent on a scenario |
| GET | `/api/scenarios` | Available demo scenarios |
| POST | `/api/simulations/start` | Start a simulation run |
| GET | `/api/simulations/{id}` | Full session detail |
| GET | `/api/sessions` | Recent sessions |
| GET | `/api/actions` | Actions (filter by session/risk/status) |
| POST | `/api/actions/evaluate` | Push one action through the pipeline |
| GET | `/api/catalog` | Action catalog with metadata |
| GET | `/api/incidents` | Incidents (filter by status/severity) |
| GET | `/api/incidents/{id}` | Timeline, factors, explanation, recovery |
| POST | `/api/incidents/{id}/recover` | Run recovery + verification |
| GET | `/api/pending-approvals` | Actions awaiting a human |
| GET | `/api/approvals` | All approval records |
| POST | `/api/approvals/{id}/approve` | Approve (409 if already decided) |
| POST | `/api/approvals/{id}/reject` | Reject (409 if already decided) |
| GET | `/api/audit` | Audit trail with filters |
| GET | `/api/audit/event-types` | Event vocabulary |
| GET | `/api/metrics` | Dashboard metrics |
| GET | `/api/environment` | Sandbox state + verification |
| GET | `/api/ml/status` | Model status + evaluation report |
| GET | `/api/policy` | Active policy document |
| WS | `/ws/events` | Live event stream |

**WebSocket event types:** `connected`, `simulation_started`, `action`, `incident`,
`recovery`, `agent_status`, `approval_requested`, `approval_decided`,
`simulation_finished`, `audit`, `error`.

## Database schema

SQLite, created automatically on first run.

| Table | Purpose |
|---|---|
| `agents` | Registered agents and their live status |
| `sessions` | One scenario run |
| `tasks` | The task assigned for a session |
| `actions` | Every attempted action + scores, decision, explanation |
| `risk_assessments` | Immutable per-action risk record |
| `interventions` | Enforcement decision and resulting agent state |
| `incidents` | HIGH/CRITICAL events, one per session, escalated in place |
| `approvals` | Human-in-the-loop requests and decisions |
| `recovery_events` | Rollback and verification steps |
| `audit_events` | Append-only evidence trail |
| `simulated_resources` | The sandboxed world and its known-good baseline |

## Project structure

```
backend/
  app/
    main.py                  FastAPI app, WebSocket, error handling
    config.py                Environment configuration
    api/routes.py            All REST endpoints
    agent/
      catalog.py             Action catalog — single source of truth
      scenarios.py           The four demo scenarios
    database/
      db.py  models.py  seed.py
    schemas/api.py           Pydantic request models
    policies/agent_policy.json
    services/
      pipeline.py            THE safety pipeline
      ml_detector.py         Model loading + calibrated scoring
      policy_engine.py       Deterministic guardrails
      risk_engine.py         0–100 weighted risk
      explanation.py         Factor-derived explanations
      recovery.py            Rollback + verification
      sandbox.py             The simulated world
      simulator.py           The autonomous agent
      audit.py  events.py  metrics.py
  ml/
    features.py              Shared feature extraction
    generate_dataset.py      Synthetic data generator
    train_model.py           Training + evaluation
    models/  data/
  tests/
    test_pipeline.py         Pipeline, policy, recovery, audit
    test_api.py              API surface + end-to-end flows
frontend/
  src/
    pages/                   Landing, Dashboard, Lab, Monitor, Incidents,
                             IncidentDetail, Approvals, Audit, ModelEvaluation
    components/              Layout, ui primitives, ActionStream
    hooks/                   useApi, useEvents (WebSocket)
    services/api.ts          Typed API client
    types/                   Shared TypeScript types
scripts/                     setup.sh, setup.ps1
```

## Testing

```bash
python -m pytest backend/tests -v
```

29 tests covering: model loading, normal/suspicious/critical scoring, risk not equalling
anomaly, policy violation specificity, explanation uniqueness, block-vs-halt distinction,
the repeat-offender rule, human approval, duplicate-decision rejection, recovery,
verification failure honesty, audit completeness, WebSocket delivery, error handling
(unknown scenario, malformed payload, missing incident, unknown action type), and that
dashboard metrics agree with the underlying records.

Frontend type checking and build:

```bash
cd frontend
npm run typecheck
npm run build
```

## Screenshots

Add captures here for submission:

- `docs/landing.png` — landing page
- `docs/lab-critical.png` — Simulation Lab mid-run, `DELETE_DATABASE` blocked
- `docs/incident-detail.png` — risk factor breakdown and explanation
- `docs/recovery.png` — recovery verified
- `docs/audit.png` — filtered audit trail
- `docs/model.png` — model evaluation

## Limitations & future work

**Known limitations, stated plainly:**

- The dataset is synthetic and generated from a hand-written behavioural model. Results
  demonstrate that the pipeline works; they do not generalise to real agent telemetry.
- Isolation Forest treats each action largely independently; sequence information enters only
  through hand-engineered features, not a sequence model.
- One agent, one policy, one sandbox. Multi-agent interaction is not modelled.
- Recovery is a full rollback to baseline, not a targeted, partial repair.

**Future extensions:**

- LLM-based reasoning-trace analysis (inspect *why* the agent chose an action, not just what)
- Sequence models (HMM / LSTM / transformer) for genuine behavioural-chain detection
- Graph-based analysis of agent–resource interaction
- Multi-agent monitoring and cross-agent correlation
- Policy learning from operator approve/reject decisions
- Real Kubernetes and cloud IAM integration for a non-simulated deployment
- Zero-trust agent architecture with per-action capability tokens
- Federated learning across deployments; model behaviour fingerprinting
- Reinforcement learning for adaptive thresholds

---

*Agent Sentinel is a hackathon prototype and a controlled safety simulation. No real systems
are affected by anything it does.*
