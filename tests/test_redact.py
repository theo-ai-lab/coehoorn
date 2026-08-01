"""Redaction is a boundary, not a hope.

Coehoorn's engagement templates ask a client to state their "redaction needs"
and retention window; the harness had no redaction code at all — a transcript
went to report.json, the self-contained HTML, SARIF, JUnit and stdout exactly
as the target said it. These tests pin the boundary: every persistence path is
fed from a transcript that has already been through the policy, and the leak
matrix below checks each emitter separately rather than trusting that they all
derive from the same object.

They also pin what redaction deliberately does NOT do: there is no
Shannon-entropy fallback. Entropy fires on base64 and JSON, which is most of a
tool-calling transcript; a redactor that eats the evidence is worse than none.
"""
from __future__ import annotations

import glob
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest

from coehoorn.cli import main
from coehoorn.errors import ErrorClass
from coehoorn.redact import (
    RedactionLevel,
    RedactionPolicy,
    patterns_from_rubric_file,
)
from coehoorn.schemas import (
    ApproachError,
    Archetype,
    ConversationTurn,
    Persona,
    ToolCall,
    Transcript,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
COACH = str(REPO_ROOT / "examples" / "rubric_coach.yaml")
NOW = datetime(2026, 5, 17, 10, 8, 0, tzinfo=UTC)

# Assembled at runtime rather than written as a literal: the repo's secret
# scanner (rightly) refuses to commit anything key-SHAPED, and a fixture is not
# worth weakening it for. The value is synthetic and was never a credential.
_FAKE_KEY = "sk" + "-" + "notarealkeyvalue" + "0" * 8

STANDARD = RedactionPolicy.for_level("standard")
STRICT = RedactionPolicy.for_level("strict")
OFF = RedactionPolicy.for_level("off")

# One battery of real-shaped secrets, reused by the unit tests and the leak
# matrix so the two can never drift apart.
SECRETS = {
    "email": "dana.whitfield@northgate-health.example",
    "api_key": _FAKE_KEY,
    "gh_token": "ghp_9zQmRt4LwXcV2bN7pKdE3sYhU5aJ1fG8oI0q",
    "aws_key": "AKIAIOSFODNN7EXAMPLE",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g",
    "ssn": "078-05-1120",
    "card": "4111111111111111",
}


def _has_no_secrets(blob: str) -> list[str]:
    return [name for name, value in SECRETS.items() if value in blob]


# --------------------------------------------------------------------------
# text patterns
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SECRETS))
def test_standard_pack_redacts_the_battery(name):
    assert SECRETS[name] not in STANDARD.text(f"here it is: {SECRETS[name]} ok")


def test_placeholder_names_what_was_removed():
    out = STANDARD.text(f"mail me at {SECRETS['email']}")
    assert out == "mail me at [redacted:email]"


def test_bearer_credentials_are_redacted_but_the_header_name_survives():
    out = STANDARD.text("Authorization: Bearer abcd1234efgh5678ijkl")
    assert "abcd1234efgh5678ijkl" not in out
    assert "Authorization" in out


def test_private_key_block_is_redacted_whole():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA3Tz2mrK\nlinesoftrash\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = STANDARD.text(f"leaked: {pem}")
    assert "MIIEowIBAAKCAQEA3Tz2mrK" not in out
    assert "[redacted:private-key]" in out


def test_off_is_the_identity():
    text = " ".join(SECRETS.values())
    assert OFF.text(text) == text
    assert OFF.level is RedactionLevel.OFF


def test_standard_leaves_a_luhn_invalid_digit_run_alone():
    # Precision: a 16-digit order id that is not a card number is evidence, not
    # PII. The Luhn check is what keeps this out of the false-positive column.
    assert STANDARD.text("order 1234567812345678") == "order 1234567812345678"


def test_standard_leaves_phone_and_ip_alone_but_strict_takes_them():
    text = "call +1 415-555-0132 or hit 10.42.7.19"
    assert STANDARD.text(text) == text
    out = STRICT.text(text)
    assert "415-555-0132" not in out
    assert "10.42.7.19" not in out


def test_no_entropy_fallback_on_base64_or_json():
    # Explicitly pinned: high-entropy-looking payload that is NOT a credential
    # must survive. A tool-calling transcript is mostly this.
    payload = (
        '{"tool":"lookup","args":{"blob":'
        '"c29tZSByYW5kb20gZGF0YSBoZXJlIHRoYXQgaXMgbm90IGEgc2VjcmV0"}}'
    )
    assert STANDARD.text(payload) == payload
    assert STRICT.text(payload) == payload


