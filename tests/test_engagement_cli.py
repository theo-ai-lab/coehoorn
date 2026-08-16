"""`coehoorn engage` — the one command a reader runs.

Discovery semantics, matching `coehoorn run`: findings are the product, so a
run that finds breaches still exits 0. What exits non-zero is a *refusal* —
an unauthorized engagement or an out-of-scope target — because that is the
operator having been stopped, not the target having been cleared.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from coehoorn.cli import build_parser, main

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "apps" / "approval-stub"))

from approval_surface import make_server  # noqa: E402

_REHEARSAL = str(_ROOT / "docs" / "engagements" / "local-approval-rehearsal.yaml")
_FARTHING = str(_ROOT / "docs" / "engagements" / "farthing-approval-surface.yaml")


@pytest.fixture
def approval_surface():
    server = make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{server.server_address[0]}:{server.server_address[1]}/decide"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_engage_is_a_registered_subcommand():
    args = build_parser().parse_args(["engage", "--engagement", _REHEARSAL])
    assert args.cmd == "engage"


def test_engage_emits_a_scriptable_json_summary(approval_surface, tmp_path, capsys):
    code = main([
        "engage", "--engagement", _REHEARSAL,
        "--target", approval_surface, "--out", str(tmp_path), "--json",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["engagement_id"] == "local-approval-rehearsal"
    assert payload["authorized"] is True
    assert payload["approaches_attempted"] == 6
    assert payload["findings"] >= 1
    assert payload["partial"] is False
    assert Path(payload["record_json"]).exists()
    assert Path(payload["report_html"]).exists()


def test_findings_alone_do_not_fail_the_command_but_may_be_opted_into(
    approval_surface, tmp_path
):
    common = ["engage", "--engagement", _REHEARSAL, "--target", approval_surface, "--json"]
    assert main([*common, "--out", str(tmp_path / "a")]) == 0
    assert main([*common, "--out", str(tmp_path / "b"), "--fail-on-finding"]) == 1


def test_an_unauthorized_engagement_exits_two_and_names_the_rule(tmp_path, capsys):
    code = main([
        "engage", "--engagement", _FARTHING,
        "--target", "https://approvals.farthing.invalid/approvals",
        "--out", str(tmp_path),
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "engagement.authorized" in err
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


def test_an_out_of_scope_target_exits_two_and_names_the_rule(tmp_path, capsys):
    code = main([
        "engage", "--engagement", _REHEARSAL,
        "--target", "http://169.254.169.254/decide",
        "--out", str(tmp_path),
    ])
    assert code == 2
    assert "scope.allowed_hosts" in capsys.readouterr().err


def test_a_refusal_message_does_not_echo_the_credential_it_refused(tmp_path, capsys):
    code = main([
        "engage", "--engagement", _REHEARSAL,
        "--target", "http://siege:hunter2@evil.example/decide?api_key=abc123secret",
        "--out", str(tmp_path),
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "hunter2" not in err
    assert "abc123secret" not in err
    assert "evil.example" in err


def test_a_missing_engagement_file_is_a_clean_error_not_a_traceback(tmp_path, capsys):
    code = main(["engage", "--engagement", str(tmp_path / "nope.yaml"), "--out", str(tmp_path)])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_no_target_anywhere_is_a_clean_error(tmp_path, capsys, monkeypatch):
    for var in ("AGENT_ENDPOINT", "COEHOORN_AGENT_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    code = main(["engage", "--engagement", _REHEARSAL, "--out", str(tmp_path)])
    assert code == 2
    assert "scope.url" in capsys.readouterr().err
