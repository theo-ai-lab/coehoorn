"""Scope is the control, and it fails closed.

A runner that dials an operator-supplied URL is SSRF surface. The premise of
this tool is that it is aimed at systems under a written engagement agreement,
so the control that matches the premise is an *allowlist declared in the
engagement* and enforced before any socket is opened — not a denylist of
"bad" ranges, which fails open on everything nobody thought of.

These tests pin the refusals. Every one of them asserts *which rule* refused,
because "it errored" is not a security property: an operator who is told
`scope.allowed_hosts` knows to amend the agreement, and an operator who is told
`scope.allow_private_addresses` knows they just pointed a siege at their own
metadata service.
"""
from __future__ import annotations

import ipaddress
import random

import pytest

from coehoorn.engagement import (
    EngagementRefused,
    EngagementScope,
    RefusalRule,
    _is_reserved,
    load_engagement,
)

_PUBLIC = (ipaddress.ip_address("93.184.216.34"),)


def _resolver(mapping: dict[str, tuple[str, ...]]):
    """A fake DNS. Injected so no test in this file touches a real resolver."""

    def resolve(host: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        try:
            return (ipaddress.ip_address(host),)
        except ValueError:
            pass
        if host not in mapping:
            raise OSError(f"name does not resolve: {host}")
        return tuple(ipaddress.ip_address(a) for a in mapping[host])

    return resolve


_RESOLVE = _resolver({"agent.example": ("93.184.216.34",)})


def _scope(**overrides) -> EngagementScope:
    fields: dict = {
        "allowed_schemes": ("https",),
        "allowed_hosts": ("agent.example",),
        "allowed_ports": (),
        "allowed_path_prefixes": (),
        "allow_private_addresses": False,
    }
    fields.update(overrides)
    return EngagementScope(**fields)


# --------------------------------------------------------------------------
# the allowlist itself
# --------------------------------------------------------------------------

def test_an_allowlisted_public_target_is_in_scope():
    url = "https://agent.example/chat"
    assert _scope().check(url, resolver=_RESOLVE) == url


def test_a_host_outside_the_allowlist_is_refused_by_name():
    with pytest.raises(EngagementRefused) as exc:
        _scope().check("https://evil.example/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.HOST


def test_userinfo_cannot_smuggle_an_allowlisted_host():
    # `https://agent.example@evil.example/` reads as allowlisted to a human
    # skimming it; the authority is `evil.example`.
    with pytest.raises(EngagementRefused) as exc:
        _scope().check("https://agent.example@evil.example/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.HOST


def test_the_allowlist_has_no_wildcards():
    # A subdomain is a different host. If an engagement covers it, it is named.
    with pytest.raises(EngagementRefused) as exc:
        _scope().check("https://sub.agent.example/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.HOST


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://agent.example/x", "ftp://agent.example/"])
def test_a_scheme_outside_the_allowlist_is_refused(url):
    with pytest.raises(EngagementRefused) as exc:
        _scope().check(url, resolver=_RESOLVE)
    assert exc.value.rule in {RefusalRule.SCHEME, RefusalRule.URL}


def test_a_port_outside_the_declared_ports_is_refused():
    scope = _scope(allowed_ports=(443,))
    assert scope.check("https://agent.example/chat", resolver=_RESOLVE)
    with pytest.raises(EngagementRefused) as exc:
        scope.check("https://agent.example:8443/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.PORT


def test_a_path_outside_the_declared_prefixes_is_refused():
    scope = _scope(allowed_path_prefixes=("/chat",))
    assert scope.check("https://agent.example/chat/v2", resolver=_RESOLVE)
    with pytest.raises(EngagementRefused) as exc:
        scope.check("https://agent.example/admin/reset", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.PATH


@pytest.mark.parametrize("url", ["not a url", "agent.example/chat", "https:///chat", ""])
def test_a_malformed_target_is_refused_not_guessed_at(url):
    with pytest.raises(EngagementRefused) as exc:
        _scope().check(url, resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.URL


# --------------------------------------------------------------------------
# parse differentials: check one representation, dial another
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/chat/../../admin",   # escapes the root, then re-enters
        "/chat/../admin",      # one level: routes to /admin
        "/chat/%2e%2e/admin",  # the same, percent-encoded
        "/chat/./../admin",
    ],
    ids=["double", "single", "encoded", "mixed"],
)
def test_dot_segments_cannot_walk_out_of_the_declared_path(path):
    # `startswith("/chat")` is true of every one of these, and every server
    # routes them to /admin. The prefix clause has to be decided on the path
    # the target will actually see.
    scope = _scope(allowed_path_prefixes=("/chat",))
    with pytest.raises(EngagementRefused) as exc:
        scope.check(f"https://agent.example{path}", resolver=_RESOLVE)
    assert exc.value.rule in {RefusalRule.PATH, RefusalRule.URL}


@pytest.mark.parametrize("ctrl", ["\n", "\r", "\t", "\x00"])
def test_a_control_character_in_the_target_is_refused_not_silently_stripped(ctrl):
    # urlsplit() strips ASCII control characters before parsing, so a header
    # smuggled into the URL is invisible to every clause below — while the raw
    # string is what would go on the wire. Refuse rather than sanitize: an
    # operator whose target was quietly rewritten cannot tell what was dialled.
    url = f"https://agent.example/chat{ctrl}Host: evil.example"
    with pytest.raises(EngagementRefused) as exc:
        _scope(allowed_path_prefixes=("/chat",)).check(url, resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.URL


def test_what_is_returned_is_what_was_checked():
    # The value this returns is the value the transport dials. If it is not
    # byte-identical to the representation every clause was decided on, the
    # check is advisory.
    from urllib.parse import urlsplit

    scope = _scope(allowed_path_prefixes=("/chat",))
    accepted = scope.check("https://agent.example/chat/v2/./", resolver=_RESOLVE)
    parts = urlsplit(accepted)
    assert ".." not in parts.path and "/./" not in parts.path
    assert parts.path.startswith("/chat")
    # A URL with nothing to normalise comes back untouched.
    plain = "https://agent.example/chat?q=1#frag"
    assert scope.check(plain, resolver=_RESOLVE) == plain


# --------------------------------------------------------------------------
# the address check — the part an allowlist alone does not give you
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",   # cloud instance metadata
        "127.0.0.1",         # loopback
        "10.1.2.3",          # RFC1918
        "192.168.0.10",
        "172.16.5.5",
        "0.0.0.0",           # unspecified
        "[::1]",             # loopback, v6
        "[fd00::1]",         # unique-local, v6
        "[::ffff:169.254.169.254]",  # v4-mapped metadata, the classic bypass
    ],
)
def test_a_reserved_address_is_refused_even_when_the_operator_allowlisted_it(host):
    # Defence in depth on purpose: an operator who pastes the metadata IP into
    # `allowed_hosts` — by typo, or because an attacker suggested it — still
    # gets refused. Reaching a reserved range takes an explicit, written opt-in.
    bare = host.strip("[]")
    scope = _scope(allowed_schemes=("http", "https"), allowed_hosts=(bare,))
    with pytest.raises(EngagementRefused) as exc:
        scope.check(f"http://{host}/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.ADDRESS


def test_a_localhost_engagement_opts_in_explicitly():
    scope = _scope(
        allowed_schemes=("http",),
        allowed_hosts=("127.0.0.1",),
        allow_private_addresses=True,
    )
    url = "http://127.0.0.1:8422/decide"
    assert scope.check(url, resolver=_RESOLVE) == url


def test_a_name_that_resolves_into_a_private_range_is_refused():
    # The allowlist is satisfied and the URL looks public. DNS is where the
    # rebind lives, so the address check runs on what the name resolves to.
    resolve = _resolver({"agent.example": ("10.0.0.7",)})
    with pytest.raises(EngagementRefused) as exc:
        _scope().check("https://agent.example/chat", resolver=resolve)
    assert exc.value.rule is RefusalRule.ADDRESS


def test_one_private_answer_among_public_ones_still_refuses():
    # A split answer is the interesting case: refuse if ANY address is
    # reserved, because we do not choose which one httpx connects to.
    resolve = _resolver({"agent.example": ("93.184.216.34", "127.0.0.1")})
    with pytest.raises(EngagementRefused) as exc:
        _scope().check("https://agent.example/chat", resolver=resolve)
    assert exc.value.rule is RefusalRule.ADDRESS


def test_a_dns_failure_is_a_refusal_not_a_shrug():
    def resolve(host: str):
        raise OSError("temporary failure in name resolution")

    with pytest.raises(EngagementRefused) as exc:
        _scope().check("https://agent.example/chat", resolver=resolve)
    assert exc.value.rule is RefusalRule.RESOLUTION


# --------------------------------------------------------------------------
# the refusal itself must be safe to print
# --------------------------------------------------------------------------

def test_the_refusal_does_not_quote_the_credential_it_refused():
    # The refused URL goes into logs, CI output and an operator's terminal.
    # It is exactly the leak class the redaction boundary exists for, so it
    # goes through the same boundary every artifact uses.
    url = "https://siege:hunter2@evil.example/chat?api_key=abc123secret"
    with pytest.raises(EngagementRefused) as exc:
        _scope().check(url, resolver=_RESOLVE)
    rendered = str(exc.value) + exc.value.target
    assert "hunter2" not in rendered
    assert "abc123secret" not in rendered
    # ...but the host survives: which target was refused is the whole record.
    assert "evil.example" in rendered


# --------------------------------------------------------------------------
# authorization — a scope you have not been given is not a scope
# --------------------------------------------------------------------------

def test_an_unauthorized_engagement_is_refused_before_any_dial(tmp_path):
    eng = load_engagement(_write_engagement(tmp_path, authorized=False))
    with pytest.raises(EngagementRefused) as exc:
        eng.check_target("https://agent.example/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.AUTHORIZED


def test_an_authorized_engagement_still_has_to_be_in_scope(tmp_path):
    eng = load_engagement(_write_engagement(tmp_path, authorized=True))
    assert eng.check_target("https://agent.example/chat", resolver=_RESOLVE)
    with pytest.raises(EngagementRefused) as exc:
        eng.check_target("https://elsewhere.example/chat", resolver=_RESOLVE)
    assert exc.value.rule is RefusalRule.HOST


def _write_engagement(tmp_path, *, authorized: bool):
    rubric = tmp_path / "r.yaml"
    rubric.write_text("criteria:\n  - id: c1\n    description: d\n")
    path = tmp_path / "eng.yaml"
    path.write_text(
        f"id: t-eng\n"
        f"authorized: {'true' if authorized else 'false'}\n"
        f"rules_of_engagement: ./roe.md\n"
        f"rubric: ./r.yaml\n"
        f"target:\n"
        f"  name: T\n"
        f"  description: d\n"
        f"scope:\n"
        f"  allowed_schemes: [https]\n"
        f"  allowed_hosts: [agent.example]\n"
    )
    return path


# --------------------------------------------------------------------------
# the space, not a handful of examples
# --------------------------------------------------------------------------

_SCHEMES = ["https", "http", "file", "gopher", "ftp", "HTTPS"]
_HOSTS = [
    "agent.example", "AGENT.EXAMPLE", "sub.agent.example", "evil.example",
    "127.0.0.1", "169.254.169.254", "10.0.0.1", "93.184.216.34",
    "[::1]", "[::ffff:127.0.0.1]", "resolves-private.example", "nxdomain.example",
]
_PORTS = ["", ":443", ":8443", ":80"]
_PATHS = ["/chat", "/chat/v2", "/admin", "/"]
_USERINFO = ["", "siege:hunter2@"]

_SPACE_RESOLVE = _resolver({
    "agent.example": ("93.184.216.34",),
    "sub.agent.example": ("93.184.216.34",),
    "evil.example": ("198.51.100.9",),
    "resolves-private.example": ("10.0.0.7",),
})


@pytest.mark.parametrize("seed", range(12))
def test_every_target_is_either_in_scope_or_names_the_rule_that_refused(seed):
    """The invariant, over the generated space: there is no third outcome.

    The dependency budget has no room for a generative-testing library, so the
    generator is a seeded deterministic loop — same shape, reproducible from the
    seed printed in any failure.
    """
    rng = random.Random(seed)
    scope = _scope(
        allowed_schemes=("https",),
        allowed_hosts=("agent.example", "169.254.169.254", "127.0.0.1"),
        allowed_ports=(443, 8443),
        allowed_path_prefixes=("/chat",),
        allow_private_addresses=False,
    )
    for _ in range(60):
        url = (
            f"{rng.choice(_SCHEMES)}://{rng.choice(_USERINFO)}"
            f"{rng.choice(_HOSTS)}{rng.choice(_PORTS)}{rng.choice(_PATHS)}"
        )
        try:
            accepted = scope.check(url, resolver=_SPACE_RESOLVE)
        except EngagementRefused as refused:
            assert isinstance(refused.rule, RefusalRule), url
            assert refused.detail, url
            assert "hunter2" not in str(refused), url
            continue
        # Accepted => every clause of the agreement actually holds.
        from urllib.parse import urlsplit
        parts = urlsplit(accepted)
        assert parts.scheme == "https", url
        host = (parts.hostname or "").lower()
        assert host in {"agent.example", "169.254.169.254", "127.0.0.1"}, url
        assert (parts.port or 443) in {443, 8443}, url
        assert parts.path.startswith("/chat"), url
        for addr in _SPACE_RESOLVE(host):
            # Call the predicate rather than re-stating it. The re-stated
            # version agreed with the implementation by construction, so it
            # could not fail for a range the implementation had forgotten —
            # and it did not, for fec0::/10 and 100.64.0.0/10. What each
            # address class is classified AS is proven by the named table in
            # tests/test_reserved_addresses.py; this only asserts the scope
            # honours that classification.
            assert not _is_reserved(addr), (
                f"{url} accepted with reserved address {addr}"
            )
