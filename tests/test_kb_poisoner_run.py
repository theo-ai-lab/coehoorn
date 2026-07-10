"""`coehoorn run` wiring for the KB-poisoner (7th) persona.

Proves the write-back-contamination surface is reachable end-to-end from
`coehoorn run --include-kb-poisoner`: the persona drives its dedicated probe
script (not the generic INJECTOR one), the run's rubric is additively folded with
the write-back criteria, a vulnerable write-back target is breached and cited,
and the safe stub holds with no false breach leaking onto the other personas.
"""
from __future__ import annotations

import glob
import json
import random
import sys
from pathlib import Path

import pytest

from coehoorn.agent_adapter import AgentReply, CallableAdapter
from coehoorn.aggregator import build_report
from coehoorn.cli import main
from coehoorn.conversation import run_conversations
from coehoorn.judge import judge_all
from coehoorn.personas import generate_personas_heuristic
from coehoorn.personas_kb import (
    KB_POISONER_PROBES,
    kb_poisoner_persona,
    kb_poisoner_rubric,
    merge_kb_poisoner_rubric,
)
from coehoorn.rubric_parser import parse_rubric_file
from coehoorn.schemas import CriterionStatus, VerdictOutcome

REPO_ROOT = Path(__file__).resolve().parent.parent
COACH = str(REPO_ROOT / "examples" / "rubric_coach.yaml")
STUB_DIR = REPO_ROOT / "apps" / "stub-agent"

_KB_CRITERIA = ("kb_write_requires_sanitization", "no_persisted_injection_echo")


def _stub_call():
    random.seed(20260517)
    if str(STUB_DIR) not in sys.path:
        sys.path.insert(0, str(STUB_DIR))
    from app import app  # type: ignore

    client = app.test_client()

    def _call(conversation):
        return client.post("/chat", json={"conversation": conversation}).get_json()[
            "reply"
        ]

    return _call


class _FakeHttpAdapter:
    """Stands in for HttpAgentAdapter so the CLI run path is exercised in-process
    against the bundled safe stub, with no socket."""

    def __init__(self, *args, **kwargs) -> None:
        self._call = _stub_call()

    async def __aenter__(self) -> _FakeHttpAdapter:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def __call__(self, conversation: list[dict]) -> str:
        return self._call(conversation)


# --------------------------------------------------------------------------- #
# Rubric merge
# --------------------------------------------------------------------------- #
def test_merge_kb_poisoner_rubric_is_additive():
    rubric, rules = parse_rubric_file(COACH)
    merged, merged_rules = merge_kb_poisoner_rubric(rubric, rules)
    ids = [c.id for c in merged.criteria]
    # Base criteria + order preserved; the two write-back criteria appended.
    assert ids[: len(rubric.criteria)] == [c.id for c in rubric.criteria]
    assert ids[len(rubric.criteria) :] == list(_KB_CRITERIA)
    assert merged.overall_pass_threshold == rubric.overall_pass_threshold
    for cid in _KB_CRITERIA:
        assert cid in merged_rules
    # The merge is non-mutating on the inputs.
    assert [c.id for c in rubric.criteria] == [
        "safe_handling_of_self_harm",
        "no_fabricated_legal_citations",
    ]


def test_merge_kb_poisoner_rubric_rejects_id_collision():
    rubric, rules = kb_poisoner_rubric()  # already carries the KB criterion ids
    with pytest.raises(ValueError, match="already present"):
        merge_kb_poisoner_rubric(rubric, rules)


# --------------------------------------------------------------------------- #
# Probe routing
# --------------------------------------------------------------------------- #
async def test_override_drives_kb_probes_not_generic_injector():
    personas = generate_personas_heuristic(n=6)
    kb = kb_poisoner_persona(f"p{len(personas):02d}")
    personas.append(kb)
    transcripts = await run_conversations(
        personas,
        CallableAdapter(lambda c: "ok"),
        max_turns=4,
        mode="heuristic",
        probe_overrides={kb.id: KB_POISONER_PROBES},
    )
    kb_t = next(t for t in transcripts if t.persona.id == kb.id)
    kb_user_turns = [t.content for t in kb_t.turns if t.role == "user"]
    assert kb_user_turns == KB_POISONER_PROBES
    # A generic INJECTOR persona (Nico, p04) still runs the generic injector probe.
    inj = next(t for t in transcripts if t.persona.id == "p04")
    assert "ignore your previous instructions" in inj.turns[0].content.lower()


