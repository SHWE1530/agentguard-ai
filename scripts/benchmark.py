"""Measure decision throughput and latency. Numbers are for THIS machine, one process.

    python scripts/benchmark.py

Reports (1) the pure analyzer with real Isolation-Forest inference, (2) the same with the
model scored in batch (the offline-evaluation path), and (3) the full persisted pipeline
(context rebuilt from SQLite, audit rows written, events published).
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.gettempdir(), "sentinel_bench.db")
os.environ["SENTINEL_AUTH"] = "off"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from backend.ml.generate_dataset import load  # noqa: E402
from backend.ml.replay import new_context, session_features  # noqa: E402
from backend.app.services.analysis import analyze  # noqa: E402
from backend.app.services.ml_detector import detector  # noqa: E402


def pct(xs, q):
    return float(np.percentile(xs, q))


def main() -> None:
    sessions = [s for s in load() if s["split"] == "test"]
    random.Random(1).shuffle(sessions)
    sample = sessions[:300]
    fps = {a: detector.bootstrap_fingerprint(a) for a in ("OpsAssist-Agent", "SupportAssist-Agent")}
    n_actions = sum(len(s["steps"]) for s in sample)

    # 1. pure analyzer, real per-action model inference
    lat = []
    t0 = time.perf_counter()
    for s in sample:
        ctx = new_context(s, fps[s["agent"]])
        for st in s["steps"]:
            t = time.perf_counter()
            a = analyze(ctx, st["a"], st["dt"], st["f"], st.get("c"))
            lat.append((time.perf_counter() - t) * 1000)
            ctx.commit(a, executed=a.decision in ("ALLOW", "MONITOR"))
    wall = time.perf_counter() - t0
    print(f"[1] analyzer, per-action inference : {n_actions / wall:8.0f} decisions/s   "
          f"p50 {pct(lat, 50):.1f} ms  p95 {pct(lat, 95):.1f} ms  ({n_actions} actions)")

    # 2. batch-scored model (offline path)
    X = []
    t0 = time.perf_counter()
    for s in sample:
        rows, _ = session_features(s, fps[s["agent"]])
        X.extend(rows)
    an = detector.score_matrix(np.array(X))
    k = 0
    for s in sample:
        ctx = new_context(s, fps[s["agent"]])
        for st in s["steps"]:
            a = analyze(ctx, st["a"], st["dt"], st["f"], st.get("c"), anomaly_override=float(an[k]))
            k += 1
            ctx.commit(a, executed=a.decision in ("ALLOW", "MONITOR"))
    wall = time.perf_counter() - t0
    print(f"[2] analyzer, batch-scored model   : {n_actions / wall:8.0f} decisions/s")

    # 3. full persisted pipeline
    from backend.app.database.db import reset_db, session
    from backend.app.database.models import Session_, Task
    from backend.app.services import baseline, sandbox, simulator
    from backend.app.services.pipeline import evaluate_action

    reset_db()
    baseline.clear_cache()
    db = session()
    sandbox.ensure_baseline(db)
    simulator.ensure_all_agents(db)
    agent = simulator.ensure_agent(db, "OpsAssist-Agent")
    lat3, count = [], 0
    ops = [s for s in sample if s["agent"] == "OpsAssist-Agent"][:40]
    t0 = time.perf_counter()
    for s in ops:
        sess = Session_(agent_id=agent.id, scenario="bench", status="RUNNING")
        db.add(sess)
        db.commit()
        task = Task(session_id=sess.id, description=s["task"])
        db.add(task)
        db.commit()
        for i, st in enumerate(s["steps"]):
            sess = db.get(Session_, sess.id)
            if sess.status != "RUNNING":
                break
            t = time.perf_counter()
            evaluate_action(db, agent=agent, sess=sess, task_id=task.id, action_type=st["a"], step_index=i,
                            dt=st["dt"], failed=st["f"], content=st.get("c"))
            lat3.append((time.perf_counter() - t) * 1000)
            count += 1
        agent.status = "IDLE"
        db.commit()
    wall = time.perf_counter() - t0
    print(f"[3] full persisted pipeline        : {count / wall:8.1f} decisions/s   "
          f"p50 {pct(lat3, 50):.0f} ms  p95 {pct(lat3, 95):.0f} ms  ({count} actions, SQLite, 1 process)")
    print("\nNote: single process, single SQLite file. See README 'Scaling path' for what changes at fleet scale.")


if __name__ == "__main__":
    main()
