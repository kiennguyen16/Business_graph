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

_TRUSTEE_SPLIT = re.compile(r"\b(?:AS TRUSTEE FOR|ATF|AS TRUSTEE OF|TRUSTEE FOR)\b")
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


@dataclass(frozen=True)
class NormalisedName:
    raw: str
    norm: str  # comparison form, legal form removed
    legal_form: str | None
    trustee_of: str | None = None
    trading_as: str | None = None
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

    def normalise(self, raw: str | None) -> NormalisedName | None:
        if not raw or not raw.strip():
            return None
        text = self._clean(raw)

        trustee_of = None
        parts = _TRUSTEE_SPLIT.split(text, maxsplit=1)
        if len(parts) == 2:
            text, trustee_of = parts[0].strip(), parts[1].strip() or None

        trading_as = None
        parts = _TRADING_SPLIT.split(text, maxsplit=1)
        if len(parts) == 2:
            text, trading_as = parts[0].strip(), parts[1].strip() or None

        text = re.sub(r"^THE ", "", text)
        text, legal_form = self._strip_legal_form(text)
        text = text.replace("/", " ")
        text = re.sub(r" AND$", "", text)  # "SMITH AND CO" -> "SMITH"
        text = _SPACE.sub(" ", text).strip()

        tokens = tuple(text.split())
        distinctive = frozenset(t for t in tokens if t not in GENERIC_TOKENS and len(t) > 1)
        return NormalisedName(
            raw=raw,
            norm=text,
            legal_form=legal_form,
            trustee_of=trustee_of,
            trading_as=trading_as,
            tokens=tokens,
            distinctive=distinctive,
        )
