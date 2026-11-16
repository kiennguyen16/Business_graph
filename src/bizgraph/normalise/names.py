"""Business name normalisation.

Produces a comparison form plus the pieces the matcher needs as evidence:
the legal form that was stripped, trustee / trading-as splits, and the
distinctive tokens (what is left after generic business words), which is the
feature that separates e.g. "Commonwealth Bank of Australia" from
"Commonwealth Superannuation Corporation".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Ordered longest first so "PROPRIETARY LIMITED" wins over "LIMITED".
_LEGAL_FORMS: list[tuple[str, str]] = [
    ("PROPRIETARY LIMITED", "PTY LTD"),
    ("PROPRIETARY LTD", "PTY LTD"),
    ("PTY LIMITED", "PTY LTD"),
    ("PTY LTD", "PTY LTD"),
    ("PTY", "PTY LTD"),
    ("NO LIABILITY", "NL"),
    ("NL", "NL"),
    ("LIMITED", "LTD"),
    ("LTD", "LTD"),
    ("INCORPORATED", "INC"),
    ("INC", "INC"),
    ("CORPORATION", "CORP"),
    ("CORP", "CORP"),
    ("COMPANY", "CO"),
    ("CO", "CO"),
    ("PLC", "PLC"),
    ("LLC", "LLC"),
]

_TRUSTEE_SPLIT = re.compile(
    r"\b(?:AS TRUSTEES? FOR|AS TRUSTEES? OF|ATF|TRUSTEES? FOR|TRUSTEES? OF)\b"
)
# Bare "TA" is deliberately absent: it is a real token in some names.
_TRADING_SPLIT = re.compile(r"(?:\bTRADING AS\b|\bT/AS\b|\bT/A\b)")

# Generic words that carry little identity on their own. Kept in the
# normalised name; only excluded from the distinctive-token set.
GENERIC_TOKENS: frozenset[str] = frozenset(
    """
    THE OF AND FOR IN ON AT A AN
    AUSTRALIA AUSTRALIAN AUST AUS NEW ZEALAND NZ NATIONAL INTERNATIONAL GLOBAL PACIFIC ASIA
    GROUP HOLDINGS HOLDING SERVICES SERVICE SOLUTIONS MANAGEMENT ENTERPRISES ENTERPRISE
    INVESTMENTS INVESTMENT NOMINEES NOMINEE TRUST TRUSTEE TRUSTEES PARTNERS PARTNERSHIP
    CAPITAL FINANCIAL FINANCE CONSULTING CONSULTANTS INDUSTRIES INDUSTRY TRADING
    PTY LTD LIMITED INC CORP CO NL PLC LLC
    """.split()
)

_PUNCT = re.compile(r"[^\w\s/]")
_SPACE = re.compile(r"\s+")


# External-administration status appended to registered names, e.g.
# "ACME PTY LTD (IN LIQUIDATION)". Parentheses are already gone after _clean.
_STATUS_SUFFIX = re.compile(
    r"\s+(?:IN LIQUIDATION|IN PROVISIONAL LIQUIDATION|IN ADMINISTRATION|ADMINISTRATORS? APPOINTED"
    r"|RECEIVERS? AND MANAGERS? APPOINTED|RECEIVERS? APPOINTED|MANAGERS? APPOINTED"
    r"|CONTROLLERS? APPOINTED|DEREGISTERED|STRUCK OFF)$"
)


@dataclass(frozen=True)
class NormalisedName:
    raw: str
    norm: str  # comparison form, legal form removed
    legal_form: str | None
    trustee_of: str | None = None  # the trust named after a trustee marker (the entity itself)
    trustee: str | None = None  # the trustee named before the marker, if any
    trading_as: str | None = None
    status_suffix: str | None = None  # e.g. IN LIQUIDATION, removed from norm
    truncated: bool = False  # ASIC cuts names at 100 chars and appends '*'
    tokens: tuple[str, ...] = field(default_factory=tuple)
    distinctive: frozenset[str] = field(default_factory=frozenset)

    @property
    def block_token(self) -> str | None:
        """First distinctive token in name order; the default blocking key."""
        for t in self.tokens:
            if t in self.distinctive:
                return t
        return self.tokens[0] if self.tokens else None


class NameNormaliser:
    def _clean(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = text.upper().replace("&", " AND ").replace("+", " AND ")
        text = text.replace(".", "").replace("'", "")
        text = _PUNCT.sub(" ", text)
        return _SPACE.sub(" ", text).strip()

    def _strip_legal_form(self, text: str) -> tuple[str, str | None]:
        for form, canonical in _LEGAL_FORMS:
            if text == form:
                continue
            if text.endswith(" " + form):
                return text[: -len(form) - 1].strip(), canonical
        return text, None

    def _strip_entity_name(self, text: str) -> tuple[str, str | None]:
        """Remove a leading THE, trailing legal forms (repeatedly, e.g. "& CO PTY LTD") and dangling AND."""
        text = re.sub(r"^THE\s+", "", text)
        legal_form = None
        for _ in range(2):
            text, form = self._strip_legal_form(text)
            if form is None:
                break
            legal_form = legal_form or form
            text = re.sub(r"\s+AND$", "", text)  # "SMITH AND CO" -> "SMITH"
        text = text.replace("/", " ")
        return _SPACE.sub(" ", text).strip(), legal_form

    def normalise(self, raw: str | None) -> NormalisedName | None:
        """Normalise an organisation (or unknown-type) name.

        A trust is registered as "The Trustee for X Trust" or "A Pty Ltd ATF X Trust".
        The entity holding the ABN is the trust, so the comparison form is the TRUST
        name; the trustee is kept separately as evidence.
        """
        if not raw or not raw.strip():
            return None
        truncated = raw.rstrip().endswith("*")
        text = self._clean(raw)

        status_suffix = None
        m = _STATUS_SUFFIX.search(text)
        if m:
            status_suffix = m.group(0).strip()
            text = text[: m.start()].strip()

        trustee_of = trustee = None
        parts = _TRUSTEE_SPLIT.split(text, maxsplit=1)
        if len(parts) == 2:
            left = re.sub(r"^THE\s*$|^THE\s+TRUSTEES?$", "", parts[0].strip()).strip()
            right = re.sub(r"^THE\s+", "", parts[1].strip()).strip()
            if right:
                trustee_of, trustee = right, left or None
                text = right
            # no trust named after the marker: keep the left side as the name

        trading_as = None
        parts = _TRADING_SPLIT.split(text, maxsplit=1)
        if len(parts) == 2 and parts[0].strip():
            text, trading_as = parts[0].strip(), parts[1].strip() or None

        stripped, legal_form = self._strip_entity_name(text)
        text = stripped or self._clean(raw)  # never collapse to empty

        tokens = tuple(text.split())
        distinctive = frozenset(t for t in tokens if t not in GENERIC_TOKENS and len(t) > 1)
        return NormalisedName(
            raw=raw,
            norm=text,
            legal_form=legal_form,
            trustee_of=trustee_of,
            trustee=trustee,
            trading_as=trading_as,
            status_suffix=status_suffix,
            truncated=truncated,
            tokens=tokens,
            distinctive=distinctive,
        )

    def normalise_person(self, raw: str | None) -> NormalisedName | None:
        """Normalise an individual's name: no legal-form stripping (a surname like CO stays)."""
        if not raw or not raw.strip():
            return None
        text = self._clean(raw)
        if "," in raw:  # "LAST, GIVEN" -> "GIVEN LAST"
            last, _, given = raw.partition(",")
            text = self._clean(f"{given} {last}")
        tokens = tuple(text.split())
        return NormalisedName(
            raw=raw,
            norm=text,
            legal_form=None,
            tokens=tokens,
            distinctive=frozenset(t for t in tokens if len(t) > 1),
        )
