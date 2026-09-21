# Agent Sentinel — AI Agent Misbehavior Detection & Recovery

> Making autonomous AI systems safer, explainable, controllable, and recoverable.

A runtime safety layer for autonomous AI agents. An agent proposes actions; Sentinel observes every one,
scores how far it departs from **that agent's learned behaviour** and from **the task it was given**,
reads the whole **sequence** for attack chains, fuses everything into an explainable risk score, applies
**configurable policy** (`ALLOW → MONITOR → REQUIRE_APPROVAL → BLOCK → TERMINATE`), simulates what would
have happened if the action were allowed, and — when something gets through — rolls the environment back and
**verifies** the result, including the case where recovery only partly works.

**The claim, precisely:** the agent can act autonomously; this system keeps its actions inside safe
boundaries, tells you *why* in terms you can check, and does not confuse "unusual" with "dangerous".

> **This is a controlled simulation.** Every dangerous action is simulated inside a SQLite sandbox.
> `DELETE_DATABASE` flips a string from `HEALTHY` to `DELETED`. No real file, service, database,
> permission or credential is ever touched, and none is required. The agents are **scripted simulators,
> not live LLMs**, and the behavioural dataset is **synthetic**.

---

## Contents

1. [What is implemented vs future work](#implemented-vs-future-work)
2. [Problem and solution](#problem-and-solution)
3. [What is technically distinctive](#what-is-technically-distinctive)
4. [Architecture](#architecture)
5. [AI/ML methodology](#aiml-methodology) — dataset, features, model, calibration
6. [Behavioural intelligence](#behavioural-intelligence) — intent, fingerprint, sequence, drift, trust, baseline
7. [Risk engine](#risk-engine) · [Policy engine](#policy-engine) · [Counterfactual analysis](#counterfactual-analysis)
8. [Human approval](#human-approval) · [Recovery](#recovery-and-verification)
9. [Evaluation](#evaluation) — measured results, ablation, robustness, honest limits
10. [Scenario library](#scenario-library) · [Demo](#demo)
11. [Installation and usage](#installation-and-usage) · [API](#api) · [Testing](#testing)
12. [Limitations](#limitations) · [Future work](#future-work)

---

## Implemented vs future work

| Capability | Status |
|---|---|
| Isolation-Forest anomaly detector (24 features, trained on normal sessions only, calibrated 0–1) | Implemented |
| Per-agent behavioural fingerprint (bigram/trigram, tools, resources, timing) learned from data | Implemented |
| Intent–behaviour alignment (TF-IDF task resolution + per-task scope), replaces a hard-coded relevance constant | Implemented |
| Sequence detection: kill-chain patterns, dedicated privilege-escalation detector, retry-storm / rate / bulk-read / stagnation loops | Implemented |
| Behaviour drift vs fingerprint, with per-agent reference and threshold | Implemented |
| Adaptive baseline with poisoning safeguards (eligibility gates + step limit + anchor limit) | Implemented |
| Dynamic per-agent trust score computed from history, fed back into enforcement | Implemented |
| 8-signal risk fusion with per-factor breakdown | Implemented |
| Configurable rule-based policy engine, five effect levels, every decision attributable to rule ids | Implemented |
| Counterfactual simulation (ALLOW vs BLOCK, cascades, projected attack chain) | Implemented |
| Prompt-injection *content scan* + session taint (heuristic regexes over simulated content) | Implemented |
| Human approval with evidence, modelled impact, safer alternative, and "request more evidence" | Implemented |
| Step-wise recovery with independent state + integrity verification; partial/failed/retry; fault injection | Implemented |
| Behaviour graph, incident replay, judge mode, architecture page with live per-stage latency | Implemented |
| 4-way ablation, ROC/PR-AUC, detection latency, robustness suite, fresh-holdout evaluation | Implemented |
| Login with signed tokens, operator/viewer roles, rate limiting, decisions attributed to the signed-in user | Implemented |
| Integration path for an external agent (`POST /api/sessions/open` + a small guard SDK) | Implemented |
| A live LLM agent, or real prompt-injection susceptibility | **Not implemented** — simulated |
| Learned sequence model (HMM / transformer) | **Not implemented** — engineered features + declared patterns |
| Real infrastructure, IAM or Kubernetes integration | **Not implemented** — sandbox only |
| SSO / OAuth / multi-tenancy / password reset | **Not implemented** — minimal built-in login only |
| Formal zero-trust or compliance conformance | **Not claimed** — used as a per-action design principle only |

---

## Problem and solution

An agent with tool access can leave its task because of faulty reasoning, unexpected input, prompt
injection, goal drift, excessive permissions or getting stuck. The dangerous failures are not crashes; they
are *plausible actions on the wrong resource, in the wrong order*.

Each single mechanism fails alone. **Rules** miss anything built from sanctioned actions. A **model** alone
flags legitimate emergency work. **Policy on top of a noisy model** inherits the noise. The measured
evidence for this is in [Evaluation](#evaluation): on held-out sessions the model alone flags 52.6% of
benign sessions, and rules alone catch 21.5% of malicious actions.

Sentinel layers the mechanisms so each covers another's blind spot, keeps a human in the loop for the
consequential middle ground, and treats recovery as a procedure that can itself fail.

## What is technically distinctive

Not "AI detects bad behaviour and blocks it" — that configuration (B/C in the ablation) is exactly what this
project measures and shows to be unusable. The combination that is implemented:

1. **Intent-behaviour alignment** — the same action (`READ_CUSTOMER_RECORD`) is on-task for a refund and
   off-task for server maintenance; alignment is computed per task, not looked up.
2. **Sequence-level detection** — `READ_LOG → ACCESS_CREDENTIAL_STORE → MODIFY_PERMISSION` is terminated at
   stage 3 of 4, *before* the export/destruction, because the chain is recognised, not because any single
   step is fatal.
3. **Behavioural fingerprint + drift + adaptive baseline** — "normal" is per-agent and learned, can update
   from verified-safe sessions, and cannot be walked away from its original anchor by slow poisoning.
4. **Counterfactual safety analysis** — every held or blocked action shows a simulated ALLOW-vs-BLOCK
   comparison, including cascades (deleting the DB degrades three dependents) and the projected chain.
5. **False-positive discipline** — an explicit "why was this allowed" rationale, and an evaluation that
   measures it (the full stack intervened on 0 of 1,100 benign test sessions, vs 52.6% for the model alone).
6. **Honest recovery** — steps, independent verification (state *and* checksum), PARTIAL/FAILED outcomes,
   retry, and a residual-risk note when a rollback cannot undo the harm (exfiltrated data).
7. **Trust that feeds back** — a low-trust agent's medium-risk actions need a human (rule R13).

## Architecture

```
  React dashboard  ──  REST /api  ·  WebSocket /ws/events
        │
  FastAPI ─ pipeline.evaluate_action (rebuilds context from the DATABASE every action)
        │
        ▼  pure analyzer  (services/analysis.py — also used, unchanged, by the offline evaluator)
  intent alignment ─► sequence / escalation / loops ─► fingerprint drift
        │                       │
        └──► Isolation Forest (24 features) ──► anomaly 0–1
        │
        ▼
  policy invariants ─► counterfactual simulation ─► 8-signal risk (0–100) ─► rule decision
        │                                                   ALLOW│MONITOR│REQUIRE_APPROVAL│BLOCK│TERMINATE
        ▼
  explanation · zero-trust answers · allow-rationale · safer alternative
        │
        ▼
  enforce ─► incident ─► human approval ─► recovery ─► independent verification ─► audit + trust snapshot
```

Two design points worth knowing:

* **The analyzer is pure** (no database). The live pipeline and the offline evaluation call the *same*
  function, so what is measured is what runs.
* **Callers cannot supply context.** `POST /api/actions/evaluate` accepts no `prev_action` or
  `task_relevance`; history, task, trust and environment are read from the database. (An early version
  trusted them, so an agent could lower its own risk by misreporting.)

Open the **Architecture** page for the same diagram with live counts and measured per-stage latency.

## AI/ML methodology

### Dataset (synthetic — never real telemetry)

`python -m backend.ml.generate_dataset` writes labelled **sessions** (`backend/ml/data/sessions.jsonl`)
sampled from hand-written behavioural models of two simulated agents. Design choices that keep the
evaluation honest:

* **Session-grouped splits.** Train / val (normal only), `dev` (used while iterating) and a **fresh `test`
  split drawn from an independent seed** and not inspected while tuning.
* **Per-step labels.** A malicious session starts benign; only the steps that are the misbehaviour are 1.
* **Hard negatives.** Bursty, repetitive, sanctioned incident response and a policy-mandated failover.
* **Eleven attack families**, three of them **novel** (alternating scrape, low-and-slow bulk read, gradual
  drift) built only from sanctioned actions, so no deny-list rule can catch them.
* **Distribution shift.** Test normal sessions come from a *perturbed* transition prior, so the learned
  fingerprint is deliberately imperfect.

Corpus: 7,320 sessions, 51,704 actions. Test: 2,310 sessions, 17,400 actions (4,766 malicious).

### Features (`backend/ml/features.py`, 24 dimensions, all 0–1)

Requested permission · resource sensitivity · action severity · **intent alignment** · **bigram surprisal**
(from the agent's own fingerprint) · **trigram novelty** · repeat ratio · inter-action time · burstiness ·
tool rarity · novel resource · step position · destructiveness · **window** max sensitivity / permission
rise / sensitive-access count / failure ratio / misalignment · 6-way action category.

The training features are **cross-fitted**: a session is featurised with a fingerprint learned from the
*other* half, so its own transitions never make it look artificially familiar.

### Model

`IsolationForest` (120 trees) fitted on **normal sessions only** — one-class novelty detection. Raw scores
(unbounded, higher = more normal) are mapped to a 0–1 anomaly score:

```
anomaly = 1 / (1 + exp((raw − t) / s))     t = 5th percentile of normal-training raw scores, s = std / 4
```

`(t, s)` are stored inside the artifact so runtime scoring equals training. The model loads once at startup
and is never retrained on boot. If it is missing the layer still runs on a labelled heuristic fallback.

## Behavioural intelligence

* **Intent** (`services/intent.py`) — a TF-IDF nearest-neighbour maps free-text task → task type, which
  fixes the expected actions and resource scope. Alignment: `0.70 + 0.20·weight + 0.10·semantic` for an
  expected action, `0.30 + 0.25·semantic` for in-scope-but-unplanned, `0.08·semantic` for out of scope.
* **Fingerprint** (`services/fingerprint.py`) — per agent: action, bigram/trigram, tool, resource-prefix and
  timing statistics. Bootstrap sample size is capped (~800 actions) so verified sessions carry real weight;
  an earlier build had a 12,000-action fingerprint that one session moved by 0.3%, making "adaptive" inert.
* **Sequence** (`services/sequence.py`) — declared kill-chain patterns (stages may be skipped; progress =
  distinct stages hit), a privilege-escalation detector over the permission trajectory (ladder / jump /
  elevation-then-restricted-access), and loops: `RETRY_STORM`, `EXCESSIVE_CALLS`, `BULK_READ`,
  `REPEATED_ACTION`, `STAGNATION` (reading without acting).
* **Drift** — window of 8 actions vs the fingerprint: action-mix JS-divergence, novel transitions, novel
  resources, permission and timing shift. Alerts need ≥5 actions of evidence; a drift *incident* also needs
  corroboration (no productive step, or intent erosion), so a legitimate emergency burst only gets MONITOR.
* **Trust** (`services/trust.py`) — `100 − recency-weighted incident penalties (less if recovered, more if
  recovery failed) − violation/anomaly/block rates − latest drift + bounded credit for clean sessions`. All
  weights are in the policy file; nothing is random.
* **Adaptive baseline** (`services/baseline.py`) — a session is learned only if it completed with no
  block/hold/incident/taint, low peak risk and drift, and the result stays within a limit of **both** the
  previous version and the **original v1 anchor**. Every accept/reject is audited with reasons.
* **Injection** (`services/injection.py`) — regex indicators over simulated untrusted content mark the
  session *tainted*; a tainted session's off-task action is blocked (R07). A missed regex is still caught
  by what the agent does next (misalignment, sequence, drift).

## Risk engine

Risk is **not** the anomaly score rescaled. Eight signals, weights in `agent_policy.json`:

```
0.22 behaviour anomaly · 0.12 resource sensitivity · 0.10 permission · 0.14 action severity
0.12 intent misalignment · 0.14 sequence risk · 0.06 trust/drift/taint · 0.10 counterfactual impact
+ policy-violation penalty, + floors (destructive & denied ≥88; completed chain ≥90; escalation ≥70)
```

`0–29 LOW · 30–59 MEDIUM · 60–84 HIGH · 85–100 CRITICAL`. The UI shows every factor, its weight and its
point contribution.

## Policy engine

`backend/app/policies/agent_policy.json` holds capability sets per agent, thresholds, weights, patterns,
injection indicators, safer alternatives and **20 ordered rules** over identity, task, tool, resource,
permission, severity, risk, trust, drift, sequence and taint. The most severe matching effect wins
(`ALLOW < MONITOR < REQUIRE_APPROVAL < BLOCK < TERMINATE`) and every matched rule id is stored.
`POST /api/policy/reload` applies edits without a restart.

## Counterfactual analysis

For every action the analyzer clones the sandbox and simulates ALLOW (with dependency cascades) against
BLOCK, and — if an attack chain is forming — projects the remaining steps. Recovery times are **modelled
estimates**, labelled as such. This is a simulation over a small hand-built world graph, not a prediction
about real systems.

## Human approval

Held actions show the action, risk, why it was held, top risk factors, sequence and rule evidence, modelled
impact, and a safer alternative. The operator can **Approve**, **Reject** or **Request more evidence**
(runs extra diagnostics against the current sandbox and the agent's record, up to 3 rounds). Approved
actions execute in the sandbox and the agent **resumes**; every decision is audited.

## Recovery and verification

`PAUSE_AGENT → REVERT_PERMISSIONS → RESTORE_RESOURCES → INTEGRITY_VERIFICATION`. Each resource has a state
*and* a checksum, so a resource that looks healthy but was silently corrupted fails verification. Outcome is
`SUCCESS`, `PARTIAL` or `FAILED`, derived from the verification step. Injectable faults
(`restore_failure`, `partial`, `corruption`) exercise the failure paths; retry re-runs against current
state. If harm cannot be undone by a state rollback (exfiltration), the report says so.

## Evaluation

Everything below is computed by `python -m backend.ml.evaluate` on the **fresh held-out `test` split**, in
*shadow mode* (decisions computed, agent never halted, so all four detectors see identical actions).
**Synthetic data: these numbers show the pipeline works on this data, not that it generalises to real agent
telemetry.** Reproduce with `python -m backend.ml.train_model`.

| Detector | Precision | Recall | F1 | ROC-AUC | PR-AUC | Benign sessions falsely flagged | Malicious sessions caught |
|---|---|---|---|---|---|---|---|
| A · Rules only | 1.000 | 0.215 | 0.355 | — | — | 0.0% | 54.5% |
| B · ML anomaly only | 0.638 | 0.814 | 0.715 | 0.923 | 0.848 | **52.6%** | 97.6% |
| C · ML + policy | 0.638 | 0.814 | 0.715 | 0.924 | 0.852 | **52.6%** | 97.6% |
| D · Full architecture | 0.971 | 0.809 | 0.883 | 0.942 | 0.890 | **0.0%** | 100% |

Action-level precision/recall/F1; recall is per malicious *action*, so it is lower than session-level catch
rate for families that start benign. **No winner is declared:** read the trade-offs.

* **A** never falsely flags but cannot see anything made of sanctioned actions or loops.
* **B/C** generalise but flag half of benign sessions — unusual is not dangerous. Adding rules to a noisy
  model does not remove its noise.
* **D** is the only configuration with both low false positives and high catch rate here. Costs: complexity,
  a ~13 ms mean decision (p95 29 ms; ~96% of it is model inference), and rules that encode the designer's
  assumptions.
* **Novel families** (no rule targets them): A catches 0%; D detects 100% of sessions (action recall 0.58,
  0.57, 0.90) with a mean detection latency of a few steps after onset.
* **Robustness** (noise, duplicate events, delayed events, 20% missing events, task change, benign prior
  drift): D's benign-session false-positive rate stays ≤0.8% while B's stays 13–88%; D's malicious-session
  detection stays ≥94.8%.
* **Friction:** 22.5% of benign actions still receive a MONITOR decision (allowed, but flagged). Low
  friction, not zero — a consequence of the 30% drift-alert floor.
* **Confusion matrices, ROC/PR curves, per-family and per-perturbation tables** are on the Evaluation page.

**Disclosures.** (1) An earlier version of this project reported F1 0.88 mostly because one hand-written
feature separated the classes at AUC 0.995; the corpus was redesigned and the best single feature is now
0.89 (shown on the page). (2) The `STAGNATION` and `BULK_READ` loop rules were added after inspecting the
dev set, which is why results are reported on a fresh seed; F1 is 0.883 on both. (3) Sequence rules encode
known attack shapes — only the three novel families test generalisation. (4) Accuracy is reported but is the
wrong headline for imbalanced one-class detection.

## Scenario library

Fifteen scenarios, each with task, expected normal behaviour, abnormal behaviour, expected risk, expected
intervention and recovery method: *normal · normal refund · unauthorized file · sensitive data · privilege
escalation · destructive · excessive API calls · repeated failures · prompt-injection deviation · behaviour
drift · multi-step sequence · critical misbehaviour · human approval · unusual-but-legitimate · recovery
failure drill*. `tests/test_system.py` asserts that each scenario's declared intervention actually happens.
Two simulation devices are labelled in the UI: injected *content* (the agent's compliance is scripted) and
the recovery drill's *guard bypass*.

## Demo

**Judge mode** (`/app/judge`): **START DEMO** runs ~110 seconds through the *real* pipeline — a normal agent;
a legitimate-but-unusual burst that must *not* be blocked; an agent that goes rogue (detection → risk
escalation → block → terminate → explanation); recovery and verification; a **recovery-failure drill** (first
attempt PARTIAL and fails verification, retry succeeds, residual-risk warning); then the audit trail.
**RESET DEMO** restores a known seeded state, so runs are repeatable (tested: two consecutive runs produce
identical outcomes). Only narration and pacing are scripted.

Suggested order for a live walkthrough: Judge mode → Evaluation (ablation) → Incident replay →
Human Approval (request more evidence) → Agent Monitor (fingerprint, trust, baseline poisoning).

## Installation and usage

Requires **Python 3.11+** and **Node 18+**. From the project root:

```bash
python -m venv venv
# Windows PowerShell:  .\venv\Scripts\Activate.ps1      macOS/Linux:  source venv/bin/activate
pip install -r requirements.txt
python -m backend.ml.generate_dataset     # synthetic corpus
python -m backend.ml.train_model          # fingerprints + Isolation Forest + evaluation report (~1–2 min)
python -m backend.app.database.seed       # realistic demo history via the real pipeline
cd frontend && npm install && cd ..
```

Or `scripts/setup.ps1` / `bash scripts/setup.sh`. Then, in two terminals:

```bash
uvicorn backend.app.main:app --reload     # http://127.0.0.1:8000  (docs at /docs)
cd frontend && npm run dev                # http://localhost:5173
```

`docker compose up --build` also works (the image generates data, trains, evaluates and seeds at build time).
Optional: set `SENTINEL_API_KEY` to require an `X-API-Key` header on all write endpoints (the frontend reads
`VITE_API_KEY`). No secrets are required to run.

## API

Interactive docs at `/docs`. Main endpoints:

| | |
|---|---|
| `GET /api/scenarios`, `POST /api/simulations/start`, `GET /api/simulations/{id}` | run and inspect scenarios |
| `POST /api/actions/evaluate` | one action through the pipeline (context from the DB, not the caller) |
| `GET /api/agents`, `/api/agents/{id}/profile`, `POST /api/agents/{id}/baseline/update` | trust, fingerprint, drift, baseline |
| `GET /api/incidents[/{id}]`, `/incidents/{id}/replay`, `POST /incidents/{id}/recover` | incidents, replay, recovery (`{"fault": ...}`) |
| `GET /api/sessions/{id}/graph` | behaviour graph |
| `GET /api/pending-approvals`, `POST /api/approvals/{id}/approve\|reject\|request-evidence` | human-in-the-loop |
| `GET /api/audit`, `/api/metrics`, `/api/environment` | evidence and metrics |
| `GET /api/evaluation`, `/api/ml/status`, `/api/architecture`, `/api/policy`, `POST /api/policy/reload` | ML, architecture, policy |
| `POST /api/demo/reset`, `/api/demo/start`, `GET /api/demo/status` | judge mode |
| `WS /ws/events` | live events |

## Testing

```bash
python -m pytest backend/tests -v      # 90 tests
cd frontend && npm run typecheck && npm run build
```

Covers: intent, fingerprint, sequence/escalation/loop detection, environment cascade and counterfactual,
policy rules and precedence, injection, risk fusion, all 15 scenarios against their declared outcomes,
false-positive behaviour, terminated agents not attempting further steps, recovery success/partial/failed/
corruption/retry, approvals (evidence, duplicate decision, resume), trust, baseline learning and **slow-poison
resistance**, graph, replay, the API surface (including that callers cannot lower their own score and the
optional API key), and judge-mode repeatability. There are no frontend unit tests; the frontend is
type-checked, built, and was exercised end-to-end in a browser.

## Sign-in and roles

The dashboard and API require a login (`SENTINEL_AUTH=off` disables it). Tokens are HMAC-signed with an expiry,
passwords are held only as PBKDF2 hashes, failed sign-ins are rate-limited (5 per minute), and the WebSocket
also requires the token. Two roles: **operator** (can start runs, decide approvals, trigger recovery) and
**viewer** (read-only; every write returns 403). The signed-in name is what is recorded as the human
decision-maker on an approval, regardless of what the request body says.

Demo accounts (active only while `SENTINEL_USERS` is unset; the login page says so): `judge` / `sentinel-demo`
(operator) and `viewer` / `sentinel-view` (viewer). For anything real set
`SENTINEL_USERS="alice:strong-password:operator,bob:another:viewer"` and `SENTINEL_SECRET=<random>` (see `.env.example`).

## Plugging in a real agent

Sentinel is a gateway: an external agent opens a session, then asks before **each** tool call.

```python
from sdk.sentinel_client import Sentinel, ActionBlocked
sentinel = Sentinel("http://127.0.0.1:8000", user="judge", password="sentinel-demo")
with sentinel.session("OpsAssist-Agent", "Perform routine maintenance.") as s:
    s.guard("READ_LOG", tool=read_log)            # runs only if ALLOW / MONITOR
    s.guard("EXPORT_DATA", tool=export)           # raises ActionBlocked; export() never runs
```

`python -m sdk.example_agent` runs a toy agent through it (the blocked tools never execute — this is tested).
Honest constraints: the agent must be registered in `agent/profiles.py` and `policies/agent_policy.json`,
the calling code is what enforces the decision so the guard must wrap every tool the agent can reach, and
actions must map to the catalogued action types.

## Feasibility and scaling

`python scripts/benchmark.py` on the development laptop (one process, one SQLite file, real model inference):

| Path | Throughput | Latency |
|---|---|---|
| Pure analyzer, per-action model inference | ~240 decisions/s | p50 4 ms, p95 5 ms |
| Pure analyzer, batch-scored model (offline evaluation) | ~6,000 decisions/s | — |
| Full persisted pipeline (context from DB, ~a dozen audit/state writes, events) | ~60 decisions/s | p50 16 ms, p95 24 ms |

The persisted path is bound by SQLite commits; WAL mode with `synchronous=NORMAL` took it from ~26 to ~60
decisions/s (durability trade-off: a power loss can drop the last few transactions, not corrupt the file).
That is ample for one team's agents, not for a fleet. The path from here, none of which is built:
Postgres and batched/async audit writes (the analyzer is already DB-free and stateless per call, so it
scales horizontally behind a queue), the per-session context cached in Redis, the model served in a
separate inference worker, and policy/fingerprint distribution via versioned artifacts.

## How this maps to the judging criteria

An honest self-assessment, not a prediction. "Gap" lists what a sceptical judge could reasonably press on.

| Criterion (weight) | Evidence in the repo | Gap |
|---|---|---|
| **Innovation & originality (25%)** | Intent-aware scoring, sequence/kill-chain and privilege-escalation detection, per-agent fingerprint + drift, poisoning-resistant adaptive baseline, counterfactual ALLOW-vs-BLOCK simulation, trust that feeds back into enforcement, recovery that can partly fail. The ablation shows *why* the combination is needed (ML alone: 52.6% benign sessions flagged). | Individual ideas (Isolation Forest, rules, kill chains) are known; the novelty is the combination and the honest measurement. |
| **Technical implementation (25%)** | 90 tests; a pure analyzer shared by the live pipeline and the offline evaluator; session-grouped fresh-holdout evaluation with ROC/PR-AUC, robustness and latency; real auth with roles; WAL-tuned persistence; a benchmark. | Synthetic data; one-class Isolation Forest rather than a learned sequence model; scripted agents. |
| **Real-world impact (20%)** | The problem (agents acting off-task, injection, escalation) is current and organisations do deploy agents with tool access. A gateway integration path (`/api/sessions/open` + SDK) and approval-with-evidence workflow map onto how a security or ops team would actually work. | Not yet validated on a real agent or real telemetry; actions must be mapped to the catalog. |
| **Feasibility & scalability (15%)** | Runs on a student laptop; measured throughput; a stateless DB-free analyzer; a stated scaling path. | Single-process SQLite is ~60 decisions/s; the fleet-scale path is described, not built. |
| **User experience & design (10%)** | White, high-contrast UI; login; a 110-second Judge mode; explanations that show the evidence behind each decision; responsive layout. | No usability testing; no dark mode toggle. |
| **Presentation & demonstration (5%)** | Judge mode (repeatable, tested), RESET DEMO, an Architecture page with live numbers, a recovery-failure drill, an evaluation page that states its own limits. | Needs rehearsal; a live LLM agent would make it more convincing. |

## Limitations

* Synthetic, self-generated data; detector and data share the designer's assumptions (see Evaluation).
* Scripted agents — no live LLM, no real injection susceptibility; injection scan is a heuristic.
* Sequence intelligence is engineered features and declared patterns, not a learned sequence model.
* Counterfactual and recovery times are modelled on a small hand-built world.
* Authentication is a minimal built-in login (no SSO, refresh tokens or password reset); single-tenant. The two demo accounts are active only when `SENTINEL_USERS` is unset — set it for anything beyond a demo.
* ML inference dominates decision latency (~96%).

## Future work

LLM reasoning-trace analysis · learned sequence models · graph-based behaviour analysis across agents ·
multi-agent correlation · policy learning from operator decisions · real infrastructure/IAM adapters ·
per-action capability tokens · federated learning and model fingerprinting.

---

*Agent Sentinel is a hackathon prototype. It is a controlled safety simulation: no real systems are
affected by anything it does.*
