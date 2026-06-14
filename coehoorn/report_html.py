"""Renders a Report as a self-contained "Siege Survey" HTML file.

No JavaScript, no external assets, no network at render time: the whole
document — including the fort diagram (inline SVG) and every wash of colour
(inline CSS) — is one file you can open from disk with the network off, or
print to a faithful PDF.

The visual language is a 17th-century military-engineering survey, after
Menno van Coehoorn: a six-faced fort (one face per adversarial *archetype*,
always six, never keyed to the variable criteria), ringed by a Prussian-blue
*ditch* that stands for the schema trust boundary. Each persona is an
*approach* on one face; a criterion failure is a *breach* — a literal gap cut
in that wall segment at the cited turn, so it reads even in grayscale. A held
wall is unbroken. The worst breach in a transcript is the *worst moment*.

Nothing here speaks the vocabulary of a deploy gate; Coehoorn discovers, it does
not gate. Rendering is pure Python with strict escaping (the report embeds
untrusted agent replies), which also lets the fort geometry be computed
directly and keeps the dependency surface at zero for this module.
"""
from __future__ import annotations

import html
import math
from pathlib import Path

from .schemas import Archetype, CriterionStatus, Report, VerdictOutcome

# The optional `metrics` argument is a metrics.MetricsReport, duck-typed here
# so this module imports nothing it doesn't strictly need to render.

_PALETTE = """
  --paper:#EFE7D3; --paper-inset:#E6DABE; --ink:#2A2622;
  --breach:#9E2B25; --ditch:#274B6D;
  --sepia:#6E5436; --held:#4E6B4F; --rule-faint:#B9AD90;
""".strip()

_SERIF = (
    "'Hoefler Text','Baskerville','Palatino Linotype','Book Antiqua',"
    "'Georgia','Times New Roman',serif"
)
_MONO = "'SF Mono','Cascadia Mono','DejaVu Sans Mono','Consolas',monospace"

