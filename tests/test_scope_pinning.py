"""The transport must dial the address the scope approved, not a fresh DNS answer.

``EngagementScope.check`` resolves the target host and refuses if *any* answer is
a reserved address. Then it hands the transport a URL still containing the
HOSTNAME, so httpx resolves a second time at connect time. A host whose record
changes between those two moments — a DNS rebind, the classic SSRF bypass — is
approved on one address and dialled on another.

``check``'s own docstring already names this failure one layer up:

    Checking one representation and handing the transport another is how a
    scope becomes advisory.

That is exactly what a hostname is here: a second representation, re-resolved by
someone else. The fix is to carry the checked ADDRESSES forward and dial those.

No network and no DNS in these tests: the resolver is injected, and the pinned
transport is exercised against a recording inner transport, so what is asserted
is the bytes that would go on the wire.
"""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from coehoorn.engagement import EngagementScope, pinned_transport


def _scope(**kw) -> EngagementScope:
    base = {
        "allowed_hosts": ["agent.example.com"],
        "allowed_schemes": ["https"],
    }
    base.update(kw)
    return EngagementScope(**base)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Stands in for the real network: records the request it was handed."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return httpx.Response(200, json={"reply": "ok"})


class TestCheckReturnsWhatItApproved:
    def test_check_pinned_hands_back_the_addresses_it_validated(self) -> None:
        approved = (ipaddress.ip_address("93.184.216.34"),)
        checked = _scope().check_pinned(
            "https://agent.example.com/chat", resolver=lambda h: approved
        )
        assert checked.url == "https://agent.example.com/chat"
        assert checked.addresses == approved


class TestPinnedTransportDialsTheApprovedAddress:
    @pytest.mark.asyncio
    async def test_request_goes_to_the_ip_literal_not_the_hostname(self) -> None:
        inner = RecordingTransport()
        transport = pinned_transport(ipaddress.ip_address("93.184.216.34"), inner=inner)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://agent.example.com/chat", json={})

        (sent,) = inner.seen
        # The dialled host is the approved address. A rebind cannot move it,
        # because no name is looked up at connect time.
        assert sent.url.host == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_host_header_still_names_the_agreed_target(self) -> None:
        inner = RecordingTransport()
        transport = pinned_transport(ipaddress.ip_address("93.184.216.34"), inner=inner)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://agent.example.com/chat", json={})

        (sent,) = inner.seen
        # Virtual hosts and TLS both need the real name; pinning the address
        # must not silently change which site is being addressed.
        assert sent.headers["host"] == "agent.example.com"
        assert sent.extensions.get("sni_hostname") == "agent.example.com"

    @pytest.mark.asyncio
    async def test_port_and_path_and_query_survive_pinning(self) -> None:
        inner = RecordingTransport()
        transport = pinned_transport(ipaddress.ip_address("93.184.216.34"), inner=inner)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://agent.example.com:8443/chat?turn=2", json={})

        (sent,) = inner.seen
        assert sent.url.port == 8443
        assert sent.url.path == "/chat"
        assert sent.url.query == b"turn=2"

    @pytest.mark.asyncio
    async def test_ipv6_address_is_bracketed_correctly(self) -> None:
        inner = RecordingTransport()
        transport = pinned_transport(ipaddress.ip_address("2606:2800:220:1::1"), inner=inner)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://agent.example.com/chat", json={})

        (sent,) = inner.seen
        assert sent.url.host == "2606:2800:220:1::1"
        assert sent.headers["host"] == "agent.example.com"


class TestAdapterCanBeGivenThePinnedTransport:
    """A capability nothing dials is decoration. The adapter has to take it."""

    @pytest.mark.asyncio
    async def test_adapter_sends_through_the_supplied_transport(self) -> None:
        from coehoorn.agent_adapter import HttpAgentAdapter

        inner = RecordingTransport()
        transport = pinned_transport(ipaddress.ip_address("127.0.0.1"), inner=inner)
        async with HttpAgentAdapter(
            "http://agent.example.com/chat", transport=transport
        ) as agent:
            reply = await agent([{"role": "user", "content": "hi"}])

        assert reply == "ok"
        (sent,) = inner.seen
        assert sent.url.host == "127.0.0.1"
        assert sent.headers["host"] == "agent.example.com"

    @pytest.mark.asyncio
    async def test_adapter_still_owns_and_closes_the_client_it_made(self) -> None:
        from coehoorn.agent_adapter import HttpAgentAdapter

        adapter = HttpAgentAdapter(
            "http://agent.example.com/chat",
            transport=pinned_transport(
                ipaddress.ip_address("127.0.0.1"), inner=RecordingTransport()
            ),
        )
        await adapter([{"role": "user", "content": "hi"}])
        assert adapter._client is not None
        await adapter.aclose()
        # A transport passed in must not turn the client into someone else's to
        # close; that would leak a connection pool per engagement.
        assert adapter._client is None


class TestRebindCannotMoveTheTarget:
    @pytest.mark.asyncio
    async def test_a_record_that_flips_to_metadata_after_the_check_is_not_dialled(
        self,
    ) -> None:
        """The whole point, end to end.

        Check time: the host resolves to a public address and passes scope.
        Connect time: the same name now resolves to the cloud metadata service.
        With the address pinned, the second answer is never consulted.
        """
        answers = iter(
            [
                (ipaddress.ip_address("93.184.216.34"),),  # check time: public
                (ipaddress.ip_address("169.254.169.254"),),  # connect time: rebound
            ]
        )
        checked = _scope().check_pinned(
            "https://agent.example.com/chat", resolver=lambda h: next(answers)
        )

        inner = RecordingTransport()
        transport = pinned_transport(checked.addresses[0], inner=inner)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post(checked.url, json={})

        (sent,) = inner.seen
        assert sent.url.host == "93.184.216.34"
        assert sent.url.host != "169.254.169.254"
