"""Contract tests for the Siege Survey HTML report.

The report is the design hero, so its constraints are tested, not trusted:
self-contained (no JS, no external assets), warm paper/ink (no pure #fff/#000),
its own siege lexicon (never a CI gate's gate/pipeline imagery), fort geometry
keyed to the six fixed archetypes (never the variable criteria, which would
render degenerate), and breaches marked by SHAPE so they survive grayscale.
All three extreme states must render.
"""
from __future__ import annotations

from datetime import UTC, datetime

from coehoorn.report_html import render_report_html
from coehoorn.schemas import (
    Archetype,
    ConversationTurn,
    Criterion,
    CriterionStatus,
    CriterionVerdict,
    Persona,
    Report,
    Rubric,
    Transcript,
    Verdict,
    VerdictOutcome,
)

CRITERIA = ["safe_handling_of_self_harm", "no_fabricated_legal_citations"]
_TS = datetime(2026, 5, 17, 10, 8, 0, tzinfo=UTC)


def _rubric():
    return Rubric(
        criteria=[Criterion(id=c, description="d") for c in CRITERIA],
        overall_pass_threshold=1.0,
    )


def _transcript(i: int, arch: Archetype) -> Transcript:
    pid = f"p{i:02d}"
    turns = [
        ConversationTurn(index=0, role="user", content="probe one"),
        ConversationTurn(index=1, role="assistant", content="reply one"),
        ConversationTurn(index=2, role="user", content="probe two"),
        ConversationTurn(index=3, role="assistant", content="reply two"),
    ]
    return Transcript(
        id=f"t-{pid}",
        persona=Persona(id=pid, archetype=arch, name=f"name{i}", description="d"),
        turns=turns,
        started_at=_TS,
        completed_at=_TS,
    )


def _verdict(tid: str, outcome: VerdictOutcome, breach_turn: int = 3) -> Verdict:
    if outcome is VerdictOutcome.FAIL:
        cvs = [
            CriterionVerdict(
                criterion_id=CRITERIA[0], status=CriterionStatus.FAIL,
                confidence=0.9, cited_turn_index=breach_turn, rationale="breached",
            ),
            CriterionVerdict(
                criterion_id=CRITERIA[1], status=CriterionStatus.PASS,
                confidence=0.9, rationale="held",
            ),
        ]
        return Verdict(transcript_id=tid, criterion_verdicts=cvs,
                       outcome=outcome, worst_moment_turn_index=breach_turn)
    status = (
        CriterionStatus.PASS if outcome is VerdictOutcome.PASS else CriterionStatus.ABSTAIN
    )
    rationale = "held" if status is CriterionStatus.PASS else "no basis"
    cvs = [
        CriterionVerdict(criterion_id=c, status=status, confidence=0.8, rationale=rationale)
        for c in CRITERIA
    ]
    return Verdict(transcript_id=tid, criterion_verdicts=cvs,
                   outcome=outcome, worst_moment_turn_index=None)


def _report(outcomes: list[VerdictOutcome]) -> Report:
    archs = list(Archetype)
    transcripts, verdicts = [], []
    for i, outcome in enumerate(outcomes):
        t = _transcript(i, archs[i % len(archs)])
        transcripts.append(t)
        verdicts.append(_verdict(t.id, outcome))
    return Report(
        created_at=_TS, completed_at=_TS,
        agent_endpoint="http://127.0.0.1:8001/chat",
        rubric=_rubric(), transcripts=transcripts, verdicts=verdicts,
    )


def _mixed():
    return _report([VerdictOutcome.FAIL, VerdictOutcome.PASS, VerdictOutcome.FAIL,
                    VerdictOutcome.PASS, VerdictOutcome.PASS, VerdictOutcome.PASS])


def _all_held():
    return _report([VerdictOutcome.PASS] * 6)


def _all_breached():
    return _report([VerdictOutcome.FAIL] * 6)


# --- self-contained ------------------------------------------------------

def test_no_javascript():
    html = render_report_html(_mixed())
    assert "<script" not in html.lower()
    assert "onclick" not in html.lower()


def test_no_external_assets():
    html = render_report_html(_mixed())
    assert "http://" not in html.replace("http://127.0.0.1:8001/chat", "")
    assert "https://" not in html
    assert "@import" not in html
    assert "url(http" not in html.lower()
    assert "<img" not in html.lower()


# --- warm palette, no SaaS chrome ----------------------------------------

def test_no_pure_black_or_white():
    css = render_report_html(_mixed()).lower()
    for banned in ("#fff", "#ffffff", "#000", "#000000"):
        assert banned not in css, f"pure value {banned} present"


def test_no_border_radius():
    # Sharp engraving, no pill badges or rounded cards.
    assert "border-radius" not in render_report_html(_mixed()).lower()


def test_no_ci_gate_vocabulary_or_imagery():
    html = render_report_html(_all_breached()).lower()
    for token in (
        "green build", "regression", "pipeline", "traffic light",
        "deploy gate", "ci gate", "checkmark", "stoplight",
    ):
        assert token not in html, f"CI-gate token {token!r} leaked in"


# --- siege lexicon present -----------------------------------------------

def test_siege_vocabulary_present():
    html = render_report_html(_mixed()).lower()
    for term in ("siege", "approach", "breach", "held", "worst moment"):
        assert term in html, f"canon term {term!r} missing"


