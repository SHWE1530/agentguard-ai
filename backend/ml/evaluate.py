"""Offline evaluation of the detection stack -- every number is computed here.

Runs the SAME analyzer used in production (services/analysis.py) over the
held-out TEST sessions in SHADOW MODE (decisions are computed but the agent is
never halted, so all four detectors see identical actions).

Detectors compared (same data, same threshold policy):
  A  rule-based only      capability set + deny-list + task scope + privilege ceiling
  B  ML only              calibrated Isolation-Forest anomaly >= threshold
  C  ML + policy          A or B
  D  full architecture    ML + policy + intent + sequence + drift + counterfactual
                          + multi-layer risk + rule engine  (BLOCK / TERMINATE, or
                          a risk-driven approval request)

Also reported: ROC-AUC / PR-AUC, confusion matrices, per-family recall, detection
latency (steps from first malicious action to first flag), live intervention
latency (ms), robustness under noise / duplicates / delays / missing events /
task changes / benign drift, and how separable the data is by ONE feature.

Usage:  python -m backend.ml.evaluate
"""
from __future__ import annotations

import json
import os
import random
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve

from backend.app.agent.profiles import AGENTS, TASK_TYPES
from backend.app.config import EVALUATION_PATH
from backend.app.services.analysis import analyze
from backend.app.services.ml_detector import detector
from backend.ml.features import FEATURE_NAMES
from backend.ml.generate_dataset import NOVEL_FAMILIES, TASK_TEXT, load, normal_steps
from backend.ml.replay import new_context, session_features

DETECTORS = ["A_rules", "B_ml", "C_ml_policy", "D_full"]
DET_LABEL = {"A_rules": "A · Rule-based only", "B_ml": "B · ML anomaly only",
             "C_ml_policy": "C · ML + policy", "D_full": "D · ML + policy + sequence + intent + risk"}


# ------------------------------------------------------------------ metrics
def prf(tp: int, fp: int, tn: int, fn: int) -> Dict[str, Any]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "accuracy": round((tp + tn) / max(1, tp + fp + tn + fn), 4),
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
            "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
            "balanced_accuracy": round(0.5 * ((tp / (tp + fn) if tp + fn else 0) + (tn / (tn + fp) if tn + fp else 0)), 4)}


def _downsample(xs, ys, n=60):
    if len(xs) <= n:
        return [[round(float(a), 4), round(float(b), 4)] for a, b in zip(xs, ys)]
    idx = np.linspace(0, len(xs) - 1, n).astype(int)
    return [[round(float(xs[i]), 4), round(float(ys[i]), 4)] for i in idx]


# ------------------------------------------------------------------- replay
def fingerprints() -> Dict[str, Any]:
    return {a: detector.bootstrap_fingerprint(a) for a in AGENTS}


def flag_set(a, thr: float) -> Dict[str, bool]:
    viol = set(a.policy.violations)
    A = (not a.policy.allowed) or a.policy.always_block or bool(viol & {"RESOURCE_OUTSIDE_TASK_SCOPE", "PERMISSION_CEILING_EXCEEDED"})
    B = a.anomaly >= thr
    D = a.decision in ("BLOCK", "TERMINATE") or (a.decision == "REQUIRE_APPROVAL" and not a.policy.needs_approval)
    return {"A_rules": A, "B_ml": B, "C_ml_policy": A or B, "D_full": D}


def replay(sessions: List[Dict[str, Any]], fps: Dict[str, Any], thr: float) -> List[Dict[str, Any]]:
    """Batch-score anomalies once, then run the full analyzer per action."""
    X: List[List[float]] = []
    for s in sessions:
        rows, _ = session_features(s, fps[s["agent"]])
        X.extend(rows)
    anomalies = detector.score_matrix(np.array(X)) if X else np.array([])
    out: List[Dict[str, Any]] = []
    k = 0
    for s in sessions:
        ctx = new_context(s, fps[s["agent"]])
        rec = {"id": s["id"], "family": s["family"], "label": s["label"], "steps": []}
        for st in s["steps"]:
            a = analyze(ctx, st["a"], st["dt"], st["f"], st.get("c"), anomaly_override=float(anomalies[k]))
            k += 1
            ctx.commit(a, executed=a.decision in ("ALLOW", "MONITOR"))
            fl = flag_set(a, thr)
            rec["steps"].append({
                "m": st["m"], "anomaly": a.anomaly, "risk": a.risk.risk_score, "decision": a.decision,
                "flags": fl,
                "feat": [a.features[n] for n in FEATURE_NAMES],
            })
        out.append(rec)
    return out


