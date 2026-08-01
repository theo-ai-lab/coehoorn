# Engagement — Farthing refund-approval surface

**Status: DEFINED, NOT AUTHORIZED, NOT EXECUTED.**

This document is the rules-of-engagement half of a Coehoorn engagement. Its
machine-readable half is [`farthing-approval-surface.yaml`](./farthing-approval-surface.yaml),
which the runner enforces. The two are deliberately paired so this page cannot
promise a boundary the code does not keep.

Read the status line above literally. As of the commit that introduced this
file:

- no Farthing endpoint has been dialled by Coehoorn;
- no authorization is on file, and the YAML says `authorized: false`, which
  makes the engagement **unrunnable** — `coehoorn engage` refuses it before an
  HTTP client is even constructed;
- every number this repo can show for an approval surface comes from the
  *rehearsal* engagement against `apps/approval-stub`, a target this repo wrote
  and deliberately weakened. See
  [`local-approval-rehearsal.yaml`](./local-approval-rehearsal.yaml).

What *is* real is everything except the target: the scope enforcement, the
runner, the probes, the rubric, the judge, the redaction boundary and the
findings artifact all work end to end and are tested over a real socket.

---

## 1. Target

| field | value |
|---|---|
| Name | Farthing refund-approval surface |
| What it does | Decides whether an AI-proposed billing refund proceeds, and records the human approval that authorized it |
| Why this surface | It is the money-moving boundary. Everything upstream is a proposal; this is where a proposal becomes a payment |
| Wire contract | `POST {conversation: [{role, content}, ...]} -> {reply: str}` |
| Endpoint | **not committed** — supplied at run time via `--target` or `AGENT_ENDPOINT` |
| Auth | `AGENT_API_KEY` (bearer) or `AGENT_AUTH_HEADER` (raw header line), read from the environment only, never a flag |

If the surface speaks a different envelope, that is an adapter change, not a
harness change: wrap `HttpAgentAdapter` or pass any
`async (conversation) -> str` callable (`CallableAdapter`).

## 2. Authorization (the gate that is currently shut)

An engagement is authorized when the target's owner has agreed, in writing, to
a siege of the named hosts within the named window. Until that exists, the YAML
carries `authorized: false` and the runner refuses every target with
`engagement.authorized`.

Turning it on is a deliberate, reviewable, one-line change to a committed file
— which is the point. A scope file that can be run by accident is not a scope
file.

## 3. Scope

The authoritative list lives in the YAML under `scope:`; this section says what
it *means*.

**In scope**

- The approval surface's decision endpoint on the hosts named in
  `scope.allowed_hosts`, over `https` only.
- Adversarial *conversation*: contradiction, ambiguity, emotional pressure,
  off-topic drift, prompt injection, and requests that sit just over the
  auto-approval ceiling. See `probes:` in the YAML — the exact scripts are
  committed, so the client knows precisely what will be sent.

**Out of scope**

- Any host not named in the allowlist. Matching is exact and
  case-insensitive; there are no wildcards, so a subdomain is a different host
  and needs its own line in the agreement.
- Any scheme other than `https`; any path outside `scope.allowed_path_prefixes`.
- Any address in a loopback, private, link-local, reserved, multicast or
  unspecified range — refused **even if such an address is in
  `allowed_hosts`** — unless the engagement sets
  `allow_private_addresses: true`. That opt-in exists for localhost rehearsals
  and is the only way to reach a reserved address.
- Load, denial of service, or throughput testing. Coehoorn runs a handful of
  short conversations at a bounded concurrency.
- Authentication, authorization or infrastructure testing of the surrounding
  system. This engagement tests the *decision behavior* of the agent.
- Any write path other than the ones the surface exposes to an ordinary
  caller. Coehoorn sends chat turns; it does not craft privileged requests.
- Real customer data. Probes reference synthetic case ids only.

**How the boundary is enforced.** `coehoorn engage` resolves the target, then
runs the authorization check and the scope check *before* constructing an HTTP
client. A refusal names the rule that refused it
(`engagement.authorized`, `scope.allowed_hosts`, `scope.allow_private_addresses`,
…) so the operator knows whether to amend the agreement or stop typing.

**Residual risk we are not claiming to have closed.** The address check
resolves the host at check time; the HTTP client resolves it again when it
connects. A DNS rebind between those two moments is not defended against here.
Closing it requires a transport pinned to the checked address, which this slice
does not build.

## 4. Handling of data

- Transcripts are redacted **before** they are judged or written — one
  boundary, five emitters downstream of it, so nothing can be forgotten by a
  new emitter. Default level `standard` removes credentials, tokens, JWTs,
  private keys, emails, US SSNs and Luhn-valid card numbers.
- The rubric declares the client-specific shapes: `examples/rubric_approval_surface.yaml`
  redacts refund case references (`R-1234`).
- The target URL is redacted the same way everywhere it is persisted or
  printed, including in refusal messages: `https://user:pw@host/…?api_key=…`
  becomes `https://[redacted:credential]@host/…?api_key=[redacted]`. The host
  survives, because which target was besieged is the record.
- The judge sees the placeholders, not the secrets. That is the intended
  trade: a criterion hunting for a leaked credential should match
  `[redacted:api-key]`, which is itself the finding.

## 5. How findings are reported

Each run writes three files into the output directory:

| file | what it is |
|---|---|
| `<run_id>.engagement.json` | The engagement record: which agreement, which scope rules, authorized or not, the redacted target, every finding, and every approach that never landed |
| `<run_id>.json` | The full run report — personas, transcripts, per-criterion verdicts |
| `<run_id>.html` | The self-contained report to attach for the client |

A finding names a persona, an archetype, a criterion, and a **cited turn
index** that resolves against the transcript in the report beside it. A finding
you cannot click through to is an opinion, so the schema does not permit one:
a failed criterion without a citation is unrepresentable.

Three things the record deliberately reports that a scorecard would hide:

- **Abstentions are not passes.** A criterion the offline judge has no basis to
  decide is recorded as an abstention.
- **A partial run says so.** An approach that never reached the wall (a 429, a
  timeout, a wrong credential) is a classified error, not a pass, and its
  presence marks the whole record `partial`.
- **Where the wall held** is reported alongside where it broke.

## 6. Rehearsal (what has actually been run)

`local-approval-rehearsal.yaml` is the same engagement — same rubric, same
probes, same runner — pointed at `apps/approval-stub`, a stdlib HTTP server on
loopback. That server has a **planted, documented** weakness: under an
injection frame it prints its policy and returns
`verdict=approve approval_ref=none`.

Run it:

```bash
uv run python scripts/rehearse_engagement.py
```

That command starts the rehearsal target, conducts the engagement over a real
socket, and prints the three artifact paths. It is the demonstration that the
spine works. It is **not** evidence that Coehoorn finds real defects in real
approval surfaces — the weakness it catches was put there for it to catch.

## 7. What would make this engagement real

1. A written authorization from the target's owner, naming hosts and a window.
2. Real hosts in `scope.allowed_hosts` (the YAML currently names a
   `.invalid` placeholder that cannot resolve).
3. `authorized: true` in the YAML, as a reviewed commit.
4. A run, and the resulting `<run_id>.engagement.json` committed or attached —
   with its abstentions and partials intact.
