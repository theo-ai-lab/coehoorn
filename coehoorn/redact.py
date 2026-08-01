"""Redaction at the Transcript boundary — the one place it can be guaranteed.

A siege transcript is someone else's user data. It reaches five persistence
paths (``report.json``, the self-contained HTML, SARIF, JUnit, and the stdout
summary), and a redactor bolted onto any one of them is a redactor that the
next emitter forgets. So the policy is applied once, to the ``Transcript``
itself, *before* the transcript is judged or assembled into a ``Report``.
Everything downstream — including judge rationales, which quote the transcript —
is therefore derived from redacted text and cannot leak what was removed.

The ordering has one honest consequence worth stating: the judge sees the
placeholder, not the secret. That is the right trade (a criterion that hunts
for a leaked credential should match ``[redacted:api-key]``, which is *itself*
the finding that a credential was present), and it is why the placeholder names
what it replaced instead of blanking the span.

Three levels:

* ``off``      — no default pack at all. Local stubs, byte-repro fixtures, and
                 anyone who would rather have the raw record. Patterns a rubric
                 declares explicitly still apply: they are a stated engagement
                 requirement, not a default.
* ``standard`` — high-precision credentials and direct identifiers: email, API
                 keys and tokens, JWTs, private-key blocks, bearer credentials,
                 US SSNs, Luhn-valid card numbers.
* ``strict``   — adds the classes that carry real false-positive risk: phone
                 numbers, IPv4 addresses, long hex digests.

What is deliberately absent: a Shannon-entropy fallback. Entropy fires on
base64 and on JSON, which is most of a tool-calling transcript — it would eat
the evidence the report exists to cite. Every pattern here is a shape, and a
few are checksum-verified (Luhn), so a false positive is a bug with an address,
not a threshold to tune.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import yaml

from .schemas import ApproachError, ToolCall, Transcript

#: Query-string keys whose value is a credential wherever it appears.
_SECRET_QUERY_KEYS = frozenset(
    {"api_key", "apikey", "key", "token", "access_token", "auth", "secret", "signature", "sig"}
)

#: A URL with an authority, as it appears *inside* text. An httpx error message
#: is prose with a URL in it ("Client error '401 Unauthorized' for url '...'"),
#: and so is any transcript turn that quotes one. Only whitespace, quotes and
#: angle brackets terminate a span: brackets cannot, because ``[::1]`` is a
#: legal host and excluding ``]`` would let every IPv6 target keep its
#: credential. Sentence punctuation is trimmed afterwards instead.
_URL_IN_TEXT = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+")

_CLOSERS = {")": "(", "]": "[", "}": "{"}


def _trim_trailing_punctuation(span: str) -> tuple[str, str]:
    """Split a matched span into the URL and the sentence punctuation after it.

    ``.,;:!?`` never end a URL anyone meant to write. A closing bracket is
    ambiguous — it belongs to the URL when the URL opened it (``[::1]``,
    ``?ids[]=1``) and to the prose when it did not (``(see http://x)``) — so it
    is decided by counting, not by guessing.
    """
    end = len(span)
    while end:
        ch = span[end - 1]
        if ch in ".,;:!?":
            end -= 1
            continue
        if ch in _CLOSERS and span.count(_CLOSERS[ch], 0, end) < span.count(ch, 0, end):
            end -= 1
            continue
        break
    return span[:end], span[end:]


def _strip_url_credentials(url: str) -> str:
    """Remove userinfo and credential query values from one URL.

    Two shapes carry them: userinfo (``https://user:pass@host/``) and
    credential-bearing query parameters (``?api_key=...``). The scheme, host,
    port and path survive — which agent was besieged, or which service a
    transcript names, is the point of the record.

    A URL carrying neither is returned *byte for byte*, not round-tripped
    through urlunsplit. This runs over every transcript now, and a URL is
    evidence a report may need to cite; re-encoding one that held no secret
    would rewrite the record for nothing.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme or not parts.netloc:
        return url
    has_userinfo = "@" in parts.netloc
    pairs = parse_qsl(parts.query, keep_blank_values=True) if parts.query else []
    has_secret_param = any(k.lower() in _SECRET_QUERY_KEYS for k, _ in pairs)
    if not has_userinfo and not has_secret_param:
        return url

    netloc = parts.netloc
    if has_userinfo:
        netloc = f"[redacted:credential]@{netloc.rsplit('@', 1)[1]}"
    query = parts.query
    if has_secret_param:
        query = urlencode(
            [(k, "[redacted]" if k.lower() in _SECRET_QUERY_KEYS else v) for k, v in pairs],
            # Keep the placeholder legible: a header that reads
            # "api_key=%5Bredacted%5D" makes a reader decode a plain fact.
            quote_via=quote,
            safe="[]",
        )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _redact_url_span(match: re.Match[str]) -> str:
    url, trailing = _trim_trailing_punctuation(match.group(0))
    return _strip_url_credentials(url) + trailing


class RedactionLevel(StrEnum):
    OFF = "off"
    STANDARD = "standard"
    STRICT = "strict"


@dataclass(frozen=True)
class RedactionPattern:
    """One named shape and what replaces it.

    ``name`` is what a reader of the artifact sees ("who removed this and
    why"), so it is required — an anonymous redaction is unauditable.
    """

    name: str
    regex: re.Pattern[str]
    placeholder: str

    def apply(self, text: str) -> str:
        return self.regex.sub(self.placeholder, text)


def _p(name: str, pattern: str, placeholder: str, flags: int = 0) -> RedactionPattern:
    return RedactionPattern(name, re.compile(pattern, flags), placeholder)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_CARD_CANDIDATE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")


def _redact_cards(text: str) -> str:
    """Redact only digit runs that pass the Luhn checksum.

    Precision over recall on purpose: a 16-digit order id is evidence a report
    may need to cite, and the checksum is what tells the two apart without a
    tunable threshold.
    """
    def _sub(match: re.Match[str]) -> str:
        digits = re.sub(r"[ -]", "", match.group(0))
        return "[redacted:card]" if _luhn_ok(digits) else match.group(0)

    return _CARD_CANDIDATE.sub(_sub, text)


# Order matters: the most specific shapes first, so a private-key block or a
# JWT is taken whole before a looser credential pattern nibbles at it.
STANDARD_PACK: tuple[RedactionPattern, ...] = (
    _p(
        "private_key",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "[redacted:private-key]",
        re.DOTALL,
    ),
    _p("jwt", r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}", "[redacted:jwt]"),
    _p("api_key", r"\bsk-[A-Za-z0-9_-]{16,}", "[redacted:api-key]"),
    _p("github_token", r"\bgh[pousr]_[A-Za-z0-9]{20,}", "[redacted:token]"),
    _p(
        "aws_access_key",
        r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA)[A-Z0-9]{12,16}\b",
        "[redacted:aws-key]",
    ),
    _p("bearer", r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted:credential]"),
    _p("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[redacted:email]"),
    _p("us_ssn", r"\b\d{3}-\d{2}-\d{4}\b", "[redacted:ssn]"),
)

STRICT_EXTRA: tuple[RedactionPattern, ...] = (
    _p(
        "phone",
        r"(?<![\d.])\+?\d{0,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\d.])",
        "[redacted:phone]",
    ),
    _p(
        "ipv4",
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b",
        "[redacted:ip]",
    ),
    _p("hex_digest", r"\b[0-9a-fA-F]{32,}\b", "[redacted:hex]"),
)


def _pack_for(level: RedactionLevel) -> tuple[RedactionPattern, ...]:
    if level is RedactionLevel.OFF:
        return ()
    if level is RedactionLevel.STANDARD:
        return STANDARD_PACK
    return STANDARD_PACK + STRICT_EXTRA


@dataclass(frozen=True)
class RedactionPolicy:
    """The compiled policy for one run. Immutable, so the boundary cannot be
    reconfigured halfway through a siege."""

    level: RedactionLevel
    patterns: tuple[RedactionPattern, ...]

    @classmethod
    def for_level(
        cls, level: str | RedactionLevel, custom: Iterable[RedactionPattern] | None = None
    ) -> RedactionPolicy:
        try:
            resolved = RedactionLevel(level)
        except ValueError as exc:
            allowed = "|".join(x.value for x in RedactionLevel)
            raise ValueError(f"unknown redaction level {level!r}; expected {allowed}") from exc
        return cls(level=resolved, patterns=_pack_for(resolved) + tuple(custom or ()))

    # -- text ------------------------------------------------------------
    def text(self, value: str) -> str:
        if not self.patterns and self.level is not RedactionLevel.STANDARD:
            return value
        out = value
        if self.level is not RedactionLevel.OFF:
            # URLs first, for two reasons. A credential in userinfo or a query
            # parameter is *structural* — it has no shape the pattern pack can
            # recognise. And `user:pass@host.tld` is email-shaped, so running
            # the pack first would rewrite it to "[redacted:email]" and give
            # the false impression the URL rule had done its job.
            out = _URL_IN_TEXT.sub(_redact_url_span, out)
        for pattern in self.patterns:
            out = pattern.apply(out)
        if self.level is not RedactionLevel.OFF:
            out = _redact_cards(out)
        return out

    def _value(self, value: Any) -> Any:
        """Redact inside tool-call arguments, which nest arbitrarily."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self._value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._value(v) for v in value]
        return value

    # -- the boundary ----------------------------------------------------
    def transcript(self, transcript: Transcript) -> Transcript:
        """Return a copy with every turn (and tool argument) redacted.

        Turn indices, roles, tool names, persona and transcript id are left
        exactly as they were: they are the citation anchors, and a citation
        that no longer resolves is a worse failure than a leak.
        """
        turns = [
            turn.model_copy(
                update={
                    "content": self.text(turn.content),
                    "tool_calls": [
                        ToolCall(name=tc.name, arguments=self._value(tc.arguments))
                        for tc in turn.tool_calls
                    ],
                }
            )
            for turn in transcript.turns
        ]
        return transcript.model_copy(update={"turns": turns})

    def approach_error(self, error: ApproachError) -> ApproachError:
        """Error messages quote URLs and responses; they leak like any other text."""
        return error.model_copy(update={"message": self.text(error.message)})

    def endpoint(self, url: str) -> str:
        """The target URL the Report persists verbatim.

        Nothing special happens here, and that is the fix: URL credentials are
        stripped by :meth:`text`, which every persisted string already goes
        through. When this method owned the URL rule privately, the header
        field was redacted correctly while an ApproachError quoting the very
        same URL — and rendered two lines below it in the client-facing HTML —
        printed the password in full. One rule, one boundary, or an emitter
        will eventually be handed a URL that never met the policy.
        """
        return self.text(url)


def patterns_from_rubric_file(path: str | Path) -> list[RedactionPattern]:
    """Read the optional ``redaction:`` block a rubric may declare.

    A client's handling requirements ("redact our employee ids") belong beside
    the criteria they apply to, not in a flag, so the rubric carries them::

        redaction:
          patterns:
            - name: employee_id
              regex: "EMP-[0-9]{6}"
              placeholder: "[redacted:employee]"   # optional

    Read here rather than in ``rubric_parser`` so the rubric contract keeps its
    two-value shape; a malformed block is a hard error, never a silent no-op —
    a redaction rule that fails open is the failure mode that matters.
    """
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Rubric YAML must be a mapping; got {type(raw).__name__}")
    block = raw.get("redaction")
    if block is None:
        return []
    if not isinstance(block, dict) or not isinstance(block.get("patterns"), list):
        raise ValueError("Rubric 'redaction' must be a mapping with a 'patterns' list.")
    return _compile_custom(block["patterns"])


def _compile_custom(specs: Sequence[Any]) -> list[RedactionPattern]:
    patterns: list[RedactionPattern] = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError(f"Each redaction pattern must be a mapping; got {type(spec).__name__}")
        name = spec.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each redaction pattern needs a non-empty 'name'.")
        regex = spec.get("regex")
        if not isinstance(regex, str) or not regex:
            raise ValueError(f"Redaction pattern {name!r} needs a non-empty 'regex'.")
        try:
            compiled = re.compile(regex)
        except re.error as exc:
            raise ValueError(
                f"Redaction pattern {name!r} is not a valid regular expression: {exc}"
            ) from exc
        placeholder = spec.get("placeholder", f"[redacted:{name}]")
        if not isinstance(placeholder, str):
            raise ValueError(f"Redaction pattern {name!r} placeholder must be a string.")
        patterns.append(RedactionPattern(name, compiled, placeholder))
    return patterns
