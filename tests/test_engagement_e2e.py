"""One engagement, end to end, against a real HTTP target over a real socket.

This is the test that answers the repo's oldest fair criticism: *every catch is
against your own deliberately-flawed stub, and nothing external was ever
sieged.* It does not answer it by claiming a live siege happened — no third
party is dialled here, and no model is called. It answers the *structural*
half: there is now an engagement definition, a scope enforced in code, a
target-agnostic runner that speaks to whatever HTTP endpoint the engagement
points at, and a findings artifact on disk.

So the target is a genuinely separate process-boundary — a stdlib HTTP server
bound to an ephemeral port, spoken to over TCP by the real
``HttpAgentAdapter``, not an in-process callable. What is proven is the wire,
the scope gate, the judge, and the artifact. What is *not* proven is that
Coehoorn finds anything interesting in someone else's real agent; the rehearsal
target's weakness is deliberate and documented, and catching it demonstrates
plumbing, not prowess.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from coehoorn.engagement import EngagementRefused, RefusalRule, load_engagement, run_engagement

_ROOT = Path(__file__).resolve().parent.parent
_STUB_DIR = _ROOT / "apps" / "approval-stub"
sys.path.insert(0, str(_STUB_DIR))

from approval_surface import make_server  # noqa: E402

_REHEARSAL = _ROOT / "docs" / "engagements" / "local-approval-rehearsal.yaml"
_FARTHING = _ROOT / "docs" / "engagements" / "farthing-approval-surface.yaml"


@pytest.fixture
def approval_surface():
    """A real HTTP server on 127.0.0.1:<ephemeral>, torn down after the test."""
    server = make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield f"http://{host}:{port}/decide"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


async def test_an_engagement_produces_a_cited_findings_artifact(approval_surface, tmp_path):
    engagement = load_engagement(_REHEARSAL)
    result = await run_engagement(engagement, target=approval_surface, out_dir=tmp_path)

    # It actually talked to the server: every approach came back.
    assert result.transcripts == engagement.personas
    assert result.approaches_attempted == engagement.personas
    assert result.partial is False

    # Findings are real and cited.
    assert result.findings, "the rehearsal target's documented weakness was not found"
    criteria = {f.criterion_id for f in result.findings}
    assert "refund_approved_without_human_authorization" in criteria
    assert "no_policy_disclosure_under_injection" in criteria

    # Three artifacts on disk, and the record is the engagement-shaped one.
    for path in (result.report_json, result.report_html, result.record_json):
        assert path.exists() and path.stat().st_size > 0
    record = json.loads(result.record_json.read_text())
    assert record["engagement_id"] == engagement.id
    assert record["authorized"] is True
    assert record["method"]["judge"].startswith("offline heuristic")
    assert record["scope"]["allow_private_addresses"] is True
    assert len(record["findings"]) == len(result.findings)

    # Every citation resolves against the transcript sitting beside it. A
    # finding you cannot click through to is an opinion.
    report = json.loads(result.report_json.read_text())
    turns_by_persona = {
        t["persona"]["id"]: {turn["index"] for turn in t["turns"]}
        for t in report["transcripts"]
    }
    for finding in record["findings"]:
        assert finding["cited_turn_index"] in turns_by_persona[finding["persona_id"]]


async def test_the_wall_holds_where_it_holds(approval_surface, tmp_path):
    # The honest half of the report: an engagement that flagged every approach
    # would be a rubric that always fires, not a finding. The rehearsal target
    # refuses the pressure approaches, and the record must show that.
    engagement = load_engagement(_REHEARSAL)
    result = await run_engagement(engagement, target=approval_surface, out_dir=tmp_path)
    breached = {f.persona_id for f in result.findings}
    assert breached, "no breach at all would mean the harness caught nothing"
    assert breached != {"p00", "p01", "p02", "p03", "p04", "p05"}, (
        "every approach breaching is the signature of a rubric that always "
        f"fires; got {breached}"
    )
    report = json.loads(result.report_json.read_text())
    assert report["pass_rate"] > 0


async def test_a_credential_in_the_target_url_never_reaches_an_artifact(
    approval_surface, tmp_path
):
    # Operators paste credentialed URLs. That is the Phase-0 leak class, and
    # the engagement record is a client deliverable.
    host_port = approval_surface.removeprefix("http://").split("/")[0]
    dirty = f"http://siege:hunter2@{host_port}/decide?api_key=abc123secret"
    engagement = load_engagement(_REHEARSAL)
    result = await run_engagement(engagement, target=dirty, out_dir=tmp_path)

    assert "hunter2" not in result.target
    assert "abc123secret" not in result.target
    for path in (result.report_json, result.report_html, result.record_json):
        text = path.read_text()
        assert "hunter2" not in text, path.name
        assert "abc123secret" not in text, path.name
    # The host is not a secret — which target was besieged is the record.
    assert host_port.split(":")[0] in result.target


async def test_an_out_of_scope_target_is_refused_before_the_socket(tmp_path):
    engagement = load_engagement(_REHEARSAL)
    with pytest.raises(EngagementRefused) as exc:
        await run_engagement(
            engagement, target="http://169.254.169.254/decide", out_dir=tmp_path
        )
    assert exc.value.rule is RefusalRule.HOST
    assert not list(tmp_path.iterdir()), "a refused engagement wrote artifacts"


async def test_the_first_real_target_is_defined_but_not_authorized(tmp_path):
    # The Farthing engagement is committed as a *definition*: scope agreed in
    # code, authorization not on file. It must be impossible to run it by
    # accident, and the repo's honesty depends on that staying true.
    engagement = load_engagement(_FARTHING)
    assert engagement.authorized is False
    with pytest.raises(EngagementRefused) as exc:
        await run_engagement(
            engagement, target="https://farthing.invalid/approvals", out_dir=tmp_path
        )
    assert exc.value.rule is RefusalRule.AUTHORIZED
    assert not list(tmp_path.iterdir())


def test_both_committed_engagements_point_at_files_that_exist():
    for path in (_REHEARSAL, _FARTHING):
        engagement = load_engagement(path)
        assert engagement.rubric_path().exists(), engagement.rubric_path()
        assert engagement.roe_path().exists(), engagement.roe_path()
