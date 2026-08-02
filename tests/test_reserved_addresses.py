"""Which addresses need a written opt-in, named one by one.

This table exists because the invariant assertion in ``test_engagement_scope.py``
re-states the *same predicate* the implementation uses. A test written that way
agrees with the code by construction: it cannot fail for an address class the
implementation forgot, because it forgot it too. That is how ``fec0::/10`` and
``100.64.0.0/10`` sat accepted under a scope whose written rules of engagement
say a reserved address is refused "even if such an address is in
``allowed_hosts``".

So every address here is written out literally, with the reason it belongs on
its side of the line. A future term added to the predicate cannot silently
change what this file asserts.
"""

from __future__ import annotations

import ipaddress

import pytest

from coehoorn.engagement import EngagementRefused, EngagementScope, RefusalRule, _is_reserved

#: Reachable only with ``allow_private_addresses: true`` in the engagement.
NEEDS_OPT_IN = [
    ("127.0.0.1", "IPv4 loopback"),
    ("::1", "IPv6 loopback"),
    ("10.0.0.1", "RFC 1918 private"),
    ("192.168.1.1", "RFC 1918 private"),
    ("172.16.0.1", "RFC 1918 private"),
    ("169.254.169.254", "link-local: the cloud metadata service, the #1 SSRF target"),
    ("fe80::1", "IPv6 link-local"),
    ("fd00::1", "IPv6 unique-local"),
    ("fdff::1", "IPv6 unique-local, top of the range"),
    ("fec0::1", "IPv6 site-local (RFC 3879, deprecated but still routed internally)"),
    ("fec0:0:0:ffff::1", "legacy well-known site-local DNS resolver address"),
    ("100.64.0.1", "RFC 6598 carrier-grade NAT shared space"),
    ("100.127.255.254", "RFC 6598, top of the range"),
    ("0.0.0.0", "unspecified"),
    ("224.0.0.1", "multicast"),
    ("240.0.0.1", "IPv4 reserved"),
    ("::ffff:169.254.169.254", "metadata service wearing an IPv6 hat"),
    ("192.0.2.1", "TEST-NET-1, documentation space"),
    ("198.18.0.1", "benchmarking space"),
]

#: Globally routable. An engagement may name these without any opt-in.
NEEDS_NO_OPT_IN = [
    ("93.184.216.34", "public IPv4"),
    ("8.8.8.8", "public IPv4"),
    ("1.1.1.1", "public IPv4"),
    ("2606:2800:220:1::1", "public IPv6"),
]


@pytest.mark.parametrize("address,why", NEEDS_OPT_IN, ids=[a for a, _ in NEEDS_OPT_IN])
def test_address_needs_a_written_opt_in(address: str, why: str) -> None:
    assert _is_reserved(ipaddress.ip_address(address)), (
        f"{address} ({why}) must not be reachable without allow_private_addresses"
    )


@pytest.mark.parametrize("address,why", NEEDS_NO_OPT_IN, ids=[a for a, _ in NEEDS_NO_OPT_IN])
def test_public_address_is_reachable_without_opt_in(address: str, why: str) -> None:
    assert not _is_reserved(ipaddress.ip_address(address)), (
        f"{address} ({why}) is globally routable; refusing it would break real engagements"
    )


@pytest.mark.parametrize("address,why", NEEDS_OPT_IN, ids=[a for a, _ in NEEDS_OPT_IN])
def test_scope_refuses_the_address_even_when_the_operator_allowlisted_it(
    address: str, why: str
) -> None:
    """The clause the rules of engagement state absolutely.

    No DNS control is needed for this route: ``system_resolver`` short-circuits
    an IP literal, so a hand-written engagement file naming the address reaches
    the address check directly.
    """
    host = f"[{address}]" if ":" in address else address
    scope = EngagementScope(allowed_hosts=[address], allowed_schemes=["https"])
    with pytest.raises(EngagementRefused) as caught:
        scope.check_pinned(f"https://{host}/chat")
    assert caught.value.rule is RefusalRule.ADDRESS, why
