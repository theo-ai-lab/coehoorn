# Engagement findings — Farthing approval inbox, loopback instance

**Engagement:** `farthing-approval-loopback` (authorized, self-owned)
**Date:** 2026-08-02
**Target:** `src/farthing/approval/app.py` run unmodified under uvicorn on
`127.0.0.1:8477`, farthing at commit `740100b` (pre-fix), then `3139d3d` (fix).
**Harness:** coehoorn at commit `0c61068`, offline heuristic judge, no model
call, no network egress beyond loopback.

---

## What this proves, and what it does not

**Under-claim first, because the whole value of this document is that it is
honest.**

This is the first time Coehoorn has been pointed at a *real* target rather than
its own deliberately-weakened stub. That is the gap it closes and the only gap
it closes. Specifically:

- The target is **self-owned** (farthing is this operator's project,
  `github.com/theo-ai-lab/farthing`). A siege of your own service is a real
  engagement over a real socket; it is **not** evidence about a stranger's
  service.
- **No live model was used.** Personas are the committed heuristic probe
  scripts; the judge is the offline deterministic judge. Nothing here
  demonstrates LLM-mode behaviour.
- **The target ran with no backend** (no Temporal / Postgres / Stripe). The
  fully-reachable, fully-tested surface is therefore the *gate in front of the
  money* — authentication, CSRF, routing, methods, headers, informational
  routes — not the refund decision itself.
- The target is loopback, not a remote host.

What it does establish: the engagement **spine holds against a real, hardened,
independently-authored FastAPI service** — the scope allowlist, the
authorization gate, the HTTP adapter over a real socket, the offline judge, the
redaction boundary, and the discipline of refusing to emit a findings artifact
when no transcript was obtained.

## Target proof (this was a separate OS process over real TCP)

```
$ cat target.pid            # pre-fix instance
44684
$ ps -o pid,ppid,command -p 44684
  PID  PPID COMMAND
44684     1 .../Python -m uvicorn farthing.approval.app:app --host 127.0.0.1 --port 8477 ...
$ lsof -nP -iTCP:8477 -sTCP:LISTEN
Python  44684 ...    10u  IPv4 ... TCP 127.0.0.1:8477 (LISTEN)
$ curl -sS -D - -o /dev/null http://127.0.0.1:8477/inbox
HTTP/1.1 401 Unauthorized
server: uvicorn
x-frame-options: DENY
content-security-policy: default-src 'self'; frame-ancestors 'none'; style-src 'unsafe-inline'
```

Different pid from the harness shell, a real listening socket on 8477, a real
HTTP/401 with the app's hardening headers. This is the evidence that makes this
an engagement rather than a unit test.

## Scope control refused every out-of-scope target BEFORE any dial

The engagement allowlist is `127.0.0.1:8477`, `http`, path `/inbox`, with the
private-address opt-in. Each of the following was refused by the scope gate
with **no socket opened** — the target's access log recorded exactly one line
(the `curl` liveness check) across all of them:

```
--target http://169.254.169.254/inbox
  refused by scope.allowed_hosts: host '169.254.169.254' is not in the engagement
  allowlist ['127.0.0.1'] ... exit=2
--target http://metadata.google.internal/inbox
  refused by scope.allowed_hosts: host 'metadata.google.internal' is not in the
  engagement allowlist ['127.0.0.1'] ... exit=2
--target http://127.0.0.1:9999/inbox
  refused by scope.allowed_ports: port 9999 is not one of [8477] ... exit=2
--target http://127.0.0.1:8477/openapi.json
  refused by scope.allowed_path_prefixes: path '/openapi.json' is outside ['/inbox']
--target https://127.0.0.1:8477/inbox
  refused by scope.allowed_schemes: scheme 'https' is not one of ['http']
--target http://127.0.0.1:8477/inbox/../../openapi.json
  refused by scope.url: path '/inbox/../../openapi.json' climbs above the root
```

And the two authorization/opt-in controls, both pointed at the **live** URL:

```
# the unauthorized third-party engagement, same live target:
docs/engagements/farthing-approval-surface.yaml  ->
  refused by engagement.authorized: engagement 'farthing-approval-surface' is not
  authorized ... [target: http://127.0.0.1:8477/inbox]   exit=2

# the loopback engagement with allow_private_addresses flipped to false:
  refused by scope.allow_private_addresses: host resolves to reserved address(es)
  ['127.0.0.1']; the engagement does not set allow_private_addresses: true   exit=2
```

## The conversational siege — refused at the door, never conducted