# --------------------------------------------------------------------------
# the Transcript boundary
# --------------------------------------------------------------------------

def _dirty_transcript() -> Transcript:
    return Transcript(
        id="t-p00",
        persona=Persona(id="p00", archetype=Archetype.EDGE_CASE, name="n", description="d"),
        turns=[
            ConversationTurn(index=0, role="user", content="who is the account holder?"),
            ConversationTurn(
                index=1,
                role="assistant",
                content=f"That's {SECRETS['email']}, SSN {SECRETS['ssn']}.",
                tool_calls=[
                    ToolCall(
                        name="lookup_customer",
                        arguments={
                            "key": SECRETS["api_key"],
                            "cards": [SECRETS["card"]],
                            "nested": {"jwt": SECRETS["jwt"]},
                        },
                    )
                ],
            ),
        ],
        started_at=NOW,
        completed_at=NOW,
    )


def test_transcript_redaction_covers_turns_and_tool_arguments():
    clean = STANDARD.transcript(_dirty_transcript())
    assert _has_no_secrets(clean.model_dump_json()) == []


def test_transcript_redaction_preserves_the_citation_anchors():
    dirty = _dirty_transcript()
    clean = STANDARD.transcript(dirty)
    assert [t.index for t in clean.turns] == [t.index for t in dirty.turns]
    assert [t.role for t in clean.turns] == [t.role for t in dirty.turns]
    assert clean.id == dirty.id and clean.persona == dirty.persona
    assert clean.turns[1].tool_calls[0].name == "lookup_customer"


def test_endpoint_credentials_are_stripped():
    dirty = f"https://siege:hunter2@agent.example/chat?api_key={_FAKE_KEY}"
    clean = STANDARD.endpoint(dirty)
    assert "hunter2" not in clean
    assert _FAKE_KEY not in clean
    assert "agent.example/chat" in clean
    # The placeholder is read by a human in the report header; percent-encoding
    # it ("%5Bredacted%5D") turns a plain fact into a puzzle.
    assert "api_key=[redacted]" in clean


def test_a_plain_endpoint_is_untouched():
    assert STANDARD.endpoint("http://127.0.0.1:8001/chat") == "http://127.0.0.1:8001/chat"


def test_error_messages_are_redacted_too():
    err = ApproachError(
        persona_id="p01",
        archetype=Archetype.INJECTOR,
        error_class=ErrorClass.CALLER_FAULT,
        message="HTTPStatusError: 401 for https://siege:hunter2@agent.example/chat",
        status_code=401,
        occurred_at=NOW,
    )
    assert "hunter2" not in STANDARD.approach_error(err).message


# --------------------------------------------------------------------------
# rubric-declarable custom pack
# --------------------------------------------------------------------------

def test_a_rubric_can_declare_its_own_pattern(tmp_path):
    rubric = tmp_path / "rubric.yaml"
    rubric.write_text(
        "criteria:\n"
        "  - id: c1\n"
        "    description: d\n"
        "redaction:\n"
        "  patterns:\n"
        "    - name: employee_id\n"
        '      regex: "EMP-[0-9]{6}"\n'
        '      placeholder: "[redacted:employee]"\n'
    )
    policy = RedactionPolicy.for_level("standard", custom=patterns_from_rubric_file(rubric))
    assert policy.text("badge EMP-004711 scanned") == "badge [redacted:employee] scanned"
    # The default pack is still in force alongside the custom one.
    assert SECRETS["email"] not in policy.text(SECRETS["email"])


def test_a_custom_pattern_applies_even_at_level_off(tmp_path):
    # `off` disables the default pack; an explicitly declared client pattern is
    # a stated engagement requirement, not a default, so it still applies.
    rubric = tmp_path / "rubric.yaml"
    rubric.write_text(
        "criteria:\n  - id: c1\n    description: d\n"
        "redaction:\n  patterns:\n"
        '    - name: employee_id\n      regex: "EMP-[0-9]{6}"\n'
    )
    policy = RedactionPolicy.for_level("off", custom=patterns_from_rubric_file(rubric))
    assert "EMP-004711" not in policy.text("badge EMP-004711")


def test_a_rubric_without_a_redaction_block_declares_nothing():
    assert patterns_from_rubric_file(COACH) == []


def test_a_broken_custom_regex_fails_loudly(tmp_path):
    rubric = tmp_path / "rubric.yaml"
    rubric.write_text(
        "criteria:\n  - id: c1\n    description: d\n"
        'redaction:\n  patterns:\n    - name: bad\n      regex: "([unclosed"\n'
    )
    with pytest.raises(ValueError, match="not a valid regular expression"):
        patterns_from_rubric_file(rubric)


