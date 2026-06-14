"""Machine-readable CI/CD outputs: SARIF and JUnit.

Coehoorn already emits a validated ``report.json`` and CI-friendly exit codes; this
adds the two formats security and CI pipelines actually ingest:

* **SARIF 2.1.0** — the Static Analysis Results Interchange Format, which GitHub's
  code-scanning tab and most security platforms consume. Each breach becomes a
  result located at the cited transcript turn.
* **JUnit XML** — the de-facto test-report format. Each (persona, criterion) cell
  becomes a test case; a breach is a failure.

Both are pure-stdlib (no new dependency) and derive entirely from a finished
``Report``, so the cited-evidence guarantee carries straight into CI.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from . import __version__
from .schemas import CriterionStatus, Report, VerdictOutcome

_SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_INFO_URI = "https://github.com/theo-ai-lab/coehoorn"

# Map a breach to a SARIF severity. A critical criterion is an "error"; a
# non-critical one is a "warning" (the gate still fails on either via exit code).
def _sarif_level(critical: bool) -> str:
    return "error" if critical else "warning"


def report_to_sarif(report: Report) -> dict:
    """Build a SARIF 2.1.0 document from a finished Report.

    Rules = the rubric criteria. Results = the breaches, each anchored to the
    transcript (the "artifact") at the cited turn (the "line").
    """
    critical_by_id = {c.id: c.failure_is_critical for c in report.rubric.criteria}
    rules = [
        {
            "id": c.id,
            "name": c.id,
            "shortDescription": {"text": c.description.strip()[:200]},
            "properties": {"weight": c.weight, "critical": c.failure_is_critical},
        }
        for c in report.rubric.criteria
    ]
    persona_by_tid = {t.id: t.persona for t in report.transcripts}

    results = []
    for v in report.verdicts:
        if v.outcome is not VerdictOutcome.FAIL:
            continue
        persona = persona_by_tid.get(v.transcript_id)
        for cv in v.criterion_verdicts:
            if cv.status is not CriterionStatus.FAIL:
                continue
            results.append({
                "ruleId": cv.criterion_id,
                "level": _sarif_level(critical_by_id.get(cv.criterion_id, False)),
                "message": {"text": cv.rationale.strip()},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f"transcripts/{v.transcript_id}.txt"},
                        # SARIF lines are 1-based; the cited turn index is 0-based.
                        "region": {"startLine": (cv.cited_turn_index or 0) + 1},
                    }
                }],
                "properties": {
                    "archetype": persona.archetype.value if persona else None,
                    "persona": persona.id if persona else None,
                    "worst_moment": v.worst_moment_turn_index,
                },
            })

    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "Coehoorn",
                "informationUri": _INFO_URI,
                "version": __version__,
                "rules": rules,
            }},
            "results": results,
        }],
    }


def report_to_junit(report: Report) -> str:
    """Build a JUnit XML string: one test case per (persona, criterion) cell."""
    n_tests = 0
    n_failures = 0
    n_skipped = 0
    persona_by_tid = {t.id: t.persona for t in report.transcripts}
    suite = ET.Element("testsuite", name="coehoorn-siege")

    for v in report.verdicts:
        persona = persona_by_tid.get(v.transcript_id)
        pid = persona.id if persona else v.transcript_id
        classname = persona.archetype.value if persona else "siege"
        for cv in v.criterion_verdicts:
            n_tests += 1
            case = ET.SubElement(
                suite, "testcase", classname=classname, name=f"{pid}::{cv.criterion_id}"
            )
            if cv.status is CriterionStatus.FAIL:
                n_failures += 1
                fail = ET.SubElement(
                    case, "failure",
                    message=f"breach at turn {cv.cited_turn_index}",
                )
                fail.text = cv.rationale.strip()
            elif cv.status is CriterionStatus.ABSTAIN:
                n_skipped += 1
                ET.SubElement(case, "skipped", message="judge abstained")

    suite.set("tests", str(n_tests))
    suite.set("failures", str(n_failures))
    suite.set("skipped", str(n_skipped))
    suites = ET.Element("testsuites", name="coehoorn", tests=str(n_tests), failures=str(n_failures))
    suites.append(suite)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(suites, encoding="unicode")


def write_sarif(report: Report, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report_to_sarif(report), indent=2))
    return out


def write_junit(report: Report, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_to_junit(report))
    return out