# Stable angular slot per archetype so the fort is always six-faced and a
# given archetype always sits in the same place across runs.
_ARCHETYPE_ORDER = list(Archetype)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _css() -> str:
    return f"""
  :root {{ {_PALETTE} }}
  * {{ box-sizing: border-box; }}
  html {{ background: var(--ink); }}
  body {{
    font-family: {_SERIF}; color: var(--ink); line-height: 1.62;
    font-variant-numeric: oldstyle-nums;
    max-width: 900px; margin: 0 auto; padding: 2.2rem 1.4rem 3rem;
    background-color: var(--paper);
    background-image:
      radial-gradient(120% 90% at 50% 0%, rgba(239,231,211,0) 60%, rgba(42,38,34,0.10) 100%),
      repeating-linear-gradient(0deg, rgba(110,84,54,0.045) 0 1px, rgba(110,84,54,0) 1px 4px);
  }}
  .frame {{
    border: 1.4px solid var(--ink); padding: 1.6rem 1.7rem;
    box-shadow: inset 0 0 0 3px var(--paper), inset 0 0 0 4.2px var(--ink);
  }}
  .token {{ font-family: {_MONO}; font-size: 0.82em; color: var(--sepia); }}
  h1, h2, h3 {{ font-weight: 600; margin: 0; }}
  .cartouche {{
    background: var(--paper-inset); border: 1.2px solid var(--ink);
    box-shadow: inset 0 0 0 2.4px var(--paper-inset), inset 0 0 0 3.4px var(--rule-faint);
    padding: 1.2rem 1.4rem 1.3rem; text-align: center; margin-bottom: 1.5rem;
  }}
  .cartouche .kicker {{
    font-variant: small-caps; letter-spacing: 0.22em; font-size: 0.74rem;
    color: var(--sepia);
  }}
  .cartouche h1 {{
    font-size: 1.3rem; letter-spacing: 0.14em; text-transform: uppercase;
    margin: 0.1rem 0 0.05rem; color: var(--sepia);
  }}
  .cartouche .sub {{ font-style: italic; font-variant: small-caps; color: var(--sepia); letter-spacing: 0.04em; }}
  .cartouche .tally {{ font-size: 2.7rem; line-height: 1.04; margin: 0.55rem 0 0.2rem; font-feature-settings: "lnum"; }}
  .cartouche .tally .n-breach {{ color: var(--breach); }}
  .cartouche .tally.clear .n-breach {{ color: var(--held); }}
  .cartouche .tally .lede {{ font-variant: small-caps; letter-spacing: 0.05em; }}
  .cartouche .verdict-prose {{ font-size: 1.02rem; margin-top: 0.35rem; color: var(--ink); }}
  .rule {{ height: 0; border: 0; border-top: 1px solid var(--ink); box-shadow: 0 2px 0 -1px var(--rule-faint); margin: 1.4rem 0; }}
  figure {{ margin: 0 0 1.4rem; text-align: center; }}
  figure figcaption {{ font-style: italic; color: var(--sepia); font-size: 0.85rem; margin-top: 0.3rem; }}
  svg {{ width: 100%; max-width: 660px; height: auto; }}
  .legend {{
    background: var(--paper-inset); border: 1px solid var(--rule-faint);
    padding: 0.75rem 1rem; font-size: 0.84rem; columns: 2; column-gap: 1.6rem;
    margin-bottom: 1.5rem;
  }}
  .legend b {{ font-variant: small-caps; letter-spacing: 0.06em; }}
  .stamp {{
    display: inline-block; padding: 0.05rem 0.45rem; font-size: 0.72rem;
    font-variant: small-caps; letter-spacing: 0.12em; border: 1.4px solid;
    vertical-align: middle;
  }}
  .stamp.breach {{ color: var(--breach); border-color: var(--breach); }}
  .stamp.held {{ color: var(--held); border-color: var(--held); }}
  .stamp.abstain {{ color: var(--sepia); border-color: var(--sepia); border-style: dashed; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 0.6rem 0 1.2rem; }}
  th, td {{ text-align: left; padding: 0.32rem 0.55rem; border-bottom: 1px solid var(--rule-faint); }}
  th {{ font-variant: small-caps; letter-spacing: 0.06em; border-bottom: 1.4px solid var(--ink); }}
  details {{ border: 1px solid var(--rule-faint); border-left: 3px solid var(--rule-faint); margin-bottom: 0.6rem; background: var(--paper-inset); padding: 0.5rem 0.85rem; }}
  details[data-outcome="fail"] {{ border-left-color: var(--breach); }}
  details[data-outcome="abstain"] {{ border-left-color: var(--sepia); border-left-style: dashed; }}
  summary {{ cursor: pointer; font-weight: 600; display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; }}
  .crit {{ margin: 0.2rem 0 0.2rem 0; }}
  .turn {{ padding: 0.4rem 0.6rem; margin: 0.28rem 0; border-left: 2.5px solid var(--rule-faint); background: rgba(110,84,54,0.05); white-space: pre-wrap; font-size: 0.9rem; }}
  .turn .who {{ font-variant: small-caps; letter-spacing: 0.08em; font-size: 0.74rem; color: var(--sepia); }}
  .turn.worst {{ border-left: 3px solid var(--breach); background: rgba(158,43,37,0.07); }}
  .turn.cited:not(.worst) {{ border-left: 2.5px dashed var(--breach); }}
  .tools {{ margin-top: 0.3rem; font-size: 0.8rem; color: var(--sepia); }}
  .tool-call {{ font-family: {_MONO}; background: rgba(39,75,109,0.10); color: var(--ditch); padding: 0 0.32rem; margin-right: 0.3rem; }}
  footer {{ margin-top: 1.8rem; font-size: 0.78rem; color: var(--sepia); font-style: italic; text-align: center; }}
  a:focus-visible, summary:focus-visible {{ outline: 2px solid var(--ditch); outline-offset: 2px; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
  @media print {{
    html, body {{ background: var(--paper); }}
    .frame {{ box-shadow: none; }}
    details {{ break-inside: avoid; }}
    /* Force every approach open so the archival record is complete on paper,
       even the held ones that render collapsed on screen. */
    details > *:not(summary) {{ display: block !important; }}
    * {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
""".strip()


def _verdict_by_tid(report: Report) -> dict:
    return {v.transcript_id: v for v in report.verdicts}


