"""MCP server — expose Coehoorn so other agents can lay siege to a chat agent.

An agent that can stress-test agents. Optional extra:

    pip install 'coehoorn[mcp]'
    coehoorn-mcp            # speaks MCP over stdio

The `mcp` dependency is imported lazily inside :func:`build_server`, so the
core package never pulls it in; `import coehoorn` and the `coehoorn` CLI work with
no extras installed. The single tool runs a deterministic heuristic siege (no
API key, no telemetry) and returns the breach report as structured data.
"""
from __future__ import annotations

from typing import Any

import yaml

from .aggregator import build_report
from .conversation import run_conversations
from .judge import judge_all
from .personas import generate_personas_heuristic
from .rubric_parser import parse_rubric_dict
from .schemas import CriterionStatus, VerdictOutcome


def build_server() -> Any:
    """Construct the FastMCP server. Raises a clear error if the extra is absent."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The Coehoorn MCP server requires the optional extra: "
            "pip install 'coehoorn[mcp]'"
        ) from e

    server = FastMCP("coehoorn")

    @server.tool()
    async def lay_siege(
        agent_endpoint: str,
        rubric_yaml: str,
        personas: int = 6,
        turns: int = 4,
    ) -> dict:
        """Run a heuristic adversarial siege against an HTTP chat agent.

        The agent must accept ``{"conversation": [...]}`` and return
        ``{"reply": "..."}``. Returns the breach report: which adversarial
        approaches broke which criteria, at which cited turn.
        """
        rubric, rules = parse_rubric_dict(yaml.safe_load(rubric_yaml))
        from .agent_adapter import HttpAgentAdapter

        async with HttpAgentAdapter(agent_endpoint) as adapter:
            transcripts = await run_conversations(
                generate_personas_heuristic(n=personas),
                adapter,
                max_turns=turns,
                mode="heuristic",
            )
        verdicts = judge_all(transcripts, rubric, rules, mode="heuristic")
        report = build_report(
            rubric=rubric,
            transcripts=transcripts,
            verdicts=verdicts,
            agent_endpoint=agent_endpoint,
        )
        by_tid = {v.transcript_id: v for v in report.verdicts}
        breach_detail = [
            {
                "persona": t.persona.id,
                "archetype": t.persona.archetype.value,
                "criteria": [
                    cv.criterion_id
                    for cv in by_tid[t.id].criterion_verdicts
                    if cv.status is CriterionStatus.FAIL
                ],
                "worst_moment_turn": by_tid[t.id].worst_moment_turn_index,
            }
            for t in report.transcripts
            if by_tid[t.id].outcome is VerdictOutcome.FAIL
        ]
        return {
            "run_id": report.run_id,
            "breaches": len(breach_detail),
            "held": sum(1 for v in verdicts if v.outcome is VerdictOutcome.PASS),
            "pass_rate": report.pass_rate,
            "abstention_rate": report.abstention_rate,
            "breaches_by_archetype": report.failures_by_archetype,
            "breach_detail": breach_detail,
        }

    return server


def main() -> int:
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
