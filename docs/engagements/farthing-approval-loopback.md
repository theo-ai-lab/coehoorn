# Engagement — Farthing approval inbox (self-owned, loopback instance)

**Status: AUTHORIZED, EXECUTED 2026-08-02.**
Findings report: [`2026-08-02-farthing-loopback-findings.md`](./2026-08-02-farthing-loopback-findings.md).

This document is the rules-of-engagement half of a Coehoorn engagement. Its
machine-readable half is [`farthing-approval-loopback.yaml`](./farthing-approval-loopback.yaml),
which the runner enforces. The two are deliberately paired so this page cannot
promise a boundary the code does not keep.

Read the scope of the claim narrowly, because that is the honest scope:

- This engagement sieges **Farthing's real approval surface**
  (`src/farthing/approval/app.py`) run **unmodified** under `uvicorn` as a
  **separate OS process** bound to `127.0.0.1:8477`. Not an in-process stub, not
  a mock — a different pid, a real socket, real HTTP.
- The target's owner is the **same person who owns this repository**. That is
  why an authorization is on file. A siege of your own service is a real
  engagement, but it is **not evidence about a stranger's service**, and the
  findings report says so in its first paragraph.
- This is **not** the third-party engagement. That one stays defined and
  deliberately unauthorized in [`farthing-approval-surface.yaml`](./farthing-approval-surface.yaml),
  whose host is an RFC 2606 `.invalid` placeholder.

What is demonstrated for the first time here: the spine that was previously only
proven against this repo's own deliberately-weakened stub
(`apps/approval-stub`) is now proven against a **real, independently-authored,
security-hardened FastAPI service** — over a real socket, with the scope gate,
the offline judge, the redaction boundary and the findings discipline all live.

---

## 1. Target

| field | value |
|---|---|
| Name | Farthing approval inbox (self-owned, loopback instance) |
| What it does | Decides whether an AI-proposed billing refund proceeds, and issues the HMAC-signed token that authorizes it |
| Why this surface | It is the money-moving boundary. Everything upstream is a proposal; this is where a proposal becomes a payment |
| How it was run | `uvicorn farthing.approval.app:app --host 127.0.0.1 --port 8477`, unmodified, in the farthing venv (fastapi 0.139.0) |
| Backend | **none** — no Temporal, no Postgres, no Stripe. Only the pre-decision gate (authentication, CSRF, routing, headers) is reachable; the decision path itself needs a backend this instance does not have |
| Wire contract | `POST {conversation: [{role, content}, ...]} -> {reply: str}` |
| Endpoint | supplied at run time via `--target` — never committed |

Because there is no Temporal backend, a request that clears authentication
reaches a decision path that cannot complete and returns a clean `500` (no
traceback in the body). The security-relevant surface that **is** fully
reachable and fully tested here is the gate in front of the money: does an
unauthenticated or cross-site caller get anywhere.

## 2. Authorization

`authorized: true` in the YAML, because the target is self-owned and the siege
is of an instance bound to loopback under the operator's own control. The
authorization gate is exercised in both directions in the run: the paired
third-party engagement (`authorized: false`), pointed at the very same live
URL, is refused by rule `engagement.authorized` before any socket opens.

## 3. Scope

The authoritative list lives in the YAML under `scope:`; this section says what
it *means*.

**In scope**

- `http://127.0.0.1:8477/inbox…` — the approval inbox and its `approve`/`deny`
  routes, over `http` (loopback, no TLS terminator in front of this instance).
- Adversarial *conversation*: contradiction, ambiguity, emotional pressure,
  off-topic drift, prompt injection, and requests just over the auto-approval
  ceiling. The exact scripts are committed under `probes:`.
- Read-only HTTP reconnaissance of the same host/port (method matrix, default
  informational routes, redirect behaviour) — recorded in the findings report.

**Out of scope**

- Any host but `127.0.0.1`; any port but `8477`; any scheme but `http`; any
  path outside `/inbox`. Each of these was demonstrated to be refused **by the
  scope gate, before any dial** (see the findings report's scope-control
  section).
- The private-address opt-in: `127.0.0.1` is reachable **only** because the
  engagement sets `allow_private_addresses: true`. With that line removed, the
  same target is refused by rule `scope.allow_private_addresses`, exactly as a
  cloud metadata address would be.
- Load, denial of service, throughput. A handful of short conversations at
  bounded concurrency.
- The surrounding infrastructure (Temporal, Postgres, Stripe, the auth proxy).
  This engagement tests the decision gate the app exposes over HTTP.
- Real customer data. Probes reference synthetic case ids only.

## 4. Handling of data

As `farthing-approval-surface.md` §4: transcripts are redacted at one boundary
before they are judged or written; the target URL is redacted the same way
everywhere it is printed, including refusal messages (note how the case
reference `R-1001` in a refused path prints as `[redacted:case-ref]`).

## 5. How findings are reported

The findings report ([`2026-08-02-farthing-loopback-findings.md`](./2026-08-02-farthing-loopback-findings.md))
states, per candidate, a TRUE/FALSE-POSITIVE verdict with the request and
response that decided it. It under-claims by construction: it names what was
**not** demonstrated (no live model, no remote target, no backend) before it
names what was.

## 6. What would make the *third-party* engagement real

Unchanged from `farthing-approval-surface.md` §7: a written authorization from a
target owner who is not us, real hosts in the allowlist, `authorized: true` as a
reviewed commit, and a committed run. This loopback engagement does not claim to
be that. It closes a different gap: whether the harness holds up against a real,
hardened service at all, rather than only against a stub written to fail.
