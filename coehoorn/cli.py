"""Coehoorn command-line interface.

  coehoorn run --rubric examples/rubric_coach.yaml \\
             --agent http://127.0.0.1:8001/chat \\
             --personas 6 --turns 4 --out runs/

  coehoorn compare --report runs/<id>.json \\
                 --expected examples/expected_failures.yaml

  coehoorn meta-eval --gold tests/gold/judge_gold.jsonl \\
                   --rubric examples/rubric_coach.yaml

  coehoorn self-play --rubric examples/rubric_coach.yaml \\
                   --gold tests/gold/judge_gold.jsonl \\
                   --agent http://127.0.0.1:8001/chat \\
                   --criterion safe_handling_of_self_harm

The CLI is the canonical interface. The HTML report is a side effect of
`run` and is opened by clicking the printed path; there is no localhost
server.

Heuristic mode is deterministic by construction (no RNG in persona or probe
selection), so there is deliberately no --seed flag: the same inputs already
produce a byte-identical report. `--json` emits a stable, scriptable summary
to stdout (human logs go to stderr); breaches are findings, not failures, so
the exit code is 0 unless you opt into gate semantics with --fail-on-breach.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from . import __version__
from .agent_adapter import HttpAgentAdapter
from .aggregator import (
    build_report,
    compare_to_expected,
    load_report_json,
    write_comparison_json,
    write_report_json,
)
from .config import headers_from_env, resolve_endpoint
from .conversation import run_conversations
from .judge import judge_all
from .meta_eval import evaluate_gold, load_gold_cases
from .metrics import metrics_from_comparison
from .personas import generate_personas_heuristic, generate_personas_llm
from .report_html import write_report_html
from .rubric_parser import parse_rubric_file
from .schemas import VerdictOutcome


def _pick_mode(explicit: str | None, allow_llm: bool) -> str:
    if explicit in {"heuristic", "llm"}:
        if explicit == "llm" and not allow_llm:
            print(
                "error: --mode llm requested but ANTHROPIC_API_KEY is not set.",
                file=sys.stderr,
            )
            sys.exit(2)
        return explicit
    return "llm" if allow_llm else "heuristic"


async def _cmd_run(args: argparse.Namespace) -> int:
    load_dotenv()
    # When emitting JSON, keep stdout clean: human logs go to stderr.
    log_stream = sys.stderr if args.json else sys.stdout

    def log(msg: str) -> None:
        print(msg, file=log_stream)

    # Resolve the target endpoint: explicit --agent wins, else AGENT_ENDPOINT /
    # COEHOORN_AGENT_ENDPOINT from the env (the seam CI uses to inject a
    # secret/variable). Fail fast and clearly if neither is present.
    endpoint = resolve_endpoint(args.agent)
    if not endpoint:
        print(
            "error: no target agent endpoint. Pass --agent URL or set "
            "AGENT_ENDPOINT (see docs/ENGAGEMENT_TEMPLATE.md).",
            file=sys.stderr,
        )
        return 2
    args.agent = endpoint
    agent_headers = headers_from_env()

    rubric, heuristic_rules = parse_rubric_file(args.rubric)
    allow_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    mode = _pick_mode(args.mode, allow_llm)

    log(f"mode: {mode}")
    log(f"agent: {args.agent}")
    if agent_headers:
        # Confirm auth is wired without ever printing the value.
        log(f"agent auth: {', '.join(sorted(agent_headers))} header(s) from env")
    log(f"personas: {args.personas} / turns: {args.turns}")
    log(f"rubric: {args.rubric}  (criteria: {len(rubric.criteria)})")

    started = datetime.now(UTC)
    if mode == "llm":
        personas = generate_personas_llm(rubric, n=args.personas)
    else:
        personas = generate_personas_heuristic(n=args.personas)
    log(f"generated {len(personas)} personas")

    # Opt-in: append the KB-poisoner (write-back contamination) persona and fold
    # its dedicated probe script + tool-policy/content criteria into this run, so
    # the agent-write-back surface is exercised end-to-end. Its criteria never
    # fire on the other personas (their probes miss the keywords / take no
    # KB-write tool), so this only adds the new face — it changes no other cell.
    probe_overrides: dict[str, list[str]] | None = None
    if args.include_kb_poisoner:
        from .personas_kb import (
            KB_POISONER_PROBES,
            kb_poisoner_persona,
            merge_kb_poisoner_rubric,
        )

        kb_persona = kb_poisoner_persona(f"p{len(personas):02d}")
        personas.append(kb_persona)
        probe_overrides = {kb_persona.id: KB_POISONER_PROBES}
        rubric, heuristic_rules = merge_kb_poisoner_rubric(rubric, heuristic_rules)
        log(
            f"included KB-poisoner persona {kb_persona.id} ({kb_persona.name}); "
            f"rubric now has {len(rubric.criteria)} criteria"
        )

    async with HttpAgentAdapter(
        args.agent, timeout=args.timeout, headers=agent_headers or None
    ) as agent:
        transcripts = await run_conversations(
            personas, agent, max_turns=args.turns, mode=mode,
            rubric=rubric, concurrency=args.concurrency,
            probe_overrides=probe_overrides,
        )
    log(f"ran {len(transcripts)} conversations")

    verdicts = judge_all(transcripts, rubric, heuristic_rules, mode=mode)
    completed = datetime.now(UTC)
    report = build_report(
        rubric=rubric, transcripts=transcripts, verdicts=verdicts,
        agent_endpoint=args.agent, created_at=started, completed_at=completed,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / report.run_id
    json_path = write_report_json(report, base.with_suffix(".json"))
    html_path = write_report_html(report, base.with_suffix(".html"))

    extra_paths: dict[str, str] = {}
    emit = {s.strip() for s in args.emit.split(",") if s.strip()}
    if "sarif" in emit:
        from .outputs import write_sarif
        extra_paths["sarif"] = str(write_sarif(report, out_dir / f"{report.run_id}.sarif.json"))
    if "junit" in emit:
        from .outputs import write_junit
        extra_paths["junit"] = str(write_junit(report, out_dir / f"{report.run_id}.junit.xml"))

    breaches = sum(1 for v in verdicts if v.outcome is VerdictOutcome.FAIL)
    held = sum(1 for v in verdicts if v.outcome is VerdictOutcome.PASS)
    abstained = sum(1 for v in verdicts if v.outcome is VerdictOutcome.ABSTAIN)

    if args.json:
        # Stable, documented key set for `coehoorn run --json | jq`.
        print(json.dumps({
            "run_id": report.run_id,
            "mode": mode,
            "agent_endpoint": args.agent,
            "personas": args.personas,
            "turns": args.turns,
            "transcripts": len(transcripts),
            "breaches": breaches,
            "held": held,
            "abstained": abstained,
            "pass_rate": report.pass_rate,
            "abstention_rate": report.abstention_rate,
            "breaches_by_archetype": report.failures_by_archetype,
            "json_path": str(json_path),
            "html_path": str(html_path),
            **{f"{k}_path": v for k, v in extra_paths.items()},
        }, indent=2))
    else:
        log(
            f"\nresult: {breaches}/{len(verdicts)} approaches breached "
            f"({report.pass_rate * 100:.0f}% held, {report.abstention_rate * 100:.0f}% abstained)"
        )
        log(f"json:  {json_path}")
        log(f"html:  {html_path}")
        for k, p in extra_paths.items():
            log(f"{k}:{' ' * (5 - len(k))}{p}")

    # Discovery semantics: finding breaches is success. Opt into gate
    # semantics with --fail-on-breach.
    return 1 if (args.fail_on_breach and breaches > 0) else 0


def _cmd_compare(args: argparse.Namespace) -> int:
    try:
        report = load_report_json(args.report)
        raw = yaml.safe_load(Path(args.expected).read_text())
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw, dict) or "personas" not in raw:
        print(
            f"error: expected file {args.expected!r} must be a mapping with a "
            "'personas' key.",
            file=sys.stderr,
        )
        return 2
    expected = raw["personas"]
    if not isinstance(expected, dict):
        print(
            "error: 'personas' must be a mapping of persona_id -> [criterion_id, ...]",
            file=sys.stderr,
        )
        return 2

    diff = compare_to_expected(report, expected)
    if args.out:
        out = write_comparison_json(diff, args.out)
        print(f"comparison written to {out}", file=sys.stderr)
    m = metrics_from_comparison(diff)
    o = m.overall
    print(json.dumps({
        "personas_compared": len(diff),
        "exact_matches": sum(1 for d in diff.values() if d["match"]),
        "true_positives": o.tp,
        "false_positives": o.fp,
        "false_negatives": o.fn,
        "true_negatives": o.tn,
        "abstained": m.abstained,
        "precision": o.precision.value,
        "recall": o.recall.value,
        "f1": o.f1,
    }, indent=2))
    return 0 if (o.fp == 0 and o.fn == 0) else 1


def _cmd_meta_eval(args: argparse.Namespace) -> int:
    try:
        rubric, rules = parse_rubric_file(args.rubric)
        cases = load_gold_cases(args.gold)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = evaluate_gold(cases, rubric, rules)
    m = result.metrics

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        def rate(est):
            if est.value is None:
                return "n/a"
            return f"{est.value:.2f} (95% CI {est.lower:.2f}-{est.upper:.2f}, n={est.denominator})"

        def num(x):
            # balanced accuracy / kappa are None when a class is absent
            # (single-class gold) — never crash the human path on it.
            return "n/a" if x is None else f"{x:.3f}"

        print("judge meta-eval — heuristic judge vs gold", file=sys.stderr)
        print(
            f"  scored cells: {result.n_scored}  (abstained, excluded: {result.n_abstained})",
            file=sys.stderr,
        )
        print(f"  confusion: TP={m.tp} FP={m.fp} FN={m.fn} TN={m.tn}", file=sys.stderr)
        print(f"  precision: {rate(m.precision)}", file=sys.stderr)
        print(f"  recall:    {rate(m.recall)}", file=sys.stderr)
        print(
            f"  balanced accuracy: {num(m.balanced_accuracy)}"
            f"   (always-breach {num(result.baseline_always_breach.balanced_accuracy)},"
            f" always-hold {num(result.baseline_always_hold.balanced_accuracy)})",
            file=sys.stderr,
        )
        print(f"  Cohen's kappa: {num(m.cohens_kappa)}", file=sys.stderr)

    # Optional regression gate on the interval floor (the honest discipline).
    if args.min_recall_lower is not None and m.recall.lower < args.min_recall_lower:
        print(
            f"GATE FAILED: recall lower bound {m.recall.lower:.3f} "
            f"(n={m.recall.denominator}) < floor {args.min_recall_lower}",
            file=sys.stderr,
        )
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="coehoorn",
        description="Local adversarial simulation harness for chat and tool-using agents.",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"coehoorn {__version__}",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run personas against an agent and write a report.")
    run_p.add_argument("--rubric", required=True, help="Path to rubric YAML.")
    run_p.add_argument(
        "--agent", default=None,
        help=(
            "HTTP endpoint of the target agent (e.g. http://127.0.0.1:8001/chat). "
            "Falls back to the AGENT_ENDPOINT / COEHOORN_AGENT_ENDPOINT env var "
            "when omitted, so CI can inject it from a secret/variable. Auth to "
            "the target is read from AGENT_API_KEY or AGENT_AUTH_HEADER."
        ),
    )
    run_p.add_argument("--personas", type=int, default=6, help="Number of personas (default 6).")
    run_p.add_argument(
        "--turns", type=int, default=4, help="Max turns per conversation (default 4)."
    )
    run_p.add_argument(
        "--mode", choices=["heuristic", "llm", "auto"], default="auto",
        help="heuristic | llm | auto (auto = llm if ANTHROPIC_API_KEY else heuristic).",
    )
    run_p.add_argument("--out", default="runs", help="Output directory (default runs/).")
    run_p.add_argument("--timeout", type=float, default=30.0, help="Agent HTTP timeout seconds.")
    run_p.add_argument("--concurrency", type=int, default=4, help="Max parallel conversations.")
    run_p.add_argument(
        "--json", action="store_true", help="Emit a JSON summary to stdout (logs to stderr)."
    )
    run_p.add_argument(
        "--fail-on-breach", action="store_true",
        help="Exit non-zero if any approach breached (opt-in gate semantics).",
    )
    run_p.add_argument(
        "--emit", default="",
        help="Comma-separated extra CI outputs: sarif,junit (in addition to json+html).",
    )
    run_p.add_argument(
        "--include-kb-poisoner", dest="include_kb_poisoner", action="store_true",
        help=(
            "Append the KB-poisoner (agent write-back contamination) persona and "
            "fold its dedicated probe script + write-back criteria into the run "
            "(OWASP LLM01 via the memory/KB surface; ASI02/ASI03 tool policy)."
        ),
    )
    run_p.set_defaults(_func=lambda a: asyncio.run(_cmd_run(a)))

    cmp_p = sub.add_parser(
        "compare", help="Compare a report's breaches to an expected-failures YAML."
    )
    cmp_p.add_argument("--report", required=True, help="Path to runs/<id>.json")
    cmp_p.add_argument("--expected", required=True, help="Path to expected_failures.yaml")
    cmp_p.add_argument("--out", default=None, help="Optional path to write the diff JSON.")
    cmp_p.set_defaults(_func=_cmd_compare)

    me_p = sub.add_parser(
        "meta-eval", help="Audit the auditor: score the judge against a gold fixture."
    )
    me_p.add_argument("--gold", required=True, help="Path to a gold JSONL fixture.")
    me_p.add_argument("--rubric", required=True, help="Rubric YAML supplying the heuristic rules.")
    me_p.add_argument(
        "--json", action="store_true", help="Emit the full scorecard as JSON to stdout."
    )
    me_p.add_argument(
        "--min-recall-lower", type=float, default=None,
        help="Gate: exit non-zero if the recall Wilson lower bound falls below this floor.",
    )
    me_p.set_defaults(_func=_cmd_meta_eval)

    # Citation-integrity suite + self-play: each module owns its own subparser
    # surface, registered here so build_parser() stays the single CLI assembly
    # point.
    from .distill import register_subparser as _register_distill_floor
    from .mcp_redteam import register_subparser as _register_mcp_siege
    from .metamorphic import register_subparser as _register_metamorphic
    from .mutants import register_subparser as _register_mutation_score
    from .overfit import register_subparser as _register_overfit_audit
    from .selective_risk import register_subparser as _register_selective_risk
    from .selfplay.cli import register_subparser as _register_self_play

    _register_mutation_score(sub)
    _register_metamorphic(sub)
    _register_overfit_audit(sub)
    _register_distill_floor(sub)
    _register_selective_risk(sub)
    _register_self_play(sub)
    _register_mcp_siege(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    mode_arg = getattr(args, "mode", None)
    if mode_arg == "auto":
        args.mode = None
    return args._func(args)


if __name__ == "__main__":
    raise SystemExit(main())
