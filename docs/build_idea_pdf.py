"""Builds the hackathon idea submission PDF: docs/Agent_Sentinel_Idea_Submission.pdf"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).parent / "Agent_Sentinel_Idea_Submission.pdf"

INK = colors.HexColor("#1b2430")
ACCENT = colors.HexColor("#1f5fbf")
MUTED = colors.HexColor("#5b6675")
TINT = colors.HexColor("#eef3fb")

base = getSampleStyleSheet()
body = ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=10,
                      leading=14.5, textColor=INK, alignment=TA_LEFT, spaceAfter=4)
h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=21, leading=25,
                    textColor=INK, spaceAfter=2)
tag = ParagraphStyle("tag", parent=body, fontSize=11, leading=15, textColor=ACCENT, spaceAfter=8)
h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                    textColor=ACCENT, spaceBefore=10, spaceAfter=3)
small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=12, textColor=MUTED)
cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=12.5, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(t, body), leftIndent=12, value="circle") for t in items],
        bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8,
    )


def table(rows, widths, header=True):
    data = [[Paragraph(c, cellb if (header and i == 0) or j == 0 else cell)
             for j, c in enumerate(r)] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3e3")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), TINT))
    t.setStyle(TableStyle(style))
    return t


def rule():
    return HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#c9d3e3"),
                      spaceBefore=2, spaceAfter=4)


story = [
    Paragraph("Agent Sentinel", h1),
    Paragraph("AI Agent Misbehaviour Detection &amp; Recovery &mdash; a runtime safety layer "
              "for autonomous AI agents", tag),
    Paragraph("Idea submission &nbsp;|&nbsp; Team: AgentGuard &nbsp;|&nbsp; "
              "Working prototype (controlled simulation) &nbsp;|&nbsp; Code: "
              "<link href='https://github.com/SHWE1530/agentguard-ai' color='#1f5fbf'>"
              "github.com/SHWE1530/agentguard-ai</link>", small),
    rule(),

    Paragraph("1. Problem statement", h2),
    Paragraph(
        "Autonomous AI agents now hold real tool access: files, databases, permissions, "
        "infrastructure. They can act outside their intended task because of faulty reasoning, "
        "prompt injection, goal misalignment, excessive permissions or getting stuck in a loop. "
        "The dangerous failures are not crashes. They are <b>plausible-looking actions on the "
        "wrong resource</b>: reading a file the agent should not, escalating its own "
        "privileges, exporting data, dropping a table.", body),
    Paragraph(
        "Existing defences each fail alone. A fixed allow-list misses behaviour nobody thought "
        "to enumerate. A model-only detector flags legitimate work (our measured false-positive "
        "rate is 5.5%, i.e. legitimate work blocked several times an hour) and can be talked "
        "around. Neither explains itself to a human, and neither helps once damage has landed.",
        body),

    Paragraph("2. Solution", h2),
    Paragraph(
        "Agent Sentinel wraps the agent in a layered safety envelope. Every action the agent "
        "attempts is intercepted <i>before</i> execution and run through one pipeline:", body),
    Paragraph("<b>OBSERVE &rarr; DETECT &rarr; ASSESS RISK &rarr; EXPLAIN &rarr; ALLOW / "
              "MONITOR / APPROVE / BLOCK / STOP &rarr; RECOVER &rarr; VERIFY &rarr; AUDIT</b>",
              ParagraphStyle("flow", parent=body, textColor=ACCENT, spaceBefore=2, spaceAfter=6)),
    table([
        ["Layer", "Answers", "How"],
        ["ML behaviour detection", "How unusual is this?", "Isolation Forest on 16 behavioural features"],
        ["Policy enforcement", "Is this permitted?", "Deterministic rules in an editable policy file"],
        ["Risk scoring", "How much does it matter?", "Weighted fusion (0&ndash;100) of anomaly and consequence"],
        ["Explanation", "Why was I stopped?", "Generated from the factors that actually fired"],
        ["Human oversight", "Should a person decide?", "Blocking approval queue for high-consequence actions"],
        ["Recovery + verification", "Are we back to safe?", "Rollback, re-inspect, report the truth"],
    ], [42 * mm, 44 * mm, 88 * mm]),
    Spacer(1, 4),
    Paragraph("<b>No layer is trusted alone</b> &mdash; that is the central design claim. The "
              "model is an <i>input to</i> the decision, never the decision.", body),
    Paragraph(
        "<b>Demo (critical scenario):</b> the agent checks server health (allowed), then "
        "attempts a permission change (blocked, privilege escalation), a data export (blocked, "
        "exfiltration) and <font face='Courier'>DELETE_DATABASE</font> (blocked pre-execution, "
        "agent stopped). The protected resource is still HEALTHY, an incident is opened, "
        "recovery runs, and the system reports <i>RECOVERY VERIFIED</i> only after "
        "re-inspecting every resource.", body),

    Paragraph("3. Technology", h2),
    table([
        ["Area", "Stack"],
        ["Backend", "Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite, Uvicorn"],
        ["ML", "scikit-learn Isolation Forest (one-class novelty detection), pandas, numpy, joblib"],
        ["Frontend", "React 18, TypeScript, Vite, Tailwind CSS, Recharts"],
        ["Realtime", "WebSocket event stream with automatic reconnect"],
        ["Quality", "29 automated tests (pipeline, policy, recovery, audit, API, WebSocket); Docker support"],
    ], [28 * mm, 146 * mm]),
    Spacer(1, 4),
    Paragraph(
        "<b>Safety of the prototype itself:</b> every dangerous action runs in a sandbox held in "
        "SQLite rows. Nothing touches a real file, database, service or host. The behavioural "
        "dataset is synthetic and generated locally; no credentials or sensitive data are used.",
        body),

    Paragraph("4. Innovation", h2),
    bullets([
        "<b>Defence in depth for agent behaviour.</b> Learned anomaly detection and hard policy "
        "are fused, so novel misbehaviour is caught by the model and known-forbidden actions "
        "are never left to a probability.",
        "<b>Trained only on normal behaviour.</b> Unsupervised novelty detection means we do not "
        "need to enumerate every way an agent can fail.",
        "<b>Risk is not the anomaly score.</b> It weighs consequence (sensitivity, severity, "
        "privilege, task relevance) with weights in an editable file, so operators can tune "
        "without touching code.",
        "<b>Block is not halt.</b> A denied but reversible action lets the agent continue under "
        "suspicion so behaviour can be observed; only a critical irreversible attempt stops "
        "it. A repeat-offender rule pauses the agent for human review after repeated blocks.",
        "<b>Honest recovery.</b> Verification re-inspects the environment after rollback and "
        "reports failure if the world is still broken; it never assumes success.",
        "<b>Explainable and replayable.</b> Each decision shows factor weights, violated "
        "policies and a generated explanation; incidents can be replayed from an append-only "
        "audit trail.",
        "<b>Graceful degradation.</b> If the model is unavailable, a transparent heuristic "
        "keeps protection on and labels every score as such.",
    ]),

    Paragraph("5. Impact", h2),
    bullets([
        "<b>Safer autonomy.</b> Organisations can grant agents real tool access while keeping "
        "actions inside declared boundaries, which is the main blocker to production adoption.",
        "<b>Limits blast radius.</b> Harmful actions are stopped before execution, and recovery "
        "returns the environment to a verified known-good state.",
        "<b>Trust and accountability.</b> Human approval for high-risk actions plus a complete "
        "evidence chain supports compliance and post-incident review.",
        "<b>Fewer false alarms.</b> Combining model and policy avoids the operational cost of "
        "model-only blocking.",
        "<b>Broad applicability.</b> Relevant wherever agents operate: DevOps and SRE, "
        "customer-data workflows, finance operations, internal IT automation.",
    ]),
    Spacer(1, 2),
    Paragraph("<b>Measured on held-out synthetic data</b> (2,536 records, 567 abnormal; "
              "reproducible with <font face='Courier'>python -m backend.ml.train_model</font>):",
              body),
    table([
        ["Precision", "Recall", "F1", "False-positive rate", "Mean anomaly: normal / abnormal"],
        ["0.830", "0.938", "0.881", "0.055", "0.065 / 0.901"],
    ], [26 * mm, 26 * mm, 22 * mm, 36 * mm, 64 * mm]),
    Spacer(1, 3),
    Paragraph(
        "<b>Limitations, stated plainly:</b> results come from synthetic data and show that the "
        "pipeline works, not that it generalises to real agent telemetry. Future work: "
        "reasoning-trace analysis with LLMs, sequence models, multi-agent correlation, policy "
        "learning from operator decisions, and real IAM/Kubernetes integration.", small),
]

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=16 * mm, bottomMargin=16 * mm,
                        title="Agent Sentinel - Idea Submission", author="AgentGuard")
doc.build(story)
print(f"wrote {OUT}")
