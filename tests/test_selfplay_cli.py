"""`coehoorn self-play` CLI: parser, offline round, honest live gate, errors.

The offline path runs the loop against the bundled safe stub in-process (no
socket) and must mark its numbers as a plumbing demo. The live path must refuse
to run without ANTHROPIC_API_KEY rather than fabricate a result.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

from coehoorn.cli import build_parser, main

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD = str(REPO_ROOT / "tests" / "gold" / "judge_gold.jsonl")
COACH = str(REPO_ROOT / "examples" / "rubric_coach.yaml")
STUB_DIR = REPO_ROOT / "apps" / "stub-agent"


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
    def __init__(self, *args, **kwargs) -> None:
        self._call = _stub_call()

    async def __aenter__(self) -> "_FakeHttpAdapter":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def __call__(self, conversation: list[dict]) -> str:
        return self._call(conversation)


def test_self_play_parser_registers_subcommand():
    parser = build_parser()
    args = parser.parse_args([
        "self-play", "--rubric", COACH, "--gold", GOLD, "--agent", "http://x",
        "--criterion", "safe_handling_of_self_harm", "--k", "2", "--json",
    ])
    assert args.cmd == "self-play"
    assert args.criterion == "safe_handling_of_self_harm"
    assert args.k == 2 and args.json is True


def test_self_play_offline_round_is_not_live(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("coehoorn.selfplay.cli.HttpAgentAdapter", _FakeHttpAdapter)
    rc = main([
        "self-play", "--rubric", COACH, "--gold", GOLD, "--agent", "http://stub",
        "--criterion", "safe_handling_of_self_harm", "--json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["is_live"] is False
    assert payload["n_attacks"] == 3
    # Every self-harm seed reproduces a trusted breach against the stub.
    assert payload["asr"] == 1.0
    assert payload["judge_trustworthy"] is True
    assert "OFFLINE PLUMBING DEMO" in payload["note"]


def test_self_play_writes_round_json_to_out(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("coehoorn.selfplay.cli.HttpAgentAdapter", _FakeHttpAdapter)
    out = tmp_path / "round.json"
    rc = main([
        "self-play", "--rubric", COACH, "--gold", GOLD, "--agent", "http://stub",
        "--criterion", "safe_handling_of_self_harm", "--out", str(out),
    ])
    assert rc == 0
    saved = json.loads(out.read_text())
    assert saved["is_live"] is False
    assert saved["n_attacks"] == 3
    assert "round json:" in capsys.readouterr().out


def test_self_play_llm_without_key_exits_2_no_fabrication(monkeypatch, capsys):
    # --mode llm with no key must NOT fabricate; the honest gate exits non-zero.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main([
            "self-play", "--mode", "llm", "--rubric", COACH, "--gold", GOLD,
            "--agent", "http://x", "--criterion", "safe_handling_of_self_harm",
        ])
    assert exc.value.code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_self_play_clean_error_when_no_seed_breach(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main([
        "self-play", "--rubric", COACH, "--gold", GOLD, "--agent", "http://x",
        "--criterion", "no_such_criterion",
    ])
    assert rc == 2
    assert "no gold=fail breach cells" in capsys.readouterr().err


def test_self_play_clean_error_on_missing_rubric(capsys):
    rc = main([
        "self-play", "--rubric", "/nonexistent/r.yaml", "--gold", GOLD,
        "--agent", "http://x",
    ])
    assert rc == 2
    assert "error" in capsys.readouterr().err.lower()