def _scores(recs, det: str):
    y, sc = [], []
    for r in recs:
        for s in r["steps"]:
            y.append(s["m"])
            if det == "B_ml":
                sc.append(s["anomaly"])
            elif det == "C_ml_policy":
                sc.append(max(s["anomaly"], 1.0 if s["flags"]["A_rules"] else 0.0))
            elif det == "D_full":
                sc.append(s["risk"] / 100.0)
            else:
                sc.append(1.0 if s["flags"]["A_rules"] else 0.0)
    return np.array(y), np.array(sc)


def detector_metrics(recs, det: str, with_curves: bool = True) -> Dict[str, Any]:
    tp = fp = tn = fn = 0
    for r in recs:
        for s in r["steps"]:
            f, m = s["flags"][det], s["m"]
            if f and m:
                tp += 1
            elif f and not m:
                fp += 1
            elif m:
                fn += 1
            else:
                tn += 1
    res: Dict[str, Any] = {"action_level": prf(tp, fp, tn, fn)}
    bfp = btn = 0
    for r in recs:
        if not r["label"]:
            for s_ in r["steps"]:
                if s_["flags"][det]:
                    bfp += 1
                else:
                    btn += 1
    res["benign_sessions_only"] = {"false_positive_rate": round(bfp / max(1, bfp + btn), 4),
                                   "false_positives": bfp, "benign_actions": bfp + btn}

    # session level: a session is caught only by a flag at/after the first malicious step
    stp = sfp = stn = sfn = 0
    lat: List[int] = []
    early = 0
    for r in recs:
        flags = [s["flags"][det] for s in r["steps"]]
        ms = [i for i, s in enumerate(r["steps"]) if s["m"]]
        if r["label"]:
            m0 = ms[0]
            hit = next((i for i in range(m0, len(flags)) if flags[i]), None)
            if hit is None:
                sfn += 1
            else:
                stp += 1
                lat.append(hit - m0)
            if any(flags[:m0]):
                early += 1
        else:
            if any(flags):
                sfp += 1
            else:
                stn += 1
    res["session_level"] = prf(stp, sfp, stn, sfn)
    res["detection_latency_steps"] = {
        "mean": round(float(np.mean(lat)), 2) if lat else None,
        "median": float(np.median(lat)) if lat else None,
        "p95": float(np.percentile(lat, 95)) if lat else None,
        "flagged_on_first_malicious_step": round(sum(1 for x in lat if x == 0) / max(1, len(lat)), 3),
        "sessions_flagged_before_onset": early,
    }
    y, sc = _scores(recs, det)
    if det == "A_rules":
        res["roc_auc"] = None
        res["pr_auc"] = None
        res["auc_note"] = "Binary detector: no score to rank; see balanced_accuracy."
    else:
        res["roc_auc"] = round(float(roc_auc_score(y, sc)), 4)
        res["pr_auc"] = round(float(average_precision_score(y, sc)), 4)
        if with_curves:
            f, t, _ = roc_curve(y, sc)
            pr, rc, _ = precision_recall_curve(y, sc)
            res["roc_curve"] = _downsample(f, t)
            res["pr_curve"] = _downsample(rc, pr)
    return res


def per_family(recs) -> Dict[str, Any]:
    fam: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        fam[r["family"]].append(r)
    out: Dict[str, Any] = {}
    for name, rs in sorted(fam.items()):
        row: Dict[str, Any] = {"n_sessions": len(rs), "malicious": bool(rs[0]["label"]),
                               "novel": name in NOVEL_FAMILIES}
        for det in DETECTORS:
            if rs[0]["label"]:
                hits = tot = sdet = 0
                lats = []
                for r in rs:
                    fl = [s["flags"][det] for s in r["steps"]]
                    ms = [i for i, s in enumerate(r["steps"]) if s["m"]]
                    for i in ms:
                        tot += 1
                        hits += int(fl[i])
                    h = next((i for i in range(ms[0], len(fl)) if fl[i]), None)
                    if h is not None:
                        sdet += 1
                        lats.append(h - ms[0])
                row[det] = {"action_recall": round(hits / max(1, tot), 3),
                            "session_detection": round(sdet / len(rs), 3),
                            "mean_latency_steps": round(float(np.mean(lats)), 2) if lats else None}
            else:
                fa = ta = sf = 0
                for r in rs:
                    fl = [s["flags"][det] for s in r["steps"]]
                    fa += sum(fl)
                    ta += len(fl)
                    sf += int(any(fl))
                row[det] = {"action_fpr": round(fa / max(1, ta), 3), "session_fpr": round(sf / len(rs), 3)}
        out[name] = row
    return out


# --------------------------------------------------------------- robustness
def _rand_benign_step(rng, agent, task_type):
    st = normal_steps(rng, agent, task_type, length=1)[0]
    return st


