"""An engagement: a named target, a written rule set, and an enforced scope.

Coehoorn has always been able to take an ``--agent URL``. What it has never had
is the artifact an engagement actually consists of — *who* we are allowed to
siege, *within what boundary*, *under whose authorization*, and *what the
findings deliverable looks like*. A URL flag is not an engagement; it is a
loaded gun with no paperwork.

This module is that paperwork, made executable:

* :class:`Engagement` — the machine-readable half of a rules-of-engagement
  document (``docs/engagements/*.yaml``). It names the target, points at the
  prose RoE, carries the rubric and the probe script, and states plainly
  whether the engagement is **authorized**.
* :class:`EngagementScope` — the boundary, enforced in code before any socket
  is opened.
* :func:`run_engagement` — a target-agnostic runner. It drives the *existing*
  :class:`~coehoorn.agent_adapter.HttpAgentAdapter` at a URL supplied by
  config, judges with the *existing* offline judge, and redacts with the
  *existing* :class:`~coehoorn.redact.RedactionPolicy`. Nothing about any
  particular target is compiled in.

Why the scope is an allowlist
-----------------------------
A runner that fetches an operator-supplied URL is SSRF surface: point it at
``169.254.169.254`` and it will happily read a cloud instance's credentials for
you. The usual mitigation — a denylist of reserved ranges — is the wrong shape
for this tool, because it fails open on every host nobody thought of.

The right shape follows from the premise: this tool is aimed at systems under a
written agreement, and the agreement names the hosts. So the engagement
declares an explicit allowlist, the code enforces exactly that list, and a
reserved address is refused *even when the operator allowlisted it* unless the
engagement carries a written opt-in (which is how a localhost rehearsal is
expressed). Every refusal names the rule that refused, because "it errored"
tells an operator nothing about whether to amend the agreement or stop typing.

Residual risk, stated rather than papered over: the address check resolves at
check time and httpx resolves again at connect time, so a DNS rebind between
the two is not defended against here. Closing it means a pinned-address
transport; that is not in this slice.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import __version__
from .redact import RedactionLevel, RedactionPolicy
from .schemas import Archetype

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
#: Resolve a host to every address a connection might land on. Injected so the
#: check is testable without a network, and so a caller can pin it.
Resolver = Callable[[str], "tuple[IpAddress, ...]"]

_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}


class RefusalRule(StrEnum):
    """Which clause refused a target.

    One flat namespace across the authorization check and the scope check, so
    an operator, a log line and a test all name the same thing. ``engagement.*``
    rules come from the paperwork; ``scope.*`` rules come from the boundary.
    """

    AUTHORIZED = "engagement.authorized"
    URL = "scope.url"
    SCHEME = "scope.allowed_schemes"
    HOST = "scope.allowed_hosts"
    PORT = "scope.allowed_ports"
    PATH = "scope.allowed_path_prefixes"
    RESOLUTION = "scope.resolvable"
    ADDRESS = "scope.allow_private_addresses"


class EngagementRefused(Exception):
    """A target was refused, and the refusal names the rule.

    ``target`` is redacted before it is stored, because a refusal message ends
    up in a terminal, a CI log and an incident channel — and the URL that was
    refused is precisely the shape most likely to carry a credential.
    """

    def __init__(self, rule: RefusalRule, target: str, detail: str) -> None:
        self.rule = rule
        self.target = target
        self.detail = detail
        super().__init__(f"refused by {rule.value}: {detail} [target: {target}]")


def system_resolver(host: str) -> tuple[IpAddress, ...]:
    """Resolve ``host`` to every address the OS would consider connecting to."""
    import socket

    try:
        return (ipaddress.ip_address(host),)
    except ValueError:
        pass
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return tuple(ipaddress.ip_address(info[4][0]) for info in infos)


def _is_reserved(addr: IpAddress) -> bool:
    """Is this an address an engagement must opt in to reach?

    IPv4-mapped IPv6 is unwrapped first: ``::ffff:169.254.169.254`` is a
    request to the metadata service wearing a hat, and whether the stdlib calls
    it "private" has changed between Python versions. Deciding it on the mapped
    address is both stable and true to what the socket will do.
    """
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


#: ASCII control characters. ``urlsplit`` strips these before parsing (CPython's
#: WHATWG-compatible sanitisation), which means a clause decided on the parse
#: never sees them while the raw string still carries them.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _remove_dot_segments(path: str) -> str | None:
    """RFC 3986 dot-segment removal. ``None`` when the path escapes the root.

    ``urlsplit`` does not do this, so ``/chat/../../admin`` satisfies a
    ``startswith("/chat")`` prefix check while every server on earth routes it
    to ``/admin``. Percent-encoded dots are classified too — ``%2e%2e`` is a
    ``..`` that survived one round of decoding.
    """
    if not path:
        return path
    segments = path.split("/")
    out: list[str] = []
    for i, raw in enumerate(segments):
        seg = unquote(raw) if "%" in raw else raw
        last = i == len(segments) - 1
        if seg == ".":
            if last:
                out.append("")
            continue
        if seg == "..":
            if len(out) <= 1:
                return None
            out.pop()
            if last:
                out.append("")
            continue
        out.append(raw)
    return "/".join(out)


class EngagementScope(BaseModel):
    """The boundary, declared in the engagement and enforced before any dial.

    ``allowed_hosts`` is matched **exactly** and case-insensitively. There are
    deliberately no wildcards: a wildcard is how a scope becomes "and anything
    that looks a bit like it", which is the opposite of an agreement. An empty
    ``allowed_ports`` or ``allowed_path_prefixes`` means "not narrowed" — the
    host allowlist and the address check are the security-relevant controls,
    and narrowing port/path is defence in depth an engagement may add.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_schemes: tuple[str, ...] = ("https",)
    allowed_hosts: tuple[str, ...] = Field(min_length=1)
    allowed_ports: tuple[int, ...] = ()
    allowed_path_prefixes: tuple[str, ...] = ()
    #: Written opt-in for loopback/private/link-local/reserved targets. This is
    #: how a localhost rehearsal is expressed — and the only way one is.
    allow_private_addresses: bool = False

    def check(
        self,
        url: str,
        *,
        resolver: Resolver | None = None,
        redaction: RedactionPolicy | None = None,
    ) -> str:
        """Return the in-scope target URL, else raise.

        Fail closed: every path out of this method is either a URL or an
        :class:`EngagementRefused` naming the rule. There is no third outcome
        and no "warn and continue".

        The URL returned is the one every clause was decided on — dot segments
        removed — and it is what the caller must dial. Checking one
        representation and handing the transport another is how a scope becomes
        advisory: ``/chat/../../admin`` satisfies a ``/chat`` prefix and reaches
        ``/admin``. Anything that cannot be reconciled that way (a control
        character, a path that climbs above the root) is refused rather than
        quietly rewritten, because an operator whose target was silently
        sanitised cannot tell what was actually dialled.
        """
        policy = redaction or RedactionPolicy.for_level(RedactionLevel.STANDARD)

        def refuse(rule: RefusalRule, detail: str) -> EngagementRefused:
            return EngagementRefused(rule, policy.endpoint(url), detail)

        if _CONTROL_CHARS.search(url):
            raise refuse(
                RefusalRule.URL,
                "target contains an ASCII control character; URL parsing strips "
                "these before any clause sees them, so the checked URL and the "
                "dialled URL would differ",
            )
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise refuse(RefusalRule.URL, f"target is not a parseable URL: {exc}") from exc
        if not parts.scheme or not parts.netloc:
            raise refuse(
                RefusalRule.URL,
                "target must be an absolute URL with a scheme and a host",
            )

        scheme = parts.scheme.lower()
        if scheme not in {s.lower() for s in self.allowed_schemes}:
            raise refuse(
                RefusalRule.SCHEME,
                f"scheme {scheme!r} is not one of {sorted(self.allowed_schemes)}",
            )

        try:
            host = (parts.hostname or "").lower()
        except ValueError as exc:
            raise refuse(RefusalRule.URL, f"target host is malformed: {exc}") from exc
        if not host:
            raise refuse(RefusalRule.URL, "target names no host")
        if host not in {h.lower() for h in self.allowed_hosts}:
            raise refuse(
                RefusalRule.HOST,
                f"host {host!r} is not in the engagement allowlist "
                f"{sorted(self.allowed_hosts)} (the allowlist is exact; "
                "subdomains are separate hosts)",
            )

        try:
            port = parts.port
        except ValueError as exc:
            raise refuse(RefusalRule.URL, f"target port is malformed: {exc}") from exc
        effective_port = port if port is not None else _DEFAULT_PORTS.get(scheme)
        if self.allowed_ports and effective_port not in self.allowed_ports:
            raise refuse(
                RefusalRule.PORT,
                f"port {effective_port} is not one of {sorted(self.allowed_ports)}",
            )

        normalized_path = _remove_dot_segments(parts.path)
        if normalized_path is None:
            raise refuse(
                RefusalRule.URL,
                f"path {parts.path!r} climbs above the root; it cannot be "
                "reconciled with any declared prefix",
            )
        if self.allowed_path_prefixes and not any(
            normalized_path.startswith(prefix) for prefix in self.allowed_path_prefixes
        ):
            raise refuse(
                RefusalRule.PATH,
                f"path {normalized_path!r} is outside "
                f"{sorted(self.allowed_path_prefixes)}"
                + (
                    f" (as written: {parts.path!r})"
                    if normalized_path != parts.path
                    else ""
                ),
            )

        resolve = resolver or system_resolver
        try:
            addresses = tuple(resolve(host))
        except OSError as exc:
            raise refuse(
                RefusalRule.RESOLUTION,
                f"host does not resolve, so it cannot be shown to be in scope: {exc}",
            ) from exc
        if not addresses:
            raise refuse(RefusalRule.RESOLUTION, "host resolved to no addresses")
        if not self.allow_private_addresses:
            # Refuse if ANY answer is reserved: the transport picks which
            # address it dials, we do not, so a split answer is a reachable
            # reserved address.
            reserved = [str(a) for a in addresses if _is_reserved(a)]
            if reserved:
                raise refuse(
                    RefusalRule.ADDRESS,
                    f"host resolves to reserved address(es) {reserved}; the "
                    "engagement does not set allow_private_addresses: true",
                )
        # Hand back exactly the representation that was checked.
        return urlunsplit(
            (parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment)
        )


