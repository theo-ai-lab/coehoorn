"""Assembles transcripts + verdicts + rubric into a single Report.

The Report is the only artifact written to disk. Schema invariants
(criterion coverage, cited-index validity, archetype keys, transcript/
verdict 1:1) are enforced by `Report`'s Pydantic validators — this
module just wires the inputs together and writes the JSON.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .schemas import CriterionStatus, Report, Rubric, Transcript, Verdict


def build_report(
    *,
    rubric: Rubric,
    transcripts: Iterable[Transcript],
    verdicts: Iterable[Verdict],
    agent_endpoint: str,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    run_id: str | None = None,
) -> Report:
    created = created_at or datetime.now(timezone.utc)
    completed = completed_at or datetime.now(timezone.utc)
    # run_id is left to Report's uuid4 default for live runs; the sample
    # builder pins it (with fixed timestamps) so the committed sample report
    # is byte-reproducible — the determinism the tool claims, applied to the
    # tool's own artifact.
    fields: dict = dict(
        created_at=created,
        completed_at=completed,
        agent_endpoint=agent_endpoint,
        rubric=rubric,
        transcripts=list(transcripts),
        verdicts=list(verdicts),
    )
    if run_id is not None:
        fields["run_id"] = run_id
    return Report(**fields)


def pin_report_timestamps(
    report: Report,
    *,
    created_at: datetime,
    completed_at: datetime,
    run_id: str | None = None,
) -> Report:
    """Return a copy of ``report`` with all provenance timestamps pinned.

    A run's substantive content — personas, messages, verdicts, citations —
    is fully determined by the seed in heuristic mode. Its provenance
    (per-transcript wall-clock and the run id) is not. To produce a
    byte-reproducible canonical artifact (the committed sample, or a gold
    file for regression comparison), pin the provenance and leave the
    substance untouched. The result is re-validated, so the timestamps must
    still satisfy ``completed_at >= started_at``.
    """
    transcripts = [
        t.model_copy(update={"started_at": created_at, "completed_at": completed_at})
        for t in report.transcripts
    ]
    update: dict = {
        "created_at": created_at,
        "completed_at": completed_at,
        "transcripts": transcripts,
    }
    if run_id is not None:
        update["run_id"] = run_id
    pinned = report.model_copy(update=update)
    # Re-validate so the pin can't silently produce an invalid report.
    return Report.model_validate(pinned.model_dump())


def write_report_json(report: Report, path: str | Path) -> Path:
    """Write a Report to disk as JSON. Returns the resolved Path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2))
    return out


def load_report_json(path: str | Path) -> Report:
    return Report.model_validate_json(Path(path).read_text())


def compare_to_expected(
    report: Report, expected: dict[str, list[str]]
) -> dict[str, dict]:
    """Compare a Report's per-(persona, criterion) judgments to expectations.

    `expected` is {persona_id: [criterion_id, ...]} — the criteria each
    persona's transcript is expected to FAIL. Every other (persona, criterion)
    cell in the rubric grid is an expected pass. The full confusion grid is
    classified per cell:

      - FAIL where a failure was expected -> true positive
      - FAIL where none was expected      -> false positive
      - PASS where a failure was expected -> false negative
      - PASS where none was expected      -> true negative
      - ABSTAIN (either way)              -> excluded from the matrix,
                                             tracked under "abstained"

    Abstentions are excluded rather than scored: a judge that declined to
    decide should not be charged a false negative for it (that is what the
    abstention rate, reported separately, is for).
    """
    all_criteria = [c.id for c in report.rubric.criteria]
    criteria_set = set(all_criteria)
    persona_id_by_tid = {t.id: t.persona.id for t in report.transcripts}
    status_by_persona: dict[str, dict[str, CriterionStatus]] = {}
    for v in report.verdicts:
        pid = persona_id_by_tid.get(v.transcript_id)
        if pid is None:
            continue
        status_by_persona[pid] = {
            cv.criterion_id: cv.status for cv in v.criterion_verdicts
        }

    diff: dict[str, dict] = {}
    all_personas = set(expected.keys()) | set(status_by_persona.keys())
    for pid in sorted(all_personas):
        exp = set(expected.get(pid, []))
        statuses = status_by_persona.get(pid, {})
        tp, fp, fn, tn, abstained = [], [], [], [], []
        for cid in all_criteria:
            status = statuses.get(cid)
            expected_fail = cid in exp
            if status is CriterionStatus.FAIL:
                (tp if expected_fail else fp).append(cid)
            elif status is CriterionStatus.PASS:
                (fn if expected_fail else tn).append(cid)
            elif status is CriterionStatus.ABSTAIN:
                abstained.append(cid)
        # A failure expected on a criterion the rubric doesn't contain is a
        # detection the system can never produce — count it honestly as missed.
        fn.extend(sorted(exp - criteria_set))
        diff[pid] = {
            "expected_failures": sorted(exp),
            "actual_failures": sorted(tp + fp),
            "abstained": sorted(abstained),
            "true_positives": sorted(tp),
            "false_positives": sorted(fp),
            "false_negatives": sorted(fn),
            "true_negatives": sorted(tn),
            "match": len(fp) == 0 and len(fn) == 0,
        }
    return diff


def write_comparison_json(diff: dict[str, dict], path: str | Path) -> Path:
    from .metrics import metrics_from_comparison

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _total(key: str) -> int:
        return sum(len(d.get(key, [])) for d in diff.values())

    summary = {
        "metrics": metrics_from_comparison(diff).model_dump(mode="json"),
        "summary": {
            "total_personas": len(diff),
            "exact_matches": sum(1 for d in diff.values() if d["match"]),
            "total_true_positives": _total("true_positives"),
            "total_false_positives": _total("false_positives"),
            "total_false_negatives": _total("false_negatives"),
            "total_true_negatives": _total("true_negatives"),
            "total_abstained": _total("abstained"),
        },
        "personas": diff,
    }
    out.write_text(json.dumps(summary, indent=2))
    return out
