"""Builds the deterministic MCP tool-poisoning sample reports under runs/sample-mcp/.

One report per archetype (hero first): rug-pull, tool-description poisoning, and
cross-server shadowing. Each drives a deliberately-vulnerable agent through an
offline loopback MCP fixture (no network, no API key) and lets the heuristic judge
cite the exact turn a poisoned tool description flipped the agent — for the
rug-pull, the turn the tool turned. Provenance (run id + timestamps) is pinned so
the committed reports are byte-reproducible.

Re-run with: `uv run python scripts/build_mcp_sample.py`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from coehoorn.aggregator import build_report, pin_report_timestamps, write_report_json
from coehoorn.judge import judge_all
from coehoorn.mcp_redteam import SCENARIOS, build_scenario, mcp_tool_poisoning_rubric, run_scenario
from coehoorn.report_html import write_report_html
from coehoorn.schemas import CriterionStatus, VerdictOutcome

REPO_ROOT = Path(__file__).resolve().parent.parent
CREATED = datetime(2026, 5, 17, 10, 8, 0, tzinfo=timezone.utc)
COMPLETED = datetime(2026, 5, 17, 10, 8, 4, tzinfo=timezone.utc)


async def main() -> int:
    rubric, rules = mcp_tool_poisoning_rubric()
    out_root = REPO_ROOT / "runs" / "sample-mcp"
    breaches = 0

    for i, key in enumerate(SCENARIOS):
        scenario = build_scenario(key)
        transcript = await run_scenario(scenario)
        verdicts = judge_all([transcript], rubric, rules, mode="heuristic")
        report = build_report(
            rubric=rubric,
            transcripts=[transcript],
            verdicts=verdicts,
            agent_endpoint=f"loopback-mcp://{key}",
        )
        report = pin_report_timestamps(
            report,
            created_at=CREATED,
            completed_at=COMPLETED,
            run_id=f"coehoorn-mcp-{i:04d}-0000-000000000000",
        )

        out_dir = out_root / key
        write_report_json(report, out_dir / "report.json")
        write_report_html(report, out_dir / "report.html")

        v = verdicts[0]
        breaches += 1 if v.outcome is VerdictOutcome.FAIL else 0
        cited = [
            (cv.criterion_id, cv.cited_turn_index)
            for cv in v.criterion_verdicts
            if cv.status is CriterionStatus.FAIL
        ]
        marker = "  <- HERO" if i == 0 else ""
        print(f"[{key}] outcome={v.outcome.value}{marker}")
        for cid, turn in cited:
            print(f"    breach: {cid} cited at turn {turn}")
        print(f"    wrote: {out_dir}/report.json, report.html")

    print(f"pack: {breaches}/{len(SCENARIOS)} archetypes breached the vulnerable agent")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