def _hexagon(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Six vertices of a flat-topped-ish hexagon, first vertex at the top."""
    return [
        (
            cx + r * math.cos(math.radians(-90 + j * 60)),
            cy + r * math.sin(math.radians(-90 + j * 60)),
        )
        for j in range(6)
    ]


def _fort_svg(report: Report) -> str:
    """Compute the six-faced fort, its ditch, and one approach per archetype."""
    # viewBox is widened well past the fort so outboard labels (which can be as
    # long as "ambiguous · abstained" on the right-middle face) never clip.
    cx, cy, r_wall, r_moat, r_out = 360.0, 214.0, 96.0, 134.0, 212.0
    verts = _hexagon(cx, cy, r_wall)
    vbt = _verdict_by_tid(report)
    # archetype slot -> (outcome, worst_turn) for the persona that ran it
    slot: dict[int, tuple[VerdictOutcome, int | None]] = {}
    for tr in report.transcripts:
        idx = _ARCHETYPE_ORDER.index(tr.persona.archetype)
        v = vbt.get(tr.id)
        if v is not None:
            slot[idx] = (v.outcome, v.worst_moment_turn_index)

    parts: list[str] = [
        '<svg viewBox="0 0 720 452" role="img" '
        'aria-label="Siege survey: a six-faced fort, one approach per archetype">'
    ]
    parts.append(
        '<defs><pattern id="masonry" width="9" height="9" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="9" stroke="#6E5436" stroke-width="0.5" stroke-opacity="0.35"/>'
        "</pattern></defs>"
    )
    # ditch / trust boundary (hexagon ring at moat radius)
    moat_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in _hexagon(cx, cy, r_moat))
    parts.append(
        f'<polygon points="{moat_pts}" fill="none" stroke="#274B6D" '
        f'stroke-width="2.2" stroke-dasharray="1 5" stroke-linecap="round"/>'
    )
    # fort interior fill (masonry hatch)
    wall_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in verts)
    parts.append(f'<polygon points="{wall_pts}" fill="url(#masonry)" stroke="none"/>')

    def _lerp(a, b, f):
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)

    label_lines: list[str] = []
    for i in range(6):
        a, b = verts[i], verts[(i + 1) % 6]
        mid = _lerp(a, b, 0.5)
        dirx, diry = mid[0] - cx, mid[1] - cy
        dlen = math.hypot(dirx, diry) or 1.0
        ux, uy = dirx / dlen, diry / dlen
        px, py = -uy, ux  # unit perpendicular to the approach
        anchor = (cx + ux * r_out, cy + uy * r_out)
        moat_pt = (cx + ux * r_moat, cy + uy * r_moat)
        arch_name = _ARCHETYPE_ORDER[i].value
        entry = slot.get(i)
        outcome = entry[0] if entry else None
        # Anchor the label AWAY from the fort (start on right faces, end on
        # left) so its text grows outward and never crosses the approach line,
        # which runs inward from the same point.
        anchor_side = "start" if ux >= 0 else "end"
        lx, ly = anchor[0] + ux * 6, anchor[1] + uy * 6 + 3.5

        if outcome is VerdictOutcome.FAIL:
            # A breach is a true GAP: two wall stubs with empty space between,
            # marked by an OPEN carmine chevron driven inward — a void, not a
            # filled plug, so it reads as "wall missing" even in grayscale.
            g1, g2 = _lerp(a, b, 0.34), _lerp(a, b, 0.66)
            tip = (mid[0] - ux * 17, mid[1] - uy * 17)
            parts.append(
                f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{g1[0]:.1f}" y2="{g1[1]:.1f}" stroke="#2A2622" stroke-width="3"/>'
            )
            parts.append(
                f'<line x1="{g2[0]:.1f}" y1="{g2[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#2A2622" stroke-width="3"/>'
            )
            parts.append(
                f'<line class="approach breach" x1="{anchor[0]:.1f}" y1="{anchor[1]:.1f}" '
                f'x2="{mid[0]:.1f}" y2="{mid[1]:.1f}" stroke="#9E2B25" stroke-width="2.4"/>'
            )
            parts.append(
                f'<polyline class="breach-mark" points="{g1[0]:.1f},{g1[1]:.1f} '
                f'{tip[0]:.1f},{tip[1]:.1f} {g2[0]:.1f},{g2[1]:.1f}" fill="none" '
                f'stroke="#9E2B25" stroke-width="2.2" stroke-linejoin="miter"/>'
            )
            # worst_moment is a schema-validated int on any FAIL verdict; cast
            # explicitly so the label is safe by construction AND by type.
            turn = int(entry[1]) if entry and entry[1] is not None else 0
            label_lines.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor_side}" '
                f'font-family={_MONO!r} font-size="10" fill="#9E2B25">'
                f"{_esc(arch_name)} · turn {turn}</text>"
            )
        else:
            # intact wall segment
            parts.append(
                f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#2A2622" stroke-width="3"/>'
            )
            if outcome is VerdictOutcome.PASS:
                cls, stroke, dash, color = "approach held", "#4E6B4F", "5 4", "#4E6B4F"
                tag = arch_name
                # cross-stroke at the ditch: this approach was turned away
                parts.append(
                    f'<line class="repulse" x1="{moat_pt[0] - px * 5:.1f}" y1="{moat_pt[1] - py * 5:.1f}" '
                    f'x2="{moat_pt[0] + px * 5:.1f}" y2="{moat_pt[1] + py * 5:.1f}" stroke="#4E6B4F" stroke-width="2"/>'
                )
            elif outcome is VerdictOutcome.ABSTAIN:
                cls, stroke, dash, color = "approach abstain", "#6E5436", "1 4", "#6E5436"
                tag = f"{arch_name} · abstained"
                # hollow dot at the anchor: no judgment was rendered
                parts.append(
                    f'<circle class="abstain-mark" cx="{anchor[0]:.1f}" cy="{anchor[1]:.1f}" r="3.4" '
                    f'fill="#EFE7D3" stroke="#6E5436" stroke-width="1.3"/>'
                )
            else:
                cls, stroke, dash, color = "approach absent", "#B9AD90", "1 6", "#B9AD90"
                tag = arch_name
            parts.append(
                f'<line class="{cls}" x1="{anchor[0]:.1f}" y1="{anchor[1]:.1f}" '
                f'x2="{moat_pt[0]:.1f}" y2="{moat_pt[1]:.1f}" stroke="{stroke}" '
                f'stroke-width="1.8" stroke-dasharray="{dash}"/>'
            )
            label_lines.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor_side}" '
                f'font-family={_MONO!r} font-size="10" fill="{color}">{_esc(tag)}</text>'
            )

    # corner bastions (small marks at each vertex) for the star-fort read
    for x, y in verts:
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.1" fill="#EFE7D3" stroke="#2A2622" stroke-width="1.4"/>'
        )
    parts.extend(label_lines)
    parts.append(
        f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" '
        f'font-family={_SERIF!r} font-size="11" fill="#6E5436" letter-spacing="2" '
        f'stroke="#EFE7D3" stroke-width="2.6" paint-order="stroke">THE AGENT</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _cartouche_prose(report: Report) -> str:
    total = len(report.verdicts)
    breaches = sum(1 for v in report.verdicts if v.outcome is VerdictOutcome.FAIL)
    held = sum(1 for v in report.verdicts if v.outcome is VerdictOutcome.PASS)
    abstained = sum(1 for v in report.verdicts if v.outcome is VerdictOutcome.ABSTAIN)
    if breaches == 0 and abstained == 0:
        return f"All {total} approaches repulsed; the works held."
    # The tally above already states the breach count, so the prose carries the
    # non-redundant detail only: how many held, how deep the worst breach went.
    bits = []
    if held:
        bits.append(f"{held} repulsed")
    if breaches:
        deepest = max(
            (v.worst_moment_turn_index for v in report.verdicts
             if v.outcome is VerdictOutcome.FAIL and v.worst_moment_turn_index is not None),
            default=None,
        )
        # Run-level: the DEEPEST breach (a turn-index max). Per-transcript
        # "worst moment" is severity-ranked; "deepest" avoids conflating them.
        if deepest is not None:
            bits.append(f"deepest breach at turn {deepest}")
    if abstained:
        bits.append(f"{abstained} inconclusive")
    return " · ".join(bits) + "."


def _legend() -> str:
    items = [
        ("siege", "one run: every approach driven against the agent."),
        ("approach", "one persona's conversation against the fort."),
        ("breach", "the turn where a criterion failed — a gap cut in the wall."),
        ("held", "an approach the wall turned away."),
        ("worst moment", "the deepest breach in a transcript."),
        ("the ditch", "the schema boundary — a breach that cites no turn cannot be constructed."),
    ]
    rows = "".join(
        f"<div><b>{_esc(t)}</b> &mdash; {_esc(d)}</div>" for t, d in items
    )
    return f'<div class="legend">{rows}</div>'


def _proportion(est) -> str:
    if est is None or est.value is None:
        return "n/a"
    return (
        f"{est.value:.2f} "
        f'<span class="token">(95% CI {est.lower:.2f}–{est.upper:.2f}, '
        f"n={est.denominator})</span>"
    )


def _num(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _meta_panel(judge_eval) -> str:
    """Render the gold judge-calibration scorecard (a meta_eval.GoldEvalResult),
    with the dumb baselines alongside. This is the judge's honest accuracy on an
    adversarial gold set — deliberately not the run's own self-fulfilling 1.00
    against its expected-failures fixture."""
    if judge_eval is None:
        return ""
    m = judge_eval.metrics
    bb, bh = judge_eval.baseline_always_breach, judge_eval.baseline_always_hold

    confusion = (
        f"<tr><td>breaches caught (TP)</td><td class='token'>{m.tp}</td></tr>"
        f"<tr><td>false alarms (FP)</td><td class='token'>{m.fp}</td></tr>"
        f"<tr><td>missed breaches (FN)</td><td class='token'>{m.fn}</td></tr>"
        f"<tr><td>correct holds (TN)</td><td class='token'>{m.tn}</td></tr>"
    )

    def prop_row(name, est, b1, b2):
        return (
            f"<tr><td>{name}</td><td>{_proportion(est)}</td>"
            f"<td class='token'>{_num(b1.value)}</td>"
            f"<td class='token'>{_num(b2.value)}</td></tr>"
        )

    def scalar_row(name, v, b1, b2, bold=False):
        cell = f"<b>{_num(v)}</b>" if bold else f"<span class='token'>{_num(v)}</span>"
        return (
            f"<tr><td>{name}</td><td>{cell}</td>"
            f"<td class='token'>{_num(b1)}</td><td class='token'>{_num(b2)}</td></tr>"
        )

    table = (
        '<tr><th scope="col">metric</th><th scope="col">judge</th>'
        '<th scope="col">always-breach</th><th scope="col">always-hold</th></tr>'
        + prop_row("precision", m.precision, bb.precision, bh.precision)
        + prop_row("recall", m.recall, bb.recall, bh.recall)
        + prop_row("specificity", m.specificity, bb.specificity, bh.specificity)
        + scalar_row("F1", m.f1, bb.f1, bh.f1)
        + scalar_row("balanced accuracy", m.balanced_accuracy,
                     bb.balanced_accuracy, bh.balanced_accuracy, bold=True)
        + scalar_row("Cohen's kappa", m.cohens_kappa, bb.cohens_kappa, bh.cohens_kappa)
    )
    abstained_note = (
        f" &middot; {judge_eval.n_abstained} abstained (excluded)"
        if judge_eval.n_abstained else ""
    )
    return f"""
    <hr class="rule"/>
    <h2>Judge calibration &mdash; the auditor, audited</h2>
    <p>How this report's judge scored against a frozen, adversarial gold set &mdash;
    the honest measure of how far to trust its verdicts (not the run's own
    self-fulfilling score against its expected-failures fixture). Rates carry a
    Wilson 95% interval; the survey reads the interval floor, not the point
    estimate, as the load-bearing number. A judge must clear the dumb baselines
    to mean anything.</p>
    <table><tbody>{confusion}</tbody></table>
    <table>{table}</table>
    <p class="token">{judge_eval.n_scored} gold cells scored{abstained_note}.</p>
    """


def _breach_table(report: Report) -> str:
    # By criterion only: the fort diagram already shows which archetype/approach
    # breached, so a second "by approach" table just restates the picture.
    fbc = report.failures_by_criterion
    if not fbc:
        return "<p><em>No breaches: every approach was turned away at the wall.</em></p>"
    crit_rows = "".join(
        f'<tr><td class="token">{_esc(cid)}</td><td>{n}</td></tr>'
        for cid, n in sorted(fbc.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return f"""
    <h2>Breaches by criterion</h2>
    <table><tr><th scope="col">criterion</th><th scope="col">breaches</th></tr>{crit_rows}</table>
    """


def _transcripts(report: Report) -> str:
    vbt = _verdict_by_tid(report)
    rows = []
    for t in report.transcripts:
        v = vbt[t.id]
        rows.append((v.outcome is VerdictOutcome.PASS, t.persona.id, t, v))
    rows.sort(key=lambda r: (r[0], r[1]))

    blocks = []
    for _, _, t, v in rows:
        stamp = {
            VerdictOutcome.PASS: '<span class="stamp held">held</span>',
            VerdictOutcome.FAIL: '<span class="stamp breach">breach</span>',
            VerdictOutcome.ABSTAIN: '<span class="stamp abstain">abstained</span>',
        }[v.outcome]
        crit_items = []
        for cv in v.criterion_verdicts:
            if cv.status is CriterionStatus.FAIL:
                tag = f'<span class="stamp breach">breach</span> at turn {cv.cited_turn_index}'
            elif cv.status is CriterionStatus.PASS:
                tag = '<span class="stamp held">held</span>'
            else:
                tag = '<span class="stamp abstain">abstained</span>'
            crit_items.append(
                f'<div class="crit"><span class="token">{_esc(cv.criterion_id)}</span> '
                f"{tag} &mdash; {_esc(cv.rationale)}</div>"
            )
        cited = {
            cv.cited_turn_index
            for cv in v.criterion_verdicts
            if cv.status is CriterionStatus.FAIL and cv.cited_turn_index is not None
        }
        turn_blocks = []
        for turn in t.turns:
            cls = "turn"
            label = f"{turn.role} · turn {turn.index}"
            if v.worst_moment_turn_index == turn.index:
                cls += " worst"
                label += " · worst moment"
            elif turn.index in cited:
                cls += " cited"
                label += " · cited"
            content_html = f"<div>{_esc(turn.content)}</div>"
            if turn.tool_calls:
                calls = "".join(
                    f'<span class="tool-call">{_esc(tc.name)}'
                    f'({_esc(", ".join(tc.arguments))})</span>'
                    for tc in turn.tool_calls
                )
                content_html += f'<div class="tools">tool calls: {calls}</div>'
            turn_blocks.append(
                f'<div class="{cls}"><div class="who">{_esc(label)}</div>{content_html}</div>'
            )
        blocks.append(
            f'<details data-outcome="{v.outcome.value}" '
            f"{'open' if v.outcome is not VerdictOutcome.PASS else ''}>"
            f"<summary><span class='token'>{_esc(t.persona.id)}</span> "
            f"{_esc(t.persona.name)} "
            f"<span class='token'>{_esc(t.persona.archetype.value)}</span> {stamp}</summary>"
            f"<p><em>{_esc(t.persona.description)}</em></p>"
            f"<div>{''.join(crit_items)}</div>"
            f"<div style='margin-top:0.5rem'>{''.join(turn_blocks)}</div>"
            "</details>"
        )
    return "<h2>Evidence &mdash; cited transcripts</h2>" + "".join(blocks)


def render_report_html(report: Report, judge_eval=None) -> str:
    total = len(report.verdicts)
    breaches = sum(1 for v in report.verdicts if v.outcome is VerdictOutcome.FAIL)
    head = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        f"<title>Siege Survey — {_esc(report.run_id[:8])}</title>"
        f"<style>{_css()}</style></head><body><div class='frame'>"
    )
    cartouche = (
        '<div class="cartouche">'
        '<div class="kicker">Carte du Si&egrave;ge</div>'
        "<h1>Siege Survey</h1>"
        f'<div class="sub">survey of the defenses of '
        f'<span class="token">{_esc(report.agent_endpoint)}</span></div>'
        f'<div class="tally{" clear" if breaches == 0 else ""}">'
        f'<span class="n-breach">{breaches}</span> '
        f'{"breach" if breaches == 1 else "breaches"} '
        f'<span class="lede">of {total} approaches</span></div>'
        f'<div class="verdict-prose">{_esc(_cartouche_prose(report))}</div>'
        f'<div class="token" style="margin-top:0.5rem">run {_esc(report.run_id)} · '
        f"{_esc(report.created_at.isoformat())} &rarr; {_esc(report.completed_at.isoformat())}</div>"
        "</div>"
    )
    figure = (
        "<figure>" + _fort_svg(report) +
        "<figcaption>The fort under siege.</figcaption></figure>"
    )
    summary_line = (
        f"<p><strong>{breaches}</strong> of <strong>{total}</strong> approaches "
        f"breached the works; <span class='token'>{report.pass_rate:.0%}</span> held"
        + (f", <span class='token'>{report.abstention_rate:.0%}</span> inconclusive"
           if report.abstention_rate else "")
        + ".</p>"
    )
    body = (
        cartouche + figure + _legend() + summary_line
        + _breach_table(report)
        + _meta_panel(judge_eval)
        + '<hr class="rule"/>'
        + _transcripts(report)
        + "<footer>Drawn by Coehoorn — a local siege survey. "
          "No script, no external plate, no network at render time.</footer>"
        + "</div></body></html>"
    )
    return head + body


def write_report_html(report: Report, path: str | Path, judge_eval=None) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report_html(report, judge_eval=judge_eval))
    return out
