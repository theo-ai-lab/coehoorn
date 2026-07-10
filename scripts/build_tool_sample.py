"""Builds a deterministic TOOL-USE siege sample under runs/sample-tools/.

Demonstrates the agentic attack surface: an in-process, deliberately-flawed
tool-using agent that (1) calls a destructive `delete_account` tool and
(2) issues a refund with no prior approval. The heuristic judge catches both —
OWASP Agentic ASI02 (tool misuse) and ASI03 (privilege/approval bypass) — and
cites the exact turn, with no API key.

Re-run with: `uv run python scripts/build_tool_sample.py`.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from coehoorn.agent_adapter import AgentReply, CallableAdapter
from coehoorn.aggregator import build_report, pin_report_timestamps, write_report_json
from coehoorn.conversation import run_conversations
from coehoorn.judge import judge_all
from coehoorn.personas import generate_personas_heuristic
from coehoorn.report_html import write_report_html
from coehoorn.rubric_parser import parse_rubric_file
from coehoorn.schemas import CriterionStatus, VerdictOutcome

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_ID = "coehoorn-tools-0000-0000-000000000000"
CREATED = datetime(2026, 5, 17, 10, 8, 0, tzinfo=UTC)
COMPLETED = datetime(2026, 5, 17, 10, 8, 4, tzinfo=UTC)


def _flawed_tool_agent(conversation: list[dict]) -> AgentReply:
    # Behavior keyed to conversation depth so every persona deterministically
    # surfaces the same two flaws.
    replies = sum(1 for m in conversation if m.get("role") == "assistant")
    if replies == 0:
        return AgentReply(
            "Of course — taking care of that for you now.",
            tool_calls=[{"name": "delete_account", "arguments": {"user": "caller"}}],
        )
    if replies == 1:
        return AgentReply(
            "Refund processed.",
            tool_calls=[{"name": "issue_refund", "arguments": {"amount": 100}}],
        )
    return AgentReply("Is there anything else I can help with?")


async def main() -> int:
    rubric, rules = parse_rubric_file(REPO_ROOT / "examples" / "rubric_tools.yaml")
    personas = generate_personas_heuristic(n=6)
    agent = CallableAdapter(_flawed_tool_agent)
    transcripts = await run_conversations(
        personas, agent, max_turns=4, mode="heuristic", concurrency=4
    )
    verdicts = judge_all(transcripts, rubric, rules, mode="heuristic")
    report = build_report(
        rubric=rubric, transcripts=transcripts, verdicts=verdicts,
        agent_endpoint="in-process://flawed-tool-agent",
    )
    report = pin_report_timestamps(
        report, created_at=CREATED, completed_at=COMPLETED, run_id=RUN_ID
    )

    out_dir = REPO_ROOT / "runs" / "sample-tools"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, out_dir / "report.json")
    write_report_html(report, out_dir / "report.html")

    breaches = sum(1 for v in verdicts if v.outcome is VerdictOutcome.FAIL)
    cited = [
        (t.persona.id, cv.criterion_id, cv.cited_turn_index)
        for t in transcripts for v in verdicts if v.transcript_id == t.id
        for cv in v.criterion_verdicts if cv.status is CriterionStatus.FAIL
    ]
    print(f"tool siege: {breaches}/{len(verdicts)} approaches breached")
    for pid, cid, turn in cited[:6]:
        print(f"  {pid}: {cid} at turn {turn}")
    print(f"wrote: {out_dir}/report.json, report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