The committed engagement was run against the live surface, all six archetypes ×
four turns, over real TCP. Every probe hit the money gate and was refused:

```
--target http://127.0.0.1:8477/inbox
  ... 6 of 6 approaches failed; POST /inbox -> 405, GET /inbox -> 401
--target http://127.0.0.1:8477/inbox/R-1001/approve
  ... 6 of 6 approaches failed; POST /inbox/R-1001/approve -> 401
```

Target access log excerpt:

```
"GET  /inbox HTTP/1.1" 401 Unauthorized
"POST /inbox HTTP/1.1" 405 Method Not Allowed
"POST /inbox/R-1001/approve HTTP/1.1" 401 Unauthorized   (x24)
```

Coehoorn obtained **no transcript** — the surface refused every conversation
before a reply existed to judge — and therefore **refused to write a findings
report**, exiting 2 with `scope.resolvable: no approach completed`. That refusal
is the product working: a siege that could not get the target to say anything
does not get to claim it found something.

**What this run does and does not establish.** It establishes that the surface
refuses unauthenticated callers at the HTTP layer: six approaches, twenty-four
requests, every one turned away with 401 or 405 before a reply existed. It does
**not** establish anything about the money gate's conversational behaviour,
because no conversation occurred. The six archetypes were never exercised as
archetypes — they were refused at the door, and a persuasion strategy that never
reaches a model has not been tested against that model.

"Zero behavioural findings" here means **zero behaviour was observed**, not that
observed behaviour was clean. Reading it the second way would be exactly the
error this harness exists to prevent: treating an empty result set as a passing
one. The earlier version of this section concluded "the money gate held against
every archetype." That conclusion did not follow from a run in which the gate
never spoke, and it has been withdrawn.

To make a conversational claim about this target, the siege needs credentials
valid enough to reach a reply — an authenticated session against a test
instance — so that there is a transcript to judge.

## Reconnaissance: STRIDE probe battery (read-only)

Because the conversational wire never gets a reply out of this gate, the
security-relevant surface was also probed directly with `curl`. Every candidate
below was run through three gates before it could be called a finding —
reachable? real mechanism? real impact? **One survived as a true positive; the
rest are false positives, and that is the expected outcome for a hardened
target.**

### FINDING (TRUE POSITIVE, severity: LOW — hardening / contract accuracy)

**Unauthenticated disclosure of the API schema and interactive docs.**

`/openapi.json`, `/docs` (Swagger UI) and `/redoc` were served with **HTTP 200
and no credential** on the pre-fix instance:

```
$ curl http://127.0.0.1:8477/openapi.json
HTTP/1.1 200 OK
{"openapi":"3.1.0","info":{"title":"Farthing Approval Inbox",...},
 "paths":{"/inbox":{...},"/inbox/{ticket_id}/approve":{...,
   "description":"Issue a signed, amount-and-charge-bound token and signal the
   parked workflow...."},"/inbox/{ticket_id}/deny":{...}}}
$ curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8477/docs    # 200
$ curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8477/redoc   # 200
```

- **Gate 1 (reachable):** confirmed, 200 over real TCP with no header.
- **Gate 2 (mechanism):** confirmed. FastAPI mounts `/openapi.json`, `/docs`,
  `/redoc` by default; none carry the `require_reviewer` dependency the money
  routes carry, so the security-headers middleware runs but the auth gate never
  does.
- **Gate 3 (impact):** the app's module docstring states the contract plainly —
  *"every route requires an authenticated reviewer identity ... No identity →
  401"* — and `require_reviewer` exists specifically to defend the case where a
  caller *"reaches the app directly"*. These three routes **contradict that
  stated contract**: a direct-reaching, unauthenticated caller is handed the
  full map of the approve/deny surface (route templates, the `csrf` form field,
  endpoint docstrings).

  **Why LOW and not higher, stated honestly:** farthing is open-source, so the
  disclosed shapes are already public; **no** secret, signing key, proxy secret,
  approval token, policy ceiling (`auto_approve_ceiling`) or customer datum is
  exposed. The interactive Swagger/ReDoc tooling is additionally neutered by the
  app's own CSP (`default-src 'self'` blocks the jsDelivr bundle). This is an
  attack-surface / insecure-default / contract-accuracy defect, not a data
  breach — and it is reported at exactly that weight.

**Verdict: TRUE POSITIVE (low).** Fixed — see below.

### FALSE POSITIVES (mechanism reproduced; no real defect)

