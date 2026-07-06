"""Pin the OWASP Agentic taxonomy the tool-use and MCP packs map onto.

Coehoorn cites tool-use and MCP-tool-poisoning breaches against the OWASP GenAI
Security Project "Top 10 for Agentic Applications" (2026 edition, published
2025-12-09; risks ASI01-ASI10). These tests pin that edition and its exact risk
titles so a future OWASP revision -- or a silent edit that drifts an ID or a
title in the docs -- fails the suite loudly here instead of leaving a stale
mapping in the coverage map.

IDs and titles verified 2026-07-06 against the OWASP GenAI Security Project
resource page, cross-checked against two independent published enumerations:
  https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
"""
from __future__ import annotations

import re
from pathlib import Path

# --- The pin --------------------------------------------------------------
# Bump these deliberately when OWASP ships a new edition; the assertions below
# then force every doc/rubric reference to be re-reconciled rather than drift.
OWASP_AGENTIC_EDITION = "2026"

# ASI01-ASI10 in published order, with the exact published titles.
OWASP_AGENTIC_TOP_10: dict[str, str] = {
    "ASI01": "Agent Goal Hijack",
    "ASI02": "Tool Misuse & Exploitation",
    "ASI03": "Agent Identity & Privilege Abuse",
    "ASI04": "Agentic Supply Chain Compromise",
    "ASI05": "Unexpected Code Execution",
    "ASI06": "Memory & Context Poisoning",
    "ASI07": "Insecure Inter-Agent Communication",
    "ASI08": "Cascading Agent Failures",
    "ASI09": "Human-Agent Trust Exploitation",
    "ASI10": "Rogue Agents",
}

_ROOT = Path(__file__).resolve().parent.parent
_COVERAGE_MAP = _ROOT / "docs" / "coverage-map.md"
_README = _ROOT / "README.md"
_ASI_TOKEN = re.compile(r"ASI\d{2}")


def _repo_text_files() -> list[Path]:
    """The source surfaces that may name ASI ids (excludes .venv, runs, dist)."""
    files: list[Path] = sorted(_ROOT.glob("*.md"))
    files += sorted((_ROOT / "docs").rglob("*.md"))
    files += sorted((_ROOT / "coehoorn").rglob("*.py"))
    files += sorted((_ROOT / "examples").rglob("*.yaml"))
    return files


def test_taxonomy_pins_ten_ids_in_published_order():
    assert list(OWASP_AGENTIC_TOP_10) == [f"ASI{n:02d}" for n in range(1, 11)]
    assert len(OWASP_AGENTIC_TOP_10) == 10


def test_coverage_map_reference_list_matches_pinned_titles():
    text = _COVERAGE_MAP.read_text()
    for asi, title in OWASP_AGENTIC_TOP_10.items():
        assert f"{asi} {title}" in text, (
            f"coverage-map.md is missing the exact pinned title '{asi} {title}'; "
            "the taxonomy drifted from tests/test_taxonomy.py"
        )


def test_docs_name_the_pinned_edition():
    pattern = re.compile(rf"Agentic[^\n]{{0,20}}{re.escape(OWASP_AGENTIC_EDITION)}")
    for path in (_COVERAGE_MAP, _README):
        assert pattern.search(path.read_text()), (
            f"{path.name} does not name the OWASP Agentic {OWASP_AGENTIC_EDITION} edition"
        )


def test_no_out_of_range_asi_ids_anywhere():
    valid = set(OWASP_AGENTIC_TOP_10)
    for path in _repo_text_files():
        for token in set(_ASI_TOKEN.findall(path.read_text())):
            assert token in valid, (
                f"{path.relative_to(_ROOT)} references '{token}', which is not a "
                f"valid id in the pinned OWASP Agentic {OWASP_AGENTIC_EDITION} taxonomy"
            )