def test_breach_cites_its_turn():
    html = render_report_html(_mixed()).lower()
    # worst moment sits at turn 3 in the mixed fixture.
    assert "turn 3" in html


# --- archetype-keyed geometry (never criteria-keyed) ---------------------

def test_fort_keyed_to_six_archetypes_even_with_two_criteria():
    html = render_report_html(_mixed())
    for arch in Archetype:
        assert arch.value in html, f"archetype {arch.value} missing from survey"
    # The fort is drawn in inline SVG, six approaches regardless of 2 criteria.
    assert "<svg" in html.lower()
    assert html.lower().count("class=\"approach") >= 6


def test_breach_marked_by_shape_not_only_color():
    # A breach must carry a structural marker (the wall notch) so it survives
    # grayscale — asserted by the presence of a distinct breach element, not a
    # colour. Held approaches must not carry it.
    breached = render_report_html(_all_breached()).lower()
    held = render_report_html(_all_held()).lower()
    assert "breach-mark" in breached
    assert "breach-mark" not in held


# --- all three states render ---------------------------------------------

def test_svg_labels_do_not_clip_the_viewbox():
    # Estimate each label's rendered extent (not just its anchor point) and
    # assert it stays inside the viewBox. The worst case is the right-middle
    # face (ambiguous) carrying the longest label — "ambiguous · abstained".
    import re
    import xml.etree.ElementTree as ET

    report = _report([
        VerdictOutcome.FAIL, VerdictOutcome.ABSTAIN, VerdictOutcome.FAIL,
        VerdictOutcome.FAIL, VerdictOutcome.FAIL, VerdictOutcome.FAIL,
    ])
    svg = re.search(r"(<svg.*?</svg>)", render_report_html(report), re.S).group(1)
    root = ET.fromstring(svg)
    vb_w = float(root.attrib["viewBox"].split()[2])
    char_w = 6.6  # conservative monospace advance at font-size 10
    for t in root.iter("text"):
        text = "".join(t.itertext())
        x = float(t.attrib["x"])
        anchor = t.attrib.get("text-anchor", "start")
        w = len(text) * char_w
        lo, hi = {"start": (x, x + w), "end": (x - w, x)}.get(
            anchor, (x - w / 2, x + w / 2)
        )
        assert lo >= -2, f"label {text!r} clips the left edge ({lo:.0f})"
        assert hi <= vb_w + 2, f"label {text!r} clips the right edge ({hi:.0f} > {vb_w:.0f})"


def test_all_states_render_nonempty():
    for report in (_mixed(), _all_held(), _all_breached()):
        html = render_report_html(report)
        assert "<svg" in html.lower()
        assert len(html) > 3000


def test_meta_panel_shows_honest_gold_calibration_with_baselines():
    from pathlib import Path

    from coehoorn.meta_eval import evaluate_gold, load_gold_cases
    from coehoorn.rubric_parser import parse_rubric_file

    root = Path(__file__).resolve().parent.parent
    rubric, rules = parse_rubric_file(root / "examples" / "rubric_coach.yaml")
    cases = load_gold_cases(root / "tests" / "gold" / "judge_gold.jsonl")
    judge_eval = evaluate_gold(cases, rubric, rules)

    html = render_report_html(_mixed(), judge_eval=judge_eval)
    assert "Judge calibration" in html
    # the dumb baselines are shown so the judge's number means something
    assert "always-breach" in html and "always-hold" in html
    # the honest gold balanced accuracy (0.66), not an all-1.00 brag
    assert "<b>0.66</b>" in html
    # rates carry a Wilson interval with n stated
    assert "95% CI" in html
    # no panel when judge_eval is omitted
    assert "Judge calibration" not in render_report_html(_mixed())


def test_cartouche_prose_reflects_state():
    held = render_report_html(_all_held()).lower()
    breached = render_report_html(_all_breached()).lower()
    # All-held survey says so; all-breached names breaches. Neither is empty.
    assert "held" in held
    assert "breach" in breached


# --- mobile + screen-reader (regression) ---------------------------------

def test_head_declares_mobile_viewport():
    # Regression: the report had no viewport meta. The CSS is fluid (max-width
    # container, width:100% svg), but without this tag a phone lays the page out
    # at ~980px and shrinks it to pinch-zoom, so the responsive CSS never engages.
    html = render_report_html(_mixed())
    assert '<meta name="viewport" content="width=device-width, initial-scale=1"/>' in html


def test_table_headers_carry_scope():
    # Regression: bare <th> gave screen readers no header/data association.
    # Covers the always-on breaches-by-criterion table and (with judge_eval)
    # the calibration table.
    from pathlib import Path

    from coehoorn.meta_eval import evaluate_gold, load_gold_cases
    from coehoorn.rubric_parser import parse_rubric_file

    # always-on table
    assert "<th>" not in render_report_html(_all_breached())

    # calibration table (only rendered when judge_eval is supplied)
    root = Path(__file__).resolve().parent.parent
    rubric, rules = parse_rubric_file(root / "examples" / "rubric_coach.yaml")
    cases = load_gold_cases(root / "tests" / "gold" / "judge_gold.jsonl")
    judge_eval = evaluate_gold(cases, rubric, rules)
    html = render_report_html(_mixed(), judge_eval=judge_eval)
    assert "<th>" not in html  # every header cell is scoped
    assert 'scope="col">metric' in html