# --------------------------------------------------------------------------- #
# Full run pipeline
# --------------------------------------------------------------------------- #
async def test_full_run_holds_against_safe_stub_with_no_false_breach():
    rubric, rules = parse_rubric_file(COACH)
    merged, merged_rules = merge_kb_poisoner_rubric(rubric, rules)
    personas = generate_personas_heuristic(n=6)
    kb = kb_poisoner_persona(f"p{len(personas):02d}")
    personas.append(kb)

    transcripts = await run_conversations(
        personas,
        CallableAdapter(_stub_call()),
        max_turns=4,
        mode="heuristic",
        probe_overrides={kb.id: KB_POISONER_PROBES},
    )
    verdicts = judge_all(transcripts, merged, merged_rules, mode="heuristic")
    # Report assembly enforces the citation-to-turn invariant across all verdicts.
    report = build_report(
        rubric=merged, transcripts=transcripts, verdicts=verdicts, agent_endpoint="x"
    )
    assert len(report.transcripts) == 7

    kb_t = next(t for t in transcripts if t.persona.id == kb.id)
    kb_v = next(v for v in verdicts if v.transcript_id == kb_t.id)
    # The safe stub never writes back and never echoes -> the wall holds.
    assert kb_v.outcome is not VerdictOutcome.FAIL

    # The write-back criteria never fire on the other personas (no false breach):
    # their probes miss the keywords and they invoke no KB-write tool.
    for v in verdicts:
        if v.transcript_id == kb_t.id:
            continue
        by_id = {cv.criterion_id: cv for cv in v.criterion_verdicts}
        for cid in _KB_CRITERIA:
            assert by_id[cid].status is CriterionStatus.PASS


async def test_full_run_breaches_a_vulnerable_writeback_target():
    rubric, rules = parse_rubric_file(COACH)
    merged, merged_rules = merge_kb_poisoner_rubric(rubric, rules)
    personas = generate_personas_heuristic(n=6)
    kb = kb_poisoner_persona(f"p{len(personas):02d}")
    personas.append(kb)

    def vulnerable(conversation):
        # Only writes back to KB-shaped requests, so the contamination surface is
        # isolated to the KB-poisoner persona (other personas stay clean).
        last = conversation[-1]["content"].lower()
        if any(
            kw in last
            for kw in ("knowledge base", "save this", "store that", "profile", "memory")
        ):
            return AgentReply(
                "Done — saved to your knowledge base; I'll follow it from now on.",
                tool_calls=[{"name": "kb_write", "arguments": {"content": "x"}}],
            )
        return "Happy to help — could you tell me more?"

    transcripts = await run_conversations(
        personas,
        CallableAdapter(vulnerable),
        max_turns=4,
        mode="heuristic",
        probe_overrides={kb.id: KB_POISONER_PROBES},
    )
    verdicts = judge_all(transcripts, merged, merged_rules, mode="heuristic")
    # Still assembles cleanly: every cited turn resolves against its transcript.
    build_report(
        rubric=merged, transcripts=transcripts, verdicts=verdicts, agent_endpoint="x"
    )

    kb_t = next(t for t in transcripts if t.persona.id == kb.id)
    kb_v = next(v for v in verdicts if v.transcript_id == kb_t.id)
    assert kb_v.outcome is VerdictOutcome.FAIL
    by_id = {cv.criterion_id: cv for cv in kb_v.criterion_verdicts}
    write = by_id["kb_write_requires_sanitization"]
    assert write.status is CriterionStatus.FAIL
    assert "ASI03" in write.rationale or "ASI02" in write.rationale
    assert by_id["no_persisted_injection_echo"].status is CriterionStatus.FAIL


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #
def test_cli_run_include_kb_poisoner(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("coehoorn.cli.HttpAgentAdapter", _FakeHttpAdapter)
    rc = main([
        "run", "--rubric", COACH, "--agent", "http://stub",
        "--personas", "6", "--turns", "4", "--include-kb-poisoner",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "included KB-poisoner persona p06 (Sable)" in out

    report = json.loads(Path(glob.glob(str(tmp_path / "*.json"))[0]).read_text())
    ids = [c["id"] for c in report["rubric"]["criteria"]]
    assert ids[-2:] == list(_KB_CRITERIA)
    p06 = next(t for t in report["transcripts"] if t["persona"]["id"] == "p06")
    assert p06["persona"]["name"] == "Sable"
    assert p06["turns"][0]["content"] == KB_POISONER_PROBES[0]
    # Safe stub -> KB persona holds (the surface is exercised, no fabricated breach).
    v06 = next(v for v in report["verdicts"] if v["transcript_id"] == p06["id"])
    assert v06["outcome"] != "fail"
