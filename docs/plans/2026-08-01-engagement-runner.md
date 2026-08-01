# Plan — the engagement spine: a scoped, target-agnostic runner

Date: 2026-08-01
Branch: `elite/error-outcomes-and-redaction`
Status: vertical slice, not the flagship

## Goal

Close the repo's biggest credibility gap in *structure*, not in claim.

Today every catch Coehoorn can show is against `apps/stub-agent`, a target this
repo wrote and deliberately flawed. The tool has an `--agent URL` flag and a
config shim, but it has never had the thing an FDE actually delivers: an
**engagement** — a named target, a written rule set, a machine-enforced scope,
and a findings artifact that says which rules were applied and what was found.

This slice builds that spine and proves it end to end against a real HTTP
target over a real socket, deterministically, with no network egress and no
model call.

**What this slice does NOT do, and the docs must not say it does:** it does not
run a live siege of Farthing (or any third party). No external endpoint was
dialled. The first target is *defined*, scoped and marked unauthorized; running
it needs a signed authorization and an endpoint this repo does not have.

## Architecture

New module `coehoorn/engagement.py`. One new seam, contract-first:

```
Engagement (pydantic, extra=forbid, frozen)
  id, authorized, target{name,description,wire_contract,endpoint?},
  scope: EngagementScope, rubric, personas, turns, redaction,
  probes{archetype: [user turns]}, rules_of_engagement (doc path)

EngagementScope.check(url, *, redaction, resolver) -> str | raises OutOfScope
  ordered rules, fail closed, each refusal names the rule that refused:
    engagement.authorized   — an unauthorized engagement may not be dialled
    scope.url               — unparseable / no scheme+host
    scope.allowed_schemes
    scope.allowed_hosts     — exact, case-insensitive, NO wildcards
    scope.allowed_ports     — empty tuple = any port on an allowed host
    scope.allowed_path_prefixes
    scope.resolvable        — DNS failure is a refusal, never a pass-through
    scope.allow_private_addresses
                            — loopback/private/link-local/reserved/multicast/
                              unspecified (and IPv4-mapped IPv6 forms) refused
                              unless the engagement explicitly opts in

run_engagement(engagement, *, target=None, out_dir, env, resolver)
    -> EngagementResult{engagement_id, run_id, target(redacted), findings[],
                        partial, artifacts}
```

The runner is target-agnostic: it drives the **existing** `HttpAgentAdapter`
against a URL resolved as `--target` > `engagement.target.endpoint` >
`config.resolve_endpoint(env)`, and authenticates with the **existing**
`config.headers_from_env`. Judging is the existing offline heuristic judge.
Redaction is the **existing** `RedactionPolicy` — the URL that reaches an
artifact is `policy.endpoint(url)`, never the raw one, so a credentialed
target (`https://user:pw@host/`, `?api_key=…`) cannot land in the engagement
record. No second redactor.

Why the SSRF control is an allowlist and not a denylist: this tool's premise is
that it is aimed at systems under an engagement agreement. The agreement names
the hosts; the code enforces exactly that list. A denylist of "bad" ranges is
the wrong shape — it fails open on everything nobody thought of.

Artifacts per run: the existing `<run_id>.json` + `<run_id>.html`, plus a new
`<run_id>.engagement.json` — the engagement record: which rules were applied,
which target (redacted), which findings, how many approaches never landed.

CLI: `coehoorn engage --engagement <yaml> [--target URL] [--out DIR] [--json]`,
registered via the module's own `register_subparser`, matching how
`mutants`/`metamorphic`/`selfplay` already extend the CLI.

Rehearsal target: `apps/approval-stub/` — a stdlib-only HTTP server that mimics
a refund-approval surface's contract (a decision request in, a verdict out). It
carries one **documented, deliberate** weakness so the spine has something to
find. Catching it proves plumbing, not prowess; the docs say exactly that.

## TDD tasks

1. **RED/GREEN — scope refuses what it must.** Table + seeded generator loop
   (no PBT lib in this repo; a deterministic loop in pytest instead) over
   schemes, hosts, ports, paths and address families. Invariant: for every
   generated URL, `check` either returns a URL whose host is in
   `allowed_hosts` and whose resolved addresses are all public (or the
   engagement opted in), or raises `OutOfScope` naming a rule. Never a third
   outcome.
2. **RED/GREEN — cloud metadata is refused even when allowlisted.**
   `169.254.169.254` in `allowed_hosts` with `allow_private_addresses: false`
   must still refuse, naming `scope.allow_private_addresses`.
3. **RED/GREEN — an unauthorized engagement is never dialled.** The refusal
   happens before any adapter exists.
4. **RED/GREEN — the refusal message cannot leak the credential** it refused.
5. **RED/GREEN — end to end over a real socket.** Bind
   `apps/approval-stub` on 127.0.0.1:0 in-process, point the rehearsal
   engagement at it, assert: a report json, an html, and an
   `.engagement.json` carrying ≥1 finding cited to a turn that exists.
6. **RED/GREEN — the artifact redacts a credentialed target URL.**
7. **Docs.** `docs/engagements/farthing-approval-surface.md` (the RoE), its
   YAML, the rehearsal YAML, and an honest README paragraph that under-claims.

## Out of scope (cut deliberately, say so)

- Any live dial of a third-party endpoint.
- LLM-mode personas/judge in an engagement (heuristic only here).
- Adapters for wire shapes other than `{conversation} -> {reply}`.
- DNS-rebinding defence: the scope check resolves at check time, httpx
  re-resolves at connect time. Documented as residual risk, not fixed.
