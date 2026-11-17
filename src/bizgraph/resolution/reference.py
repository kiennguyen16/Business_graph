"""`Reference`: what the matcher is asked to resolve, from a SourceRecord or from free text.

A reference carries only *trusted* identifiers (checksum-valid and, for a source
record, emitted by the adapter as the entity's own). Numbers the adapter withheld
(`unverified_acn`, `trustee_acn`, ...) are not identifiers here; they stay in the
payload for evidence only, so they can neither link nor veto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.normalise.identifiers import validator_for
from bizgraph.normalise.names import NameNormaliser, NormalisedName

# Schemes that identify a party (a disagreement on one of them is an IDENTIFIER_CONFLICT).
PARTY_SCHEMES: frozenset[str] = frozenset({"abn", "acn", "arbn", "arsn", "lei", "nzbn", "nz_company_no"})
# Schemes that only locate a party through a fact that can transfer: a match is evidence,
# a disagreement is not a conflict.
LICENCE_SCHEMES: frozenset[str] = frozenset({"afsl", "acl", "liquidator_no"})

_STATE_KEYS = ("state", "State", "STATE", "state_code", "MainBusinessLocation_State", "address_state")
_AU_STATES = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")
# Registers whose record name is the entity's own registered legal name: such a reference is
# "formal" even without a legal form, so a business / trading name alias or an extra word in the
# candidate's name means a different entity (GLEIF 'MORGAN STANLEY' is not MORGAN STANLEY
# AUSTRALIA LIMITED).
REGISTER_SOURCES: frozenset[str] = frozenset(
    {"gleif_l1", "asic_afsl", "asic_credit", "asic_banned_org", "asic_liquidator", "asic_company", "abr"}
)
# Sources whose records are natural persons by nature: an UNKNOWN hint becomes PERSON.
PERSON_SOURCES: frozenset[str] = frozenset({"asic_liquidator"})

# Common given names (static seed; the matcher adds the frequent first tokens of person
# parties in the store). Used only to recognise person-shaped references.
COMMON_GIVEN_NAMES: frozenset[str] = frozenset(
    """
    JOHN DAVID PETER MICHAEL PAUL ROBERT JAMES MARK ANDREW STEPHEN WILLIAM RICHARD CHRISTOPHER
    ANTHONY GEOFFREY GRAHAM IAN BRUCE GARY KEVIN BRIAN ROSS TIMOTHY MATTHEW DANIEL SIMON JASON
    SCOTT BENJAMIN THOMAS NICHOLAS ADAM LUKE BEN TOM NICK JOSHUA SAMUEL ALEXANDER JONATHAN
    PHILIP PHILLIP ALAN ALLAN GREGORY GREG CRAIG DEAN TROY SHANE WAYNE DARREN GLENN GLEN
    TERRY TREVOR NEIL NEVILLE KEITH KENNETH COLIN BARRY RAYMOND RAY DOUGLAS DONALD RONALD
    GEORGE HENRY EDWARD FRANK JOSEPH CHARLES ARTHUR HUGH ROGER MARTIN PATRICK SEAN LIAM
    MARY SUSAN JENNIFER ELIZABETH MARGARET PATRICIA LINDA BARBARA SARAH KAREN LISA MICHELLE
    JULIE HELEN ANNE ANN JANE CATHERINE KATHERINE KATE DEBORAH CHRISTINE NICOLE REBECCA
    RACHEL EMMA JESSICA AMANDA MELISSA KYLIE LEANNE TRACEY TRACY SHARON WENDY JOANNE JO
    LOUISE ALISON ALICE ANGELA ROBYN JUDITH JUDY DIANE DIANNE CAROL CAROLYN KERRY KIM
    GILLIAN FIONA HEATHER JACQUELINE VICTORIA SOPHIE CHLOE GRACE HANNAH LAURA LAUREN AMY
    WEI LI XIN YAN MOHAMMED MOHAMMAD MUHAMMAD AHMED ALI RAJ PRIYA
    """.split()
)
COMMON_SURNAMES: frozenset[str] = frozenset(
    """
    SMITH JONES WILLIAMS BROWN TAYLOR WILSON JOHNSON WHITE MARTIN ANDERSON THOMPSON NGUYEN
    THOMAS WALKER HARRIS LEE RYAN ROBINSON KELLY KING DAVIS WRIGHT EVANS ROBERTS GREEN HALL
    WOOD JACKSON CLARKE CLARK PATEL KHAN MITCHELL HUGHES CAMPBELL MURPHY YOUNG ALLEN BELL
    MILLER MOORE SCOTT STEWART COOPER MORRIS WARD TURNER CHEN WANG ZHANG LIU TRAN LE PHAM
    """.split()
)


def _jurisdiction(payload: dict[str, Any]) -> str | None:
    """Country of the legal jurisdiction ('AU-NSW' -> 'AU'), else of the legal address (GLEIF)."""
    j = payload.get("legal_jurisdiction") or payload.get("legal_country")
    return str(j).strip().upper()[:2] or None if j else None


def _postcode(payload: dict[str, Any]) -> str | None:
    """An Australian 4-digit postcode stated by the source (register address or GLEIF legal address)."""
    pc = payload.get("postcode")
    if not pc:
        addr = payload.get("legal_address") or {}
        if (addr.get("country") or "").upper() == "AU":
            pc = addr.get("postalcode")
    pc = str(pc).strip() if pc else ""
    return pc if len(pc) == 4 and pc.isdigit() else None


def _normalise(names: NameNormaliser, raw: str | None, ptype: PartyType) -> NormalisedName | None:
    """Individuals get the person normaliser ('LAST, GIVEN' -> 'GIVEN LAST', no legal forms)."""
    if ptype is PartyType.PERSON:
        return names.normalise_person(raw)
    return names.normalise(raw)


@dataclass(frozen=True)
class Reference:
    """Value object. `identifiers` holds trusted identifiers only."""

    name_raw: str | None
    normalised: NormalisedName | None
    identifiers: tuple[Identifier, ...] = ()
    party_type_hint: PartyType = PartyType.UNKNOWN
    state: str | None = None
    source: str = "adhoc"
    record_id: str = ""
    lei_status: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    state_basis: str = "register"  # 'text' when a free-text reference states the state
    jurisdiction: str | None = None  # ISO country of the legal jurisdiction (GLEIF), e.g. 'AU', 'NZ'
    postcode: str | None = None  # Australian postcode stated by the source
    party_type_basis: str | None = None  # how the source's party type was decided

    def alternative(self, normaliser: NameNormaliser | None = None) -> Reference | None:
        """The trading-as name ('X Pty Ltd t/as Y' -> Y) as a reference of its own, matched
        against names and aliases like the primary name; None when there is none."""
        if not self.normalised or not self.normalised.trading_as:
            return None
        alt = (normaliser or NameNormaliser()).normalise(self.normalised.trading_as)
        if alt is None or not alt.norm or alt.norm == self.name_norm:
            return None
        return replace(self, name_raw=self.normalised.trading_as, normalised=alt)

    @property
    def name_norm(self) -> str | None:
        return self.normalised.norm if self.normalised else None

    @property
    def distinctive(self) -> frozenset[str]:
        return self.normalised.distinctive if self.normalised else frozenset()

    @property
    def block_token(self) -> str | None:
        return self.normalised.block_token if self.normalised else None

    def ids(self, scheme: str) -> list[str]:
        return [i.value for i in self.identifiers if i.scheme.value == scheme]

    def party_ids(self) -> dict[str, set[str]]:
        """Party identifiers by scheme (the ones a candidate may conflict with)."""
        out: dict[str, set[str]] = {}
        for i in self.identifiers:
            if i.scheme.value in PARTY_SCHEMES:
                out.setdefault(i.scheme.value, set()).add(i.value)
        return out

    @property
    def formal(self) -> bool:
        """A registered legal name: carries a legal form, or comes from a register."""
        return bool(self.normalised and self.normalised.legal_form) or self.source in REGISTER_SOURCES

    @property
    def lei_is_duplicate(self) -> bool:
        return (self.lei_status or "").upper() == "DUPLICATE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "record_id": self.record_id,
            "name_raw": self.name_raw,
            "name_norm": self.name_norm,
            "legal_form": self.normalised.legal_form if self.normalised else None,
            "distinctive": sorted(self.distinctive),
            "identifiers": [[i.scheme.value, i.value] for i in self.identifiers],
            "party_type_hint": str(self.party_type_hint),
            "state": self.state,
            "state_basis": self.state_basis,
            "jurisdiction": self.jurisdiction,
            "postcode": self.postcode,
            "party_type_basis": self.party_type_basis,
            "lei_status": self.lei_status,
            "notes": list(self.notes),
        }

    # ------------------------------------------------------------------ constructors

    @classmethod
    def from_record(cls, record: SourceRecord, normaliser: NameNormaliser | None = None) -> Reference:
        names = normaliser or NameNormaliser()
        payload = record.payload or {}
        ptype = record.party_type
        if ptype is PartyType.UNKNOWN and record.source in PERSON_SOURCES:
            ptype = PartyType.PERSON
        lei_status = payload.get("lei_status")
        ids: list[Identifier] = []
        notes: list[str] = []
        for i in record.identifiers:
            if i.scheme is IdScheme.LEI and str(lei_status or "").upper() == "ANNULLED":
                # Issued in error: the LEI itself is not trusted to join or to veto.
                notes.append("annulled_lei_ignored")
                continue
            ids.append(i)
        state = None
        for k in _STATE_KEYS:
            v = payload.get(k)
            if v and str(v).strip().upper() in _AU_STATES:
                state = str(v).strip().upper()
                break
        return cls(
            name_raw=record.name_raw,
            normalised=_normalise(names, record.name_raw, ptype),
            identifiers=tuple(ids),
            party_type_hint=ptype,
            state=state,
            source=record.source,
            record_id=record.record_id,
            lei_status=str(lei_status) if lei_status else None,
            notes=tuple(notes),
            jurisdiction=_jurisdiction(payload),
            postcode=_postcode(payload),
            party_type_basis=payload.get("party_type_basis"),
        )


class ReferenceParser:
    """Parses a messy free-text reference ("Commonwealth Bank of Aust, ABN 48 123 123 124").

    Labelled numbers (ABN / ACN / ARBN / ARSN / AFSL / ACL / LEI) are extracted and
    checksum-validated; an unlabelled 11-digit group is taken as an ABN only when it
    passes the ABN checksum; an unlabelled 9-digit group is never taken (it passes the
    ACN check by chance one time in ten). Extracted spans are removed from the name.
    """

    _SEP = r"[\s:#.\-]*(?:NO\.?|NUMBER)?[\s:#.\-]*"
    _LABELLED = [
        (IdScheme.ABN, re.compile(r"\bABN" + _SEP + r"(\d[\d ]{9,14}\d)\b", re.IGNORECASE)),
        (IdScheme.ARBN, re.compile(r"\bARBN" + _SEP + r"(\d[\d ]{7,11}\d)\b", re.IGNORECASE)),
        (IdScheme.ARSN, re.compile(r"\bARSN" + _SEP + r"(\d[\d ]{7,11}\d)\b", re.IGNORECASE)),
        (IdScheme.ACN, re.compile(r"\bACN" + _SEP + r"(\d[\d ]{7,11}\d)\b", re.IGNORECASE)),
        (
            IdScheme.AFSL,
            re.compile(
                r"\b(?:AFSL|AFS\s+LICEN[CS]E|AUSTRALIAN\s+FINANCIAL\s+SERVICES\s+LICEN[CS]E)"
                + _SEP + r"(\d{4,7})\b",
                re.IGNORECASE,
            ),
        ),
        (
            IdScheme.ACL,
            re.compile(
                r"\b(?:ACL|AUSTRALIAN\s+CREDIT\s+LICEN[CS]E)" + _SEP + r"(\d{4,7})\b", re.IGNORECASE
            ),
        ),
        (IdScheme.LEI, re.compile(r"\b(?:LEI" + _SEP + r")?([A-Z0-9]{18}\d{2})\b", re.IGNORECASE)),
    ]
    _BARE_ABN = re.compile(r"(?<!\d)(\d{2}\s?\d{3}\s?\d{3}\s?\d{3})(?!\d)")
    _STATE = re.compile(r"[(\[]?\b(" + "|".join(_AU_STATES) + r")\b[)\]]?\s*\d{0,4}\s*$", re.IGNORECASE)
    # Unlabelled digit groups of 6+ digits (an ACN or phone number without a label) are never
    # identifiers and never name tokens.
    _DIGIT_GROUP = re.compile(r"(?<![\w])\d(?:[ ]?\d){5,}(?![\w])")
    _JUNK = re.compile(r"^[\s,;:()\[\]\-/|]+|[\s,;:()\[\]\-/|]+$")

    def __init__(self, normaliser: NameNormaliser | None = None) -> None:
        self.names = normaliser or NameNormaliser()

    def parse(self, text: str, source: str = "adhoc", record_id: str = "") -> Reference:
        text = text or ""
        work = text
        ids: list[Identifier] = []
        notes: list[str] = []
        spans: list[tuple[int, int]] = []

        def take(m: re.Match[str]) -> None:
            spans.append(m.span())

        for scheme, pattern in self._LABELLED:
            for m in pattern.finditer(work):
                if any(s <= m.start() < e for s, e in spans):
                    continue
                ident = validator_for(scheme).parse(m.group(1))
                if ident is None:
                    notes.append(f"invalid_{scheme.value}:{m.group(1).strip()}")
                    take(m)
                    continue
                if scheme is IdScheme.LEI and not m.group(0).upper().startswith("LEI") and not any(
                    c.isalpha() for c in m.group(1)
                ):
                    continue  # 20 bare digits: not an LEI claim
                if ident not in ids:
                    ids.append(ident)
                take(m)
        for m in self._BARE_ABN.finditer(work):
            if any(s <= m.start() < e for s, e in spans):
                continue
            ident = validator_for(IdScheme.ABN).parse(m.group(1))
            if ident is not None:
                if ident not in ids:
                    ids.append(ident)
                take(m)

        # Remove identifier spans (right to left) to leave the name.
        for s, e in sorted(spans, reverse=True):
            work = work[:s] + " " + work[e:]
        state = None
        work = self._DIGIT_GROUP.sub(" ", work)
        m = self._STATE.search(work)
        if m:
            state = m.group(1).upper()
            work = work[: m.start()]
        name = re.sub(r"\s+", " ", self._JUNK.sub("", work)).strip(" ,;")
        name = re.sub(r"\s*,\s*$", "", name)
        hint = self._party_type(name)
        return Reference(
            name_raw=name or None,
            normalised=_normalise(self.names, name, hint) if name else None,
            identifiers=tuple(ids),
            party_type_hint=hint,
            state=state,
            source=source,
            record_id=record_id,
            state_basis="text",
            notes=tuple(notes),
        )

    @staticmethod
    def _party_type(name: str) -> PartyType:
        """Free-text hint. Anything not clearly a person is treated as an organisation only
        when it carries an organisation word; otherwise UNKNOWN (strictest threshold)."""
        if not name:
            return PartyType.UNKNOWN
        from bizgraph.sources.adapters.tier2 import classify_party  # adapters import is heavy

        ptype, basis = classify_party(name, comma_person_format="," in name)
        if basis in ("default_organisation", "given_last_format"):
            # 'Acme Plumbing' has the 'GIVEN LAST' shape too: too weak to veto either type.
            return PartyType.UNKNOWN
        if basis == "no_person_format":
            return PartyType.ORGANISATION
        return ptype


def person_shaped(ref: Reference, given_names: frozenset[str] | set[str], surnames: frozenset[str] | set[str]) -> bool:
    """An UNKNOWN reference that looks like an individual's name: 2 to 4 alphabetic tokens, no
    legal form, no business word, first token a known given name (or an initial) and every
    other token a known surname or an initial. 'John Smith' is; 'Smith Plumbing' is not."""
    n = ref.normalised
    if n is None or n.legal_form or n.trustee_of or n.trading_as:
        return False
    toks = list(n.tokens)
    if not 2 <= len(toks) <= 4 or not all(t.isalpha() for t in toks):
        return False
    from bizgraph.normalise.names import GENERIC_TOKENS

    if any(t in GENERIC_TOKENS for t in toks):
        return False
    first, rest = toks[0], toks[1:]
    if not (len(first) == 1 or first in given_names):
        return False
    return all(len(t) == 1 or t in surnames or t in given_names for t in rest)
