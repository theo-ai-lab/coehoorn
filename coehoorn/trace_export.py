"""Export a Coehoorn Report's transcripts as Plimsoll native traces.

Plimsoll (same org) is a span-level policy gate for tool-using agents:
allow/forbid lists, required tool ordering, budgets. Converting a finished
siege into its native trace format lets a second, independent analyzer
re-derive the verdict from the raw run record. The judge cites a breach
turn; the trace gate must find the same forbidden call or ordering
violation in the spans — if the two disagree, one of them is wrong.

The conversion is a pure function of the Report and emits plain JSON:
nothing here imports plimsoll, so the core path gains no dependency. The
gate itself runs wherever plimsoll is installed (see
``.github/workflows/trace-gate.yml`` and ``tests/test_trace_export.py``).

Span timing is synthetic-ordinal. Coehoorn records turn ORDER, not
per-turn latency, so each turn occupies a fixed one-second slot: turn ``i``
spans ``[i*1000, i*1000+900]`` and its tool calls nest inside the slot in
call order. Order-sensitive checks (forbidden tools, ``must_precede``,
sequences) are sound against these traces; duration budgets
(``max_duration_ms``) are NOT — the durations are placeholders, and the
trace metadata says so.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import CriterionStatus, Report, Transcript, Verdict

TURN_SLOT_MS = 1000
_TURN_SPAN_MS = 900
_TOOL_STEP_MS = 10
_TOOL_SPAN_MS = 5

_TIMING_NOTE = (
    "synthetic-ordinal: span times encode turn order only (one 1000ms slot "
    "per turn), not measured latency; do not apply duration budgets"
)


def transcript_to_trace(
    transcript: Transcript,
    verdict: Verdict,
    *,
    run_id: str,
    agent_endpoint: str,
) -> dict[str, Any]:
    """Build one Plimsoll native trace (a plain dict) from one transcript.

    Every turn becomes a span (``kind="input"`` for the persona,
    ``kind="model"`` for the agent) and every tool call becomes a nested
    ``kind="tool"`` span carrying ``tool_name`` and the call arguments, so
    Plimsoll's tool-sequence checks see exactly the calls the judge saw.
    Coehoorn's verdict rides along in ``metadata`` for cross-referencing;
    Plimsoll ignores metadata when evaluating, so the gate's decision is
    derived independently from the spans alone.
    """
    spans: list[dict[str, Any]] = []
    final_output = ""
    for turn in transcript.turns:
        slot = turn.index * TURN_SLOT_MS
        if turn.role == "assistant":
            final_output = turn.content
        spans.append(
            {
                "span_id": f"turn-{turn.index:02d}",
                "name": f"{turn.role} turn {turn.index}",
                "kind": "model" if turn.role == "assistant" else "input",
                "status": "ok",
                "start_ms": slot,
                "end_ms": slot + _TURN_SPAN_MS,
                "output": turn.content,
            }
        )
        for j, call in enumerate(turn.tool_calls):
            start = slot + _TOOL_STEP_MS * (j + 1)
            spans.append(
                {
                    "span_id": f"turn-{turn.index:02d}-tool-{j}",
                    "name": call.name,
                    "kind": "tool",
                    "status": "ok",
                    "start_ms": start,
                    "end_ms": start + _TOOL_SPAN_MS,
                    "tool_name": call.name,
                    "input": call.arguments,
                }
            )
    breaches = [
        {"criterion": cv.criterion_id, "turn": cv.cited_turn_index}
        for cv in verdict.criterion_verdicts
        if cv.status is CriterionStatus.FAIL
    ]
    return {
        "run_id": f"{run_id}/{transcript.id}",
        "case_id": transcript.id,
        "final_output": final_output,
        "metadata": {
            "source": "coehoorn",
            "coehoorn_run_id": run_id,
            "agent_endpoint": agent_endpoint,
            "persona": transcript.persona.name,
            "archetype": transcript.persona.archetype.value,
            "coehoorn_outcome": verdict.outcome.value,
            "coehoorn_breaches": breaches,
            "timing": _TIMING_NOTE,
        },
        "spans": spans,
    }


def report_to_traces(report: Report) -> list[dict[str, Any]]:
    """Convert every transcript in a Report to a Plimsoll trace dict.

    Report's referential-integrity validator guarantees exactly one verdict
    per transcript, so the lookup below cannot miss.
    """
    verdict_by_tid = {v.transcript_id: v for v in report.verdicts}
    return [
        transcript_to_trace(
            t,
            verdict_by_tid[t.id],
            run_id=report.run_id,
            agent_endpoint=report.agent_endpoint,
        )
        for t in report.transcripts
    ]


def write_trace_files(report: Report, out_dir: str | Path) -> list[Path]:
    """Write one ``<transcript_id>.json`` trace per transcript. Returns paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for trace in report_to_traces(report):
        path = out / f"{trace['case_id']}.json"
        path.write_text(json.dumps(trace, indent=2) + "\n")
        paths.append(path)
    return paths
