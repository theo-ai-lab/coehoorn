"""SARIF + JUnit CI outputs derive correctly from a Report.

The cited-evidence guarantee must carry into CI: a SARIF result is located at the
exact cited turn, and a JUnit failure exists for every breach.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from coehoorn.aggregator import build_report
from coehoorn.outputs import (
    report_to_junit,
    report_to_sarif,
    write_junit,
    write_sarif,
)
from coehoorn.schemas import (
    Archetype,
    ConversationTurn,
    Criterion,
    CriterionStatus,
    CriterionVerdict,
    Persona,
    Rubric,
    Transcript,
    Verdict,
    VerdictOutcome,
)

_TS = datetime(2026, 5, 17, tzinfo=UTC)


def _t(pid: str, arch: Archetype) -> Transcript:
    return Transcript(
        id=f"t-{pid}",
        persona=Persona(id=pid, archetype=arch, name="n", description="d"),
        turns=[
            ConversationTurn(index=i, role="user" if i % 2 == 0 else "assistant", content="c")
            for i in range(4)
        ],
        started_at=_TS, completed_at=_TS,
    )


def _report():
    rubric = Rubric(
        criteria=[
            Criterion(id="x", description="no fabrication", failure_is_critical=True),
            Criterion(id="y", description="be safe"),
        ],
        overall_pass_threshold=1.0,
    )
    t0, t1 = _t("p00", Archetype.EDGE_CASE), _t("p01", Archetype.AMBIGUOUS)
    v0 = Verdict(
        transcript_id="t-p00",
        criterion_verdicts=[
            CriterionVerdict(criterion_id="x", status=CriterionStatus.FAIL, confidence=0.9,
                             cited_turn_index=3, rationale="fabricated a citation"),
            CriterionVerdict(criterion_id="y", status=CriterionStatus.PASS,
                             confidence=0.9, rationale="ok"),
        ],
        outcome=VerdictOutcome.FAIL, worst_moment_turn_index=3,
    )
    v1 = Verdict(
        transcript_id="t-p01",
        criterion_verdicts=[
            CriterionVerdict(criterion_id="x", status=CriterionStatus.PASS,
                             confidence=0.9, rationale="ok"),
            CriterionVerdict(criterion_id="y", status=CriterionStatus.PASS,
                             confidence=0.9, rationale="ok"),
        ],
        outcome=VerdictOutcome.PASS, worst_moment_turn_index=None,
    )
    return build_report(rubric=rubric, transcripts=[t0, t1], verdicts=[v0, v1], agent_endpoint="http://x")


def test_sarif_locates_breach_at_cited_turn():
    s = report_to_sarif(_report())
    assert s["version"] == "2.1.0"
    driver = s["runs"][0]["tool"]["driver"]
    assert driver["name"] == "Coehoorn"
    assert {r["id"] for r in driver["rules"]} == {"x", "y"}
    results = s["runs"][0]["results"]
    assert len(results) == 1  # one breach
    r = results[0]
    assert r["ruleId"] == "x"
    assert r["level"] == "error"  # x is the critical criterion
    # cited turn 3 (0-based) -> SARIF line 4 (1-based)
    assert r["locations"][0]["physicalLocation"]["region"]["startLine"] == 4
    assert r["properties"]["archetype"] == "edge_case"


def test_junit_one_case_per_cell_failure_per_breach():
    root = ET.fromstring(report_to_junit(_report()))
    suite = root.find("testsuite")
    assert suite.get("tests") == "4"  # 2 personas x 2 criteria
    assert suite.get("failures") == "1"
    failures = root.findall(".//failure")
    assert len(failures) == 1
    assert "fabricated" in failures[0].text


def test_write_both_files(tmp_path):
    report = _report()
    sp = write_sarif(report, tmp_path / "r.sarif.json")
    jp = write_junit(report, tmp_path / "r.junit.xml")
    assert json.loads(sp.read_text())["version"] == "2.1.0"
    assert ET.fromstring(jp.read_text()).find("testsuite").get("failures") == "1"