def perturb(kind: str, sessions: List[Dict[str, Any]], rng: random.Random) -> List[Dict[str, Any]]:
    out = []
    for s in sessions:
        steps = [dict(x) for x in s["steps"]]
        t = dict(s, steps=steps)
        if kind == "noise":
            new = []
            for x in steps:
                new.append(x)
                if rng.random() < 0.25:
                    new.append(_rand_benign_step(rng, s["agent"], s["task_type"]))
            t["steps"] = new
        elif kind == "duplicates":
            new = []
            for x in steps:
                new.append(x)
                if rng.random() < 0.2:
                    new.append(dict(x, dt=0.1))
            t["steps"] = new
        elif kind == "delays":
            for x in steps:
                if rng.random() < 0.15:
                    x["dt"] = round(min(60.0, x["dt"] * 15), 2)
        elif kind == "missing":
            kept = [x for x in steps if rng.random() > 0.2]
            if s["label"] and not any(x["m"] for x in kept):
                kept = steps
            t["steps"] = kept or steps
        elif kind == "task_change" and not s["label"]:
            alt = {"ops": ["routine_maintenance", "incident_response", "capacity_planning", "temp_cleanup"],
                   "support": ["refund_processing"]}[AGENTS[s["agent"]].domain]
            others = [a for a in alt if a != s["task_type"]] or alt
            new_tt = rng.choice(others)
            t["task"] = rng.choice(TASK_TEXT[new_tt])
            t["task_type"] = new_tt
        out.append(t)
    return out