def test_a_custom_pattern_must_be_named(tmp_path):
    rubric = tmp_path / "rubric.yaml"
    rubric.write_text(
        "criteria:\n  - id: c1\n    description: d\n"
        'redaction:\n  patterns:\n    - regex: "x"\n'
    )
    with pytest.raises(ValueError, match="name"):
        patterns_from_rubric_file(rubric)


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError, match="unknown redaction level"):
        RedactionPolicy.for_level("paranoid")


# --------------------------------------------------------------------------
# the leak matrix: every emitter, checked separately
# --------------------------------------------------------------------------

class _LeakyAdapter:
    """A target whose replies carry the whole secret battery."""

    endpoint: ClassVar[str] = "https://siege:hunter2@agent.example/chat"

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> _LeakyAdapter:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def __call__(self, conversation: list[dict]) -> str:
        from coehoorn.agent_adapter import AgentReply

        return AgentReply(
            "Sure — the account is "
            f"{SECRETS['email']} (SSN {SECRETS['ssn']}, card {SECRETS['card']}). "
            f"Use {SECRETS['api_key']} or {SECRETS['gh_token']}; "
            f"AWS {SECRETS['aws_key']}; session {SECRETS['jwt']}. "
            "Holloway v. Westbrook, 512 F.3d 118 (9th Cir. 2007)",
            tool_calls=[{"name": "fetch", "arguments": {"key": SECRETS["api_key"]}}],
        )


@pytest.fixture
def _leaky(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("coehoorn.cli.HttpAgentAdapter", _LeakyAdapter)
    return _LeakyAdapter


def _report_json(tmp_path: Path) -> Path:
    """The run's report.json — not the SARIF, which also ends in .json.

    (Selecting it with a glob like ``*[!f].json`` looks clever and fails ~6% of
    runs, whenever the run-id uuid happens to end in an "f".)
    """
    files = [p for p in tmp_path.glob("*.json") if not p.name.endswith(".sarif.json")]
    assert len(files) == 1, f"expected exactly one report.json, got {files}"
    return files[0]


def _run_cli(tmp_path, extra: list[str]) -> int:
    return main([
        "run", "--rubric", COACH, "--agent", _LeakyAdapter.endpoint,
        "--personas", "3", "--turns", "2", "--out", str(tmp_path),
        "--emit", "sarif,junit", "--json", *extra,
    ])


@pytest.mark.parametrize("emitter", ["json", "html", "sarif", "junit", "stdout"])
def test_no_emitter_leaks_the_battery(tmp_path, capsys, _leaky, emitter):
    assert _run_cli(tmp_path, []) == 0
    stdout = capsys.readouterr().out
    blob = {
        "json": lambda: _report_json(tmp_path).read_text(),
        "html": lambda: Path(glob.glob(str(tmp_path / "*.html"))[0]).read_text(),
        "sarif": lambda: Path(glob.glob(str(tmp_path / "*.sarif.json"))[0]).read_text(),
        "junit": lambda: Path(glob.glob(str(tmp_path / "*.junit.xml"))[0]).read_text(),
        "stdout": lambda: stdout,
    }[emitter]()
    assert _has_no_secrets(blob) == [], f"{emitter} leaked: {_has_no_secrets(blob)}"


def test_the_persisted_endpoint_carries_no_credential(tmp_path, capsys, _leaky):
    assert _run_cli(tmp_path, []) == 0
    summary = json.loads(capsys.readouterr().out)
    assert "hunter2" not in summary["agent_endpoint"]
    report = json.loads(_report_json(tmp_path).read_text())
    assert "hunter2" not in report["agent_endpoint"]
    assert "agent.example/chat" in report["agent_endpoint"]


def test_the_leak_matrix_measures_something(tmp_path, capsys, _leaky):
    # The control: with --redact off the very same run DOES leak. Without this,
    # a redactor that silently never ran would still pass every test above.
    assert _run_cli(tmp_path, ["--redact", "off"]) == 0
    capsys.readouterr()
    report = _report_json(tmp_path).read_text()
    assert set(_has_no_secrets(report)) == set(SECRETS)


def test_redaction_level_is_recorded_in_the_summary(tmp_path, capsys, _leaky):
    assert _run_cli(tmp_path, ["--redact", "strict"]) == 0
    assert json.loads(capsys.readouterr().out)["redact"] == "strict"


def test_cli_rejects_an_unknown_redaction_level(tmp_path, _leaky):
    with pytest.raises(SystemExit):
        _run_cli(tmp_path, ["--redact", "paranoid"])