class EngagementTarget(BaseModel):
    """Who is being besieged, and what wire it speaks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    wire_contract: str = "POST {conversation: [{role, content}, ...]} -> {reply: str}"
    #: Optional default endpoint. Usually absent: a real target's URL is
    #: supplied at run time (flag or env) so it is never committed.
    endpoint: str | None = None


class Engagement(BaseModel):
    """The machine-readable half of a rules-of-engagement document.

    The prose half lives at :attr:`rules_of_engagement` and is where a human
    reads what in/out of scope means and how findings are reported. This half
    is what the runner enforces, so the two cannot drift into a document that
    promises a boundary the code does not keep.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    #: Has the target's owner authorized this siege, in writing? An engagement
    #: that says no is a *defined* engagement, not a runnable one: the runner
    #: refuses it before an adapter exists. This is the field that keeps a
    #: committed scope file from being a loaded gun.
    authorized: bool
    #: Path (relative to this file) to the prose rules-of-engagement document.
    rules_of_engagement: str
    #: Path (relative to this file) to the rubric the siege judges against.
    rubric: str
    target: EngagementTarget
    scope: EngagementScope
    personas: int = Field(default=6, ge=1, le=99)
    turns: int = Field(default=4, ge=1, le=50)
    redaction: Literal["off", "standard", "strict"] = "standard"
    #: Per-archetype user-turn scripts. This is how an engagement supplies
    #: domain probes (a refund-approval surface is not asked about self-harm)
    #: without any target knowledge landing in the harness.
    probes: dict[Archetype, list[str]] = Field(default_factory=dict)
    #: Set by :func:`load_engagement`; any value in the YAML is discarded.
    source_dir: Path | None = None

    # -- paths -----------------------------------------------------------
    def _resolve(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        return ((self.source_dir or Path.cwd()) / p).resolve()

    def rubric_path(self) -> Path:
        return self._resolve(self.rubric)

    def roe_path(self) -> Path:
        return self._resolve(self.rules_of_engagement)

    # -- policy ----------------------------------------------------------
    def redaction_policy(self, custom: Sequence[Any] | None = None) -> RedactionPolicy:
        return RedactionPolicy.for_level(self.redaction, custom=custom)

    def _refusal_policy(self) -> RedactionPolicy:
        """Redaction used for refusal messages — never below ``standard``.

        An engagement may legitimately set ``redaction: off`` for a local stub
        whose transcript is not anyone's data. A refused URL is different: it
        is operator input that may carry a credential, and it is printed. So
        the floor here is ``standard`` regardless.
        """
        level = RedactionLevel(self.redaction)
        if level is RedactionLevel.OFF:
            level = RedactionLevel.STANDARD
        return RedactionPolicy.for_level(level)

    # -- the gate --------------------------------------------------------
    def check_target(self, url: str, *, resolver: Resolver | None = None) -> str:
        """Authorization first, then scope. Both fail closed, both name a rule."""
        policy = self._refusal_policy()
        if not self.authorized:
            raise EngagementRefused(
                RefusalRule.AUTHORIZED,
                policy.endpoint(url),
                f"engagement {self.id!r} is not authorized: no signed "
                f"authorization is on file, so no target may be dialled. See "
                f"{self.rules_of_engagement}.",
            )
        return self.scope.check(url, resolver=resolver, redaction=policy)


def load_engagement(path: str | Path) -> Engagement:
    """Parse an engagement YAML. A malformed engagement is a hard error."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Engagement YAML {str(p)!r} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"Engagement YAML must be a mapping; got {type(raw).__name__}"
        )
    data = dict(raw)
    # The loader owns provenance; a file may not declare where it came from.
    data.pop("source_dir", None)
    data["source_dir"] = p.resolve().parent
    return Engagement.model_validate(data)


# ---------------------------------------------------------------------------
# findings + the run record
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """One cited breach, in the shape a client reads it.

    Everything here resolves: ``cited_turn_index`` is a turn of the named
    persona's transcript in the run report beside it. A finding you cannot
    click through to is an opinion.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_id: str
    archetype: Archetype
    criterion_id: str
    critical: bool
    cited_turn_index: int
    rationale: str


@dataclass(frozen=True)
class EngagementResult:
    """What one engagement run produced. Paths are on disk, counts are real."""

    engagement_id: str
    run_id: str
    target: str
    findings: tuple[Finding, ...]
    approaches_attempted: int
    transcripts: int
    partial: bool
    report_json: Path
    report_html: Path
    record_json: Path


async def run_engagement(
    engagement: Engagement,
    *,
    target: str | None = None,
    out_dir: str | Path,
    env: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
    timeout: float = 30.0,
    concurrency: int = 4,
) -> EngagementResult:
    """Conduct one engagement against a scoped HTTP target.

    Target resolution, most explicit first: the ``target`` argument, then the
    engagement's own ``target.endpoint``, then ``AGENT_ENDPOINT`` /
    ``COEHOORN_AGENT_ENDPOINT`` from ``env``. Whatever wins is put through
    :meth:`Engagement.check_target` before an adapter is constructed — the
    refusal happens with no socket open and no credential sent.

    Judging is the offline heuristic judge: an engagement run is reproducible
    and needs no model key. LLM-mode personas and judge are deliberately not
    wired here.
    """
    # Local imports: the engagement seam is additive, and this keeps the
    # module's import cost off the core path.
    from .agent_adapter import HttpAgentAdapter
    from .aggregator import build_report, write_report_json
    from .config import headers_from_env, resolve_endpoint
    from .conversation import run_conversations_resilient
    from .judge import judge_all
    from .personas import generate_personas_heuristic
    from .redact import patterns_from_rubric_file
    from .report_html import write_report_html
    from .rubric_parser import parse_rubric_file
    from .schemas import CriterionStatus, VerdictOutcome

    url = resolve_endpoint(target or engagement.target.endpoint, env)
    if not url:
        raise EngagementRefused(
            RefusalRule.URL,
            "(none)",
            f"engagement {engagement.id!r} has no target: pass one explicitly, "
            "set target.endpoint in the engagement, or set AGENT_ENDPOINT.",
        )
    # THE gate. Nothing below this line runs for an out-of-scope target.
    url = engagement.check_target(url, resolver=resolver)

    rubric_path = engagement.rubric_path()
    rubric, heuristic_rules = parse_rubric_file(rubric_path)
    redaction = engagement.redaction_policy(patterns_from_rubric_file(rubric_path))
    target_shown = redaction.endpoint(url)

    personas = generate_personas_heuristic(n=engagement.personas)
    probe_overrides = {
        p.id: list(engagement.probes[p.archetype])
        for p in personas
        if p.archetype in engagement.probes
    }

    started = datetime.now(UTC)
    async with HttpAgentAdapter(
        url, timeout=timeout, headers=headers_from_env(env) or None
    ) as agent:
        outcome = await run_conversations_resilient(
            personas,
            agent,
            max_turns=engagement.turns,
            mode="heuristic",
            rubric=rubric,
            concurrency=concurrency,
            probe_overrides=probe_overrides or None,
        )
    # Redact once, at the transcript boundary, before anything is judged or
    # written — the same boundary `coehoorn run` uses. No second redactor.
    transcripts = [redaction.transcript(t) for t in outcome.transcripts]
    errors = [redaction.approach_error(e) for e in outcome.errors]
    if not transcripts:
        raise EngagementRefused(
            RefusalRule.RESOLUTION,
            target_shown,
            f"no approach completed ({len(errors)} of {len(personas)} failed); "
            "an engagement with no transcript has no findings to report.",
        )

    verdicts = judge_all(transcripts, rubric, heuristic_rules, mode="heuristic")
    completed = datetime.now(UTC)
    report = build_report(
        rubric=rubric,
        transcripts=transcripts,
        verdicts=verdicts,
        agent_endpoint=target_shown,
        created_at=started,
        completed_at=completed,
        errors=errors,
    )

    persona_by_tid = {t.id: t.persona for t in transcripts}
    criteria_by_id = {c.id: c for c in rubric.criteria}
    findings: list[Finding] = []
    for v in verdicts:
        if v.outcome is not VerdictOutcome.FAIL:
            continue
        persona = persona_by_tid[v.transcript_id]
        for cv in v.criterion_verdicts:
            if cv.status is not CriterionStatus.FAIL or cv.cited_turn_index is None:
                continue
            findings.append(
                Finding(
                    persona_id=persona.id,
                    archetype=persona.archetype,
                    criterion_id=cv.criterion_id,
                    critical=criteria_by_id[cv.criterion_id].failure_is_critical,
                    cited_turn_index=cv.cited_turn_index,
                    rationale=cv.rationale.strip(),
                )
            )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = out / report.run_id
    report_json = write_report_json(report, base.with_suffix(".json"))
    report_html = write_report_html(report, base.with_suffix(".html"))
    record_json = _write_record(
        out / f"{report.run_id}.engagement.json",
        engagement=engagement,
        report=report,
        target_shown=target_shown,
        findings=findings,
        rubric_path=rubric_path,
        report_json=report_json,
        report_html=report_html,
    )

    return EngagementResult(
        engagement_id=engagement.id,
        run_id=report.run_id,
        target=target_shown,
        findings=tuple(findings),
        approaches_attempted=report.approaches_attempted,
        transcripts=len(transcripts),
        partial=report.partial,
        report_json=report_json,
        report_html=report_html,
        record_json=record_json,
    )


def register_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``engage`` subcommand and set ``._func``.

    The module owns its CLI surface; ``cli.build_parser()`` adds one wiring
    call, matching how every other extension in this package registers itself.

    Note what this command deliberately does *not* do: it does not load a
    ``.env`` file. ``coehoorn run`` does, and for a chat siege that is a
    convenience. Here the environment can name the *target*, and a runner that
    silently picks up a target from a dotfile in the working directory is a
    runner that can be redirected by a file nobody read. Auth and endpoint are
    taken from the process environment only.
    """
    p = subparsers.add_parser(
        "engage",
        help="Conduct a defined engagement against a scoped HTTP target.",
        description=(
            "Run an engagement defined in docs/engagements/<name>.yaml. The "
            "target must satisfy the engagement's authorization and scope "
            "rules; a refusal names the rule that refused it and exits 2."
        ),
    )
    p.add_argument("--engagement", required=True, help="Path to an engagement YAML.")
    p.add_argument(
        "--target", default=None,
        help=(
            "Target URL. Falls back to the engagement's target.endpoint, then "
            "AGENT_ENDPOINT / COEHOORN_AGENT_ENDPOINT. Whichever wins is "
            "checked against the engagement scope before anything is dialled."
        ),
    )
    p.add_argument("--out", default="runs", help="Output directory (default runs/).")
    p.add_argument("--timeout", type=float, default=30.0, help="Target HTTP timeout seconds.")
    p.add_argument("--concurrency", type=int, default=4, help="Max parallel approaches.")
    p.add_argument(
        "--json", action="store_true", help="Emit a JSON summary to stdout (logs to stderr)."
    )
    p.add_argument(
        "--fail-on-finding", dest="fail_on_finding", action="store_true",
        help="Exit non-zero if the engagement produced any finding (gate semantics).",
    )
    p.set_defaults(_func=lambda a: asyncio.run(_cmd_engage(a)))


async def _cmd_engage(args: argparse.Namespace) -> int:
    """Discovery semantics: findings exit 0. A *refusal* exits 2."""
    log_stream = sys.stderr if args.json else sys.stdout

    def log(msg: str) -> None:
        print(msg, file=log_stream)

    try:
        engagement = load_engagement(args.engagement)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    log(f"engagement: {engagement.id}  (authorized: {engagement.authorized})")
    log(f"rules of engagement: {engagement.rules_of_engagement}")
    log(f"scope: {', '.join(engagement.scope.allowed_hosts)} over "
        f"{', '.join(engagement.scope.allowed_schemes)}"
        f"{'  [private addresses opted in]' if engagement.scope.allow_private_addresses else ''}")

    try:
        result = await run_engagement(
            engagement,
            target=args.target,
            out_dir=args.out,
            timeout=args.timeout,
            concurrency=args.concurrency,
        )
    except EngagementRefused as refused:
        print(f"error: {refused}", file=sys.stderr)
        return 2
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    by_criterion: dict[str, int] = {}
    for f in result.findings:
        by_criterion[f.criterion_id] = by_criterion.get(f.criterion_id, 0) + 1

    if args.json:
        print(json.dumps({
            "engagement_id": result.engagement_id,
            "authorized": engagement.authorized,
            "target": result.target,
            "run_id": result.run_id,
            "approaches_attempted": result.approaches_attempted,
            "approaches_completed": result.transcripts,
            "partial": result.partial,
            "findings": len(result.findings),
            "findings_by_criterion": by_criterion,
            "record_json": str(result.record_json),
            "report_json": str(result.report_json),
            "report_html": str(result.report_html),
        }, indent=2))
    else:
        log(f"target: {result.target}")
        log(
            f"\nresult: {len(result.findings)} finding(s) across "
            f"{result.transcripts} of {result.approaches_attempted} approaches"
        )
        for f in result.findings:
            mark = "critical" if f.critical else "finding"
            log(f"  [{mark}] {f.persona_id} ({f.archetype.value}) "
                f"{f.criterion_id} @ turn {f.cited_turn_index}")
        if result.partial:
            log(
                "PARTIAL: at least one approach never reached the wall; the "
                "counts above cover the ones that did."
            )
        log(f"record: {result.record_json}")
        log(f"json:   {result.report_json}")
        log(f"html:   {result.report_html}")

    return 1 if (args.fail_on_finding and result.findings) else 0


def _write_record(
    path: Path,
    *,
    engagement: Engagement,
    report: Any,
    target_shown: str,
    findings: Sequence[Finding],
    rubric_path: Path,
    report_json: Path,
    report_html: Path,
) -> Path:
    """Write the engagement record: the rules applied, and what was found.

    Separate from the run report on purpose. The run report answers "what did
    the agent do"; this answers "under what agreement did we ask, and what are
    we handing back". A reader who only gets this file can still tell whether
    the siege was authorized, where it was allowed to point, and how many
    approaches never landed.
    """
    record = {
        "engagement_id": engagement.id,
        "coehoorn_version": __version__,
        "authorized": engagement.authorized,
        "rules_of_engagement": str(engagement.rules_of_engagement),
        "target": {
            "name": engagement.target.name,
            "endpoint": target_shown,
            "wire_contract": engagement.target.wire_contract,
        },
        "scope": engagement.scope.model_dump(mode="json"),
        "method": {
            "mode": "heuristic",
            "judge": "offline heuristic (no model call)",
            "rubric": rubric_path.name,
            "personas": engagement.personas,
            "turns": engagement.turns,
            "redaction": engagement.redaction,
        },
        "run_id": report.run_id,
        "started_at": report.created_at.isoformat(),
        "completed_at": report.completed_at.isoformat(),
        "approaches_attempted": report.approaches_attempted,
        "approaches_completed": len(report.transcripts),
        "partial": report.partial,
        "errors": [
            {
                "persona_id": e.persona_id,
                "archetype": e.archetype.value,
                "error_class": e.error_class.value,
                "message": e.message,
            }
            for e in report.errors
        ],
        "findings": [f.model_dump(mode="json") for f in findings],
        "artifacts": {"report_json": report_json.name, "report_html": report_html.name},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path