def robustness(test: List[Dict[str, Any]], fps, thr: float, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in test:
        by[s["family"]].append(s)
    subset: List[Dict[str, Any]] = []
    for fam, rs in by.items():
        subset += rng.sample(rs, min(40, len(rs)))

    variants: Dict[str, List[Dict[str, Any]]] = {"clean": subset}
    for k in ["noise", "duplicates", "delays", "missing", "task_change"]:
        variants[k] = perturb(k, subset, rng)
    # benign drift: normal sessions from a much more perturbed prior
    drift_set = []
    for i in range(150):
        agent = "OpsAssist-Agent"
        tt = rng.choice(["routine_maintenance", "capacity_planning"])
        st = normal_steps(rng, agent, tt, noise=1.0)
        drift_set.append({"id": f"drift-{i}", "family": "benign_drift", "agent": agent, "task_type": tt,
                          "task": rng.choice(TASK_TEXT[tt]), "label": 0, "split": "test", "steps": st})
    variants["benign_prior_drift"] = drift_set + [s for s in subset if s["label"]]

    out: Dict[str, Any] = {}
    for name, sess in variants.items():
        recs = replay(sess, fps, thr)
        row: Dict[str, Any] = {"n_sessions": len(sess)}
        for det in DETECTORS:
            b_a = b_n = b_s = b_sn = m_s = m_sn = m_a = m_an = 0
            for r in recs:
                fl = [s["flags"][det] for s in r["steps"]]
                if r["label"]:
                    ms = [i for i, s in enumerate(r["steps"]) if s["m"]]
                    m_sn += 1
                    m_s += int(any(fl[ms[0]:]))
                    m_an += len(ms)
                    m_a += sum(fl[i] for i in ms)
                else:
                    b_sn += 1
                    b_s += int(any(fl))
                    b_n += len(fl)
                    b_a += sum(fl)
            row[det] = {"benign_action_fpr": round(b_a / max(1, b_n), 4),
                        "benign_session_fpr": round(b_s / max(1, b_sn), 4),
                        "malicious_session_detection": round(m_s / max(1, m_sn), 4),
                        "malicious_action_recall": round(m_a / max(1, m_an), 4)}
        out[name] = row
    return out


# ------------------------------------------------------ latency & separability
def live_latency(test: List[Dict[str, Any]], fps, n_sessions: int = 60) -> Dict[str, Any]:
    """Real per-action latency including real Isolation-Forest inference."""
    rng = random.Random(3)
    picks = rng.sample(test, min(n_sessions, len(test)))
    tot: List[float] = []
    stages: Dict[str, List[float]] = defaultdict(list)
    for s in picks:
        ctx = new_context(s, fps[s["agent"]])
        for st in s["steps"]:
            a = analyze(ctx, st["a"], st["dt"], st["f"], st.get("c"))
            ctx.commit(a, executed=a.decision in ("ALLOW", "MONITOR"))
            tot.append(a.latency_ms["total"])
            for k, v in a.latency_ms.items():
                stages[k].append(v)
    return {"n_actions": len(tot), "mean_ms": round(float(np.mean(tot)), 2),
            "p50_ms": round(float(np.percentile(tot, 50)), 2),
            "p95_ms": round(float(np.percentile(tot, 95)), 2),
            "stage_mean_ms": {k: round(float(np.mean(v)), 3) for k, v in stages.items() if k != "total"}}


def single_feature_auc(recs) -> List[Dict[str, Any]]:
    y = np.array([s["m"] for r in recs for s in r["steps"]])
    F = np.array([s["feat"] for r in recs for s in r["steps"]])
    rows = []
    for j, n in enumerate(FEATURE_NAMES):
        if F[:, j].std() < 1e-9:
            continue
        a = roc_auc_score(y, F[:, j])
        rows.append({"feature": n, "auc": round(float(max(a, 1 - a)), 3)})
    return sorted(rows, key=lambda r: -r["auc"])[:6]


# --------------------------------------------------------------------- main
def run(seed: int = 11) -> Dict[str, Any]:
    if not detector.ready:
        raise SystemExit(detector.load_error)
    thr = detector.threshold
    sessions = load()
    test = [s for s in sessions if s["split"] == "test"]
    dev = [s for s in sessions if s["split"] == "dev"]
    fps = fingerprints()
    t0 = time.time()
    recs = replay(test, fps, thr)
    dev_recs = replay(dev, fps, thr)
    dev_summary = {d: {"action_level": detector_metrics(dev_recs, d, False)["action_level"],
                       "session_level": detector_metrics(dev_recs, d, False)["session_level"]} for d in DETECTORS}

    ablation = {d: detector_metrics(recs, d) for d in DETECTORS}
    n_mal = sum(1 for r in recs if r["label"])
    D = ablation["D_full"]
    benign_actions = sum(len(r["steps"]) for r in recs if not r["label"])
    monitor_benign = sum(1 for r in recs if not r["label"] for s in r["steps"] if s["decision"] == "MONITOR")

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": "IsolationForest (one-class, trained on normal sessions only)",
        "dataset": ("SYNTHETIC - generated locally by backend/ml/generate_dataset.py from hand-written "
                    "behavioural models of two simulated agents. Not real-world telemetry."),
        "split": "By SESSION. Training: normal sessions only. `test`: fresh held-out sessions (independent seed) "
                 "with a perturbed transition prior, hard negatives and three novel attack families.",
        "mode": "Shadow mode: decisions are computed but the agent is never halted, so all detectors see identical actions.",
        "threshold": thr,
        "n_test_sessions": len(test), "n_malicious_sessions": n_mal, "n_benign_sessions": len(test) - n_mal,
        "n_test_actions": sum(len(r["steps"]) for r in recs),
        "n_malicious_actions": sum(s["m"] for r in recs for s in r["steps"]),
        "novel_families": NOVEL_FAMILIES,
        "dev_set": {"note": "Used while iterating on detectors (STAGNATION / BULK_READ loop rules were added after "
                            "inspecting these results). The headline numbers above are from the fresh `test` split.",
                    "n_sessions": len(dev), "detectors": dev_summary},
        "detector_labels": DET_LABEL,
        "ablation": ablation,
        "per_family": per_family(recs),
        "friction_on_benign": {
            "benign_actions": benign_actions,
            "monitor_rate": round(monitor_benign / max(1, benign_actions), 4),
        },
        "single_feature_separability": single_feature_auc(recs),
        "live_latency": live_latency(test, fps),
        "robustness": robustness(test, fps, thr, seed),
        "headline": {"detector": "D_full", "action_level": D["action_level"], "roc_auc": D["roc_auc"],
                     "pr_auc": D["pr_auc"], "detection_latency_steps": D["detection_latency_steps"]},
        "eval_seconds": round(time.time() - t0, 1),
        "limitations": [
            "Synthetic data from the same designer's assumptions as the detector: results show the pipeline "
            "works, not that it generalises to real agent telemetry.",
            "Sequence rules encode known attack shapes; only the three novel families test generalisation.",
            "Accuracy is reported but is weak for this imbalanced, one-class problem; use precision, recall, "
            "FPR and PR-AUC.",
            "Trust is fixed at 100 in shadow evaluation to isolate the per-action layers.",
        ],
    }
    return report


def run_and_save() -> Dict[str, Any]:
    rep = run()
    with open(EVALUATION_PATH, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"[eval] report -> {EVALUATION_PATH}  ({rep['eval_seconds']}s)")
    print(f"[eval] test: {rep['n_test_sessions']} sessions / {rep['n_test_actions']} actions "
          f"({rep['n_malicious_actions']} malicious)")
    for d in DETECTORS:
        m = rep["ablation"][d]
        a, s = m["action_level"], m["session_level"]
        print(f"  {DET_LABEL[d]:<52} P={a['precision']:.3f} R={a['recall']:.3f} F1={a['f1']:.3f} "
              f"FPR={a['false_positive_rate']:.3f} | session R={s['recall']:.3f} FPR={s['false_positive_rate']:.3f}"
              f" | ROC={m['roc_auc']} PR={m['pr_auc']}")
    return rep


if __name__ == "__main__":
    run_and_save()
