"""Pin the release workflow's trigger and publish-safety contract.

The release workflow is the one workflow whose misfire is unrecoverable: PyPI
never accepts the same version twice, so a bad publish cannot be replaced. These
tests pin the properties that make it safe — fires only on a version tag (never
a branch push), publishes via OIDC trusted publishing (no stored token to leak),
verifies the tag matches the packaged version before anything uploads, and
proves the PUBLISHED artifact works in a clean environment that never checks out
the repo tree. A later edit that widens the trigger, pastes a token, or quietly
drops the clean-env property fails the suite loudly here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> dict[str, Any]:
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in _steps(job))


def test_release_workflow_exists() -> None:
    assert _WORKFLOW.is_file(), "release readiness requires .github/workflows/release.yml"


def test_fires_only_on_version_tags_never_on_branch_pushes() -> None:
    wf = _workflow()
    # PyYAML 1.1 parses a bare `on:` key as boolean True.
    triggers = wf[True]
    assert set(triggers) == {"push"}, (
        "release must have no trigger besides push; a pull_request/schedule/"
        f"dispatch trigger could publish from unreviewed state: {set(triggers)}"
    )
    push = triggers["push"]
    assert set(push) == {"tags"}, (
        "the push trigger must carry ONLY a tags filter — adding a branches key "
        f"would make branch pushes eligible to publish: {set(push)}"
    )
    assert push["tags"] == ["v*.*.*"], push["tags"]


def test_default_token_is_read_only() -> None:
    wf = _workflow()
    assert wf.get("permissions") == {"contents": "read"}


def test_publish_uses_oidc_trusted_publishing_not_a_stored_token() -> None:
    jobs = _workflow()["jobs"]
    publish = jobs["publish"]
    assert publish.get("permissions") == {"id-token": "write"}, (
        "publish needs exactly id-token: write for OIDC and nothing else"
    )
    assert publish.get("environment", {}).get("name") == "pypi"
    uses = [step.get("uses", "") for step in _steps(publish)]
    assert any(u.startswith("pypa/gh-action-pypi-publish@") for u in uses), uses
    for step in _steps(publish):
        with_block = step.get("with") or {}
        assert "password" not in with_block, (
            "trusted publishing must not carry a password/token input"
        )


def test_tag_must_match_packaged_version_before_anything_uploads() -> None:
    jobs = _workflow()["jobs"]
    build = jobs["build"]
    run_text = _run_text(build)
    assert "pyproject.toml" in run_text and "GITHUB_REF_NAME" in run_text, (
        "the build job must compare the pushed tag against pyproject's version"
    )
    assert jobs["publish"].get("needs") == "build"


def test_wheel_is_smoked_before_the_unrecoverable_upload() -> None:
    build = _workflow()["jobs"]["build"]
    run_text = _run_text(build)
    assert "dist/*.whl" in run_text and "--version" in run_text, (
        "the built wheel must install and run in a fresh venv BEFORE publish; "
        "a broken artifact found after upload can never be re-uploaded"
    )


def test_install_smoke_runs_the_published_wheel_in_a_clean_env() -> None:
    jobs = _workflow()["jobs"]
    smoke = jobs["install-smoke"]
    assert smoke.get("needs") == "publish"
    for step in _steps(smoke):
        assert not step.get("uses", "").startswith("actions/checkout"), (
            "the install smoke must never check out the repo: it proves the "
            "PUBLISHED artifact alone delivers the README's install commands"
        )
    run_text = _run_text(smoke)
    assert "pip" in run_text and "coehoorn[mcp]==" in run_text
    assert "--version" in run_text
    assert "mcp-siege" in run_text


def test_no_template_interpolation_of_refs_into_run_scripts() -> None:
    # ${{ github.ref* }} inlined into a run script is a shell-injection seam
    # (a tag name may contain shell metacharacters); the default-env form
    # $GITHUB_REF_NAME expands as data, not code.
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "${{ github.ref" not in text
