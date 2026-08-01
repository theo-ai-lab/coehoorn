"""No check may report success for work it did not do.

The external siege used to guard itself with a first *step* that set
`configured=false` and an `if:` on every following step. GitHub scores that
job **success**: 17 of 17 scheduled runs went green having executed nothing but
the guard, and the surviving `pull_request` trigger still mints a fresh green
no-op check on every PR. In a harness whose product claim is that a dishonest
verdict should be structurally unrepresentable, that signal is the worst kind
of lie — a green tick for a siege that never happened.

The fix is a job-level gate: an unconfigured siege must SKIP. These tests pin
the shape, for this workflow and for any future one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _ROOT / ".github" / "workflows"
_EXTERNAL = _WORKFLOW_DIR / "external-siege.yml"


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", []) or []


def _is_guard_gated(step: dict[str, Any]) -> bool:
    """Does this step's condition depend on another step *in the same job*?"""
    cond = str(step.get("if", ""))
    return "steps." in cond and ".outputs." in cond


@pytest.mark.parametrize(
    "workflow_path", sorted(_WORKFLOW_DIR.glob("*.yml")), ids=lambda p: p.name
)
def test_no_job_can_pass_having_run_only_its_guard(workflow_path: Path) -> None:
    # The general lock, not just a fix for one file: a job whose real work is
    # conditioned on a same-job step output reports SUCCESS when the condition
    # is false. Gate at the job level (`if:` on a needs.<job>.outputs.*) so the
    # run is scored SKIPPED — an honest "this did not happen".
    jobs = _load(workflow_path).get("jobs", {})
    for job_name, job in jobs.items():
        gated = [s for s in _steps(job) if _is_guard_gated(s)]
        assert not gated, (
            f"{workflow_path.name}:{job_name} gates "
            f"{[s.get('name') or s.get('uses') for s in gated]} on a same-job "
            "step output; that job reports success when the guard is false. "
            "Move the guard to a job-level if:."
        )


def test_external_siege_skips_instead_of_passing_when_unconfigured() -> None:
    jobs = _load(_EXTERNAL)["jobs"]
    siege = jobs["external-siege"]
    condition = str(siege.get("if", ""))
    assert "needs." in condition and ".outputs." in condition, (
        "the siege job must carry a job-level if: on a preflight output so an "
        f"unconfigured run is SKIPPED, not passed; got {condition!r}"
    )
    guard_job = siege.get("needs")
    guard_job = guard_job[0] if isinstance(guard_job, list) else guard_job
    assert guard_job in jobs, f"the siege must depend on the guard job; got {guard_job!r}"
    assert f"needs.{guard_job}.outputs" in condition


def test_the_guard_job_resolves_both_the_secret_and_the_variable() -> None:
    # Job-level `if:` cannot read `secrets`, which is why the guard is a job at
    # all. It must still honour both configuration routes documented in the
    # header (a secret for a private URL, a repo variable for a public one).
    jobs = _load(_EXTERNAL)["jobs"]
    siege_condition = str(jobs["external-siege"].get("if", ""))
    guard_name = siege_condition.split("needs.")[1].split(".outputs")[0]
    guard = jobs[guard_name]
    assert guard.get("outputs"), "the guard job must expose its verdict as an output"
    text = yaml.safe_dump(guard)
    assert "secrets.AGENT_ENDPOINT" in text
    assert "vars.AGENT_ENDPOINT" in text


def test_the_siege_still_does_the_work_it_claims() -> None:
    # The gate must not have been "fixed" by deleting the siege.
    siege = _load(_EXTERNAL)["jobs"]["external-siege"]
    steps = _steps(siege)
    uses = " ".join(s.get("uses", "") for s in steps)
    runs = "\n".join(s.get("run", "") for s in steps)
    assert "actions/checkout@" in uses
    assert "coehoorn run" in runs and "--emit sarif,junit" in runs
    assert "upload-sarif@" in uses


def test_pull_request_trigger_is_only_useful_when_configured() -> None:
    # Keeping the PR trigger is fine — a configured repo gets its cited-breach
    # comment. What may not survive is a PR check that goes green having done
    # nothing, which the job-level gate above now prevents.
    triggers = _load(_EXTERNAL)[True]  # PyYAML 1.1 parses bare `on:` as True
    assert "pull_request" in triggers
    comment = next(
        s for s in _steps(_load(_EXTERNAL)["jobs"]["external-siege"])
        if "github-script" in s.get("uses", "")
    )
    assert "github.event_name == 'pull_request'" in str(comment.get("if", ""))