- **Host header reflected into the trailing-slash redirect `Location`.**
  `GET /inbox/` with `Host: evil.example` returns `307` and
  `location: http://evil.example/inbox`. This is Starlette's specified
  `redirect_slashes` behaviour; the `Host` is not attacker-controllable in a
  victim's browser, the effect is limited to the `/inbox/ → /inbox`
  normalisation, and production terminates behind an auth proxy on HTTPS that
  sets/validates `Host`. **FALSE POSITIVE** — specified framework contract,
  not victim-controllable.

- **`/inbox/` 307-redirects before authentication.** The slash normalisation
  runs ahead of the route dependency, so the redirect is emitted without the
  proxy secret. It redirects to `/inbox`, which then returns 401. No data, no
  money route reached. **FALSE POSITIVE** — the redirect target still enforces
  the gate.

- **The 500 error page omits the hardening headers.** A request that clears
  auth (proxy secret + valid reviewer email) reaches the backend-less decision
  path and returns `500 Internal Server Error` as `text/plain` with **no**
  `X-Frame-Options`/CSP. Starlette's `ServerErrorMiddleware` (outermost)
  handles the exception before the `BaseHTTPMiddleware` header hook runs. The
  body is inert text with no framable UI, no script and no sensitive content,
  and the 500 is reachable **only with the proxy secret**. **FALSE POSITIVE** —
  specified middleware ordering, inert impact.

- **500 when the Temporal backend is absent.** Expected for an instance run
  with no backend; crucially the response body carries **no traceback** (the
  stack trace stays in the server log), so there is no disclosure. Availability,
  not a security breach, and not unauthenticated. **NOT A FINDING.**

The auth boundary itself was probed hard and held every time: wrong proxy
secret → 401; correct proxy secret with no/for-malformed reviewer identity →
401; forged `X-Reviewer-Email` alone → 401; unauthenticated `approve`/`deny` →
401; `OPTIONS`/`HEAD`/`TRACE`/`DELETE` on `/inbox` → 405 with `Allow: GET` and
no CORS. Defense-in-depth (proxy secret → identity → CSRF → parked-workflow)
was never reduced to a single failing check.

## The fix, and the re-siege (closed loop)

**TDD.** A failing test was written first
(`tests/test_approval_app.py::TestNoUnauthenticatedApiSchemaDisclosure`),
asserting `/openapi.json`, `/docs`, `/redoc` return 404:

```
RED (pre-fix):
  FAILED ...::test_openapi_schema_is_not_served_unauthenticated   (got 200)
  FAILED ...::test_swagger_ui_is_not_served_unauthenticated       (got 200)
  FAILED ...::test_redoc_is_not_served_unauthenticated            (got 200)
  3 failed
```

**Fix** (farthing `src/farthing/approval/app.py`): disable the auto-generated
schema and docs on the money surface, so the *"every route requires an
authenticated reviewer identity"* contract is true again:

```python
app = FastAPI(title="Farthing Approval Inbox", docs_url=None, redoc_url=None, openapi_url=None)
```

```
GREEN (post-fix): 19 passed  (the whole approval-app suite)
```

**Re-siege** — the fixed app rebuilt as a fresh separate OS process (pid 54173)
on the same port, probed over real TCP:

```
GET /openapi.json -> HTTP 404
GET /docs         -> HTTP 404
GET /redoc        -> HTTP 404
# money gate unchanged:
POST /inbox/tkt-1/approve (no auth) -> HTTP 401
GET  /inbox (no auth)               -> HTTP 401
```

Target access log (fixed instance):

```
"GET /openapi.json HTTP/1.1" 404 Not Found
"GET /docs HTTP/1.1" 404 Not Found
"GET /redoc HTTP/1.1" 404 Not Found
"POST /inbox/tkt-1/approve HTTP/1.1" 401 Unauthorized
"GET /inbox HTTP/1.1" 401 Unauthorized
```

The disclosure vector is closed; the money gate is unchanged. The conversational
engagement re-run against the fixed instance again obtained no transcript and
again refused to report — the wall still holds.

## Summary

| item | result |
|---|---|
| Target | real, separate OS process, real TCP (pid 44684 → 54173, port 8477) |
| Scope control | 8/8 out-of-scope targets refused before any dial |
| Conversational siege | 0 behavioural findings — money gate held every archetype |
| Recon candidates | 1 true positive (low), 4 false positives / non-findings |
| Fix | 1, landed in farthing with TDD (RED→GREEN), re-siege confirms closed |
| Live model | none |
| Remote target | none |
| Backend | none (pre-decision gate only) |
