"""Behaviour graph and incident replay, both built from recorded data.

Graph columns:  Agent -> Task -> Action -> Tool -> Resource -> Permission
Each executed step contributes a path; shared tools/resources/permissions are
merged into one node. Suspicious paths (blocked, held, or part of a matched
attack-chain pattern) are flagged so the UI can highlight them.

Replay: an ordered list of frames (audit events + the actions they refer to),
each with the derived agent status and the simulated environment state at that
moment, so a judge can scrub through an incident like a recording.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.database.models import Action, Agent, AuditEvent, Incident, Session_, Task
from backend.app.services import envsim, recovery
from backend.app.services.pipeline import action_to_dict

SUSPICIOUS_DECISIONS = {"BLOCK", "TERMINATE", "REQUIRE_APPROVAL"}


def session_graph(db: Session, session_id: str) -> Dict[str, Any]:
    sess = db.get(Session_, session_id)
    agent = db.get(Agent, sess.agent_id)
    task = db.query(Task).filter(Task.session_id == session_id).first()
    acts = db.query(Action).filter(Action.session_id == session_id).order_by(Action.step_index.asc()).all()

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}

    def node(nid: str, kind: str, label: str, **kw: Any) -> None:
        n = nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, "suspicious": False})
        n.update({k: v for k, v in kw.items() if k != "suspicious"})
        if kw.get("suspicious"):
            n["suspicious"] = True

    def edge(a: str, b: str, sus: bool, kind: str = "flow") -> None:
        eid = f"{a}>{b}"
        e = edges.setdefault(eid, {"id": eid, "source": a, "target": b, "suspicious": False, "kind": kind})
        if sus:
            e["suspicious"] = True

    node("agent", "agent", agent.name)
    node("task", "task", (task.description if task else "task")[:60])
    edge("agent", "task", False)

    # every step of a matched attack chain is suspicious, including its benign opening step
    in_chain: set = set()
    for a in acts:
        for p in json.loads(a.risk_factors_json).get("sequence", {}).get("patterns", []):
            if p.get("progress", 0) < 2:
                continue
            want = list(p.get("path", []))
            for b in acts:
                if b.step_index > a.step_index or not want:
                    continue
                if b.action_type == want[0]:
                    in_chain.add(b.id)
                    want.pop(0)

    path_ids: List[str] = []
    prev_id = None
    for a in acts:
        rf = json.loads(a.risk_factors_json)
        sus = a.decision in SUSPICIOUS_DECISIONS or a.risk_level in ("HIGH", "CRITICAL") or a.id in in_chain
        aid = f"act:{a.id}"
        tool, res, perm = f"tool:{a.tool_name}", f"res:{a.resource}", f"perm:{a.permission_level}"
        node(aid, "action", a.action_type, step=a.step_index, decision=a.decision, risk=a.risk_score,
             risk_level=a.risk_level, suspicious=sus, alignment=round(a.task_relevance, 2),
             executed=a.execution_result == "SUCCESS")
        node(tool, "tool", a.tool_name, suspicious=sus)
        node(res, "resource", a.resource, suspicious=sus)
        node(perm, "permission", a.permission_level, suspicious=sus)
        edge("task", aid, sus)
        edge(aid, tool, sus)
        edge(tool, res, sus)
        edge(res, perm, sus)
        if prev_id:
            edge(prev_id, aid, sus, kind="sequence")
        prev_id = aid
        if sus:
            path_ids.append(aid)

    return {"session_id": session_id, "nodes": list(nodes.values()), "edges": list(edges.values()),
            "suspicious_path": path_ids,
            "chain": [n["label"] for n in nodes.values() if n["kind"] == "action"]}


def _agent_state(event: str, cur: str) -> str:
    return {"AGENT_STARTED": "RUNNING", "ACTION_BLOCKED": "SUSPICIOUS", "AGENT_PAUSED": "PAUSED",
            "APPROVAL_REQUESTED": "PAUSED", "HUMAN_APPROVAL": "RUNNING", "HUMAN_REJECTION": "RUNNING",
            "INCIDENT_RESOLVED": "IDLE", "SESSION_COMPLETED": "IDLE"}.get(event, cur)


def incident_replay(db: Session, incident: Incident) -> Dict[str, Any]:
    events: List[AuditEvent] = (db.query(AuditEvent).filter(AuditEvent.session_id == incident.session_id)
                                  .order_by(AuditEvent.timestamp.asc()).all())
    acts = db.query(Action).filter(Action.session_id == incident.session_id).order_by(Action.step_index.asc()).all()
    rec_events = recovery.recovery_events(db, incident.id)
    exec_events = [e for e in events if e.event_type == "ACTION_EXECUTED"]
    action_for = {e.id: acts[i] for i, e in enumerate(exec_events) if i < len(acts)}
    restored_snaps = [r for r in rec_events if r["recovery_action"] == "INTEGRITY_VERIFICATION"]

    env = envsim.fresh_state()
    state = "IDLE"
    t0 = events[0].timestamp if events else None
    frames: List[Dict[str, Any]] = []
    snap_i = 0
    for e in events:
        state = _agent_state(e.event_type, state)
        act = action_for.get(e.id)
        if act is not None and act.execution_result == "SUCCESS":
            env, _ = envsim.apply(env, act.action_type)
        if e.event_type == "RECOVERY_STEP":
            if "REVERT_PERMISSIONS" in (e.reason or ""):
                for n in ("iam/role-bindings", "security/guardrails"):
                    env[n] = envsim.HEALTHY
            if "INTEGRITY_VERIFICATION" in (e.reason or "") and snap_i < len(restored_snaps):
                env = dict(restored_snaps[snap_i]["restored_state"]) or env
                snap_i += 1
            elif "RESTORE_RESOURCES" in (e.reason or "") and "OK" in (e.decision or ""):
                env = envsim.fresh_state()
        frames.append({
            "t": round((e.timestamp - t0).total_seconds(), 2) if t0 else 0.0,
            "event_type": e.event_type, "reason": e.reason, "action_type": e.action_type,
            "risk_score": e.risk_score, "risk_level": e.risk_level, "decision": e.decision,
            "agent_status": state, "environment": dict(env),
            "action": action_to_dict(act) if act is not None else None,
        })
    return {"incident_id": incident.id, "reference": incident.reference, "frames": frames,
            "duration_s": frames[-1]["t"] if frames else 0.0}
