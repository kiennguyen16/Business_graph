"""Domain model. Mirrors ontology/schema.ttl.

`Fact` is the in-code equivalent of a reified edge: anything with its own
attributes or validity period (licence, ban, ownership, notice, sponsorship).
A new relationship type is a new Fact subclass plus an ontology subclass.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class IdScheme(StrEnum):
    ABN = "abn"
    ACN = "acn"
    ARBN = "arbn"
    ARSN = "arsn"  # registered managed investment scheme; shares the ACN checksum, never an ACN
    NZBN = "nzbn"
    NZ_COMPANY_NO = "nz_company_no"
    LEI = "lei"
    LIQUIDATOR_NO = "liquidator_no"
    AFSL = "afsl"
    ACL = "acl"
    ARTG_SPONSOR = "artg_sponsor"


class PartyType(StrEnum):
    ORGANISATION = "organisation"
    PERSON = "person"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Identifier:
    """Value object. `value` is always the normalised form (digits only for ABN/ACN)."""

    scheme: IdScheme
    value: str

    PARTY_SCHEMES = ("abn", "acn", "arbn", "lei")

    def iri(self) -> str:
        """Party IRI. Only party identifiers qualify: licence numbers belong to Licence facts."""
        if self.scheme.value not in self.PARTY_SCHEMES:
            raise ValueError(f"{self.scheme} is not a party identifier; licences are facts")
        return f"urn:{self.scheme.value}:{self.value}"


@dataclass(frozen=True)
class SourceRecord:
    """An immutable raw record exactly as a source asserted it.

    Never deleted after resolution: canonical parties and links are derived
    views over these, which is what makes merges reversible.
    """

    source: str
    record_id: str
    snapshot_date: date
    payload: dict[str, Any]
    name_raw: str | None = None
    name_norm: str | None = None
    party_type: PartyType = PartyType.UNKNOWN
    identifiers: tuple[Identifier, ...] = ()

    @property
    def content_hash(self) -> str:
        blob = json.dumps(self.payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:32]

    def identifier(self, scheme: IdScheme) -> str | None:
        for ident in self.identifiers:
            if ident.scheme == scheme:
                return ident.value
        return None

    def iri(self) -> str:
        return f"urn:src:{self.source}:{self.record_id}"


@dataclass
class Party:
    """Canonical party. party_type is never UNKNOWN here (only on SourceRecord)."""

    canonical_key: str
    name: str
    name_norm: str
    party_type: PartyType
    identifiers: list[Identifier] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)


@dataclass
class Organisation(Party):
    entity_type: str | None = None
    status: str | None = None
    state: str | None = None
    anzsic: str | None = None


@dataclass
class Person(Party):
    given_names: str | None = None
    family_name: str | None = None


class MatchType(StrEnum):
    """Values equal the skos:notation codes in ontology/schema.ttl (bg:MatchTypeScheme)."""

    EXACT_ABN = "EXACT_ABN"
    EXACT_ACN = "EXACT_ACN"
    EXACT_LEI = "EXACT_LEI"
    EXACT_LICENCE_NO = "EXACT_LICENCE_NO"
    NAME_NORMALISED_EXACT = "NAME_NORMALISED_EXACT"
    NAME_FUZZY = "NAME_FUZZY"
    NAME_SEMANTIC = "NAME_SEMANTIC"
    WIKIDATA_ALIAS = "WIKIDATA_ALIAS"

    @property
    def is_exact_path(self) -> bool:
        return self.name.startswith("EXACT_") or self is MatchType.NAME_NORMALISED_EXACT


class AbstainReason(StrEnum):
    """Values equal the skos:notation codes in bg:AbstainReasonScheme."""

    NO_CANDIDATE = "NO_CANDIDATE"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    AMBIGUOUS = "AMBIGUOUS"
    IDENTIFIER_CONFLICT = "IDENTIFIER_CONFLICT"
    PARTY_TYPE_CONFLICT = "PARTY_TYPE_CONFLICT"
    QUARANTINED_TARGET = "QUARANTINED_TARGET"


@dataclass
class Fact:
    """A reified assertion made by one source record.

    `subject_record` (the source record IRI) is always set. `subject_key` (the
    canonical party) is None until a link in the active links graph attributes
    it; an abstained record keeps its facts, unattributed.
    """

    fact_id: str
    subject_record: str
    subject_key: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    derived_from: list[str] = field(default_factory=list)  # SourceRecord IRIs

    def is_valid_on(self, d: date) -> bool:
        if self.valid_from and d < self.valid_from:
            return False
        if self.valid_to and d > self.valid_to:
            return False
        return True


@dataclass
class Licence(Fact):
    licence_no: str = ""
    kind: str = ""  # AFSL | ACL
    status: str | None = None
    authorisations: list[str] = field(default_factory=list)
    transferred_from: str | None = None  # fact_id of the previous holding period


@dataclass
class Ban(Fact):
    ban_type: str = ""


@dataclass
class Ownership(Fact):
    """subject_record is the owned (child) record; counterparty is the owner (parent)."""

    owned_record: str = ""
    owner_record: str = ""
    owned_key: str | None = None  # link-derived
    owner_key: str | None = None  # link-derived
    percentage: Decimal | None = None
    relationship_kind: str = ""  # e.g. IS_DIRECTLY_CONSOLIDATED_BY
    relationship_status: str | None = None


@dataclass
class Affiliation(Fact):
    """Extension-point example: a liquidator (person) acting for a firm."""

    member_record: str = ""
    affiliated_with_record: str = ""
    member_key: str | None = None
    affiliated_with_key: str | None = None


@dataclass
class InfringementNotice(Fact):
    regulator: str = "ACCC"
    amount_aud: Decimal | None = None
    description: str = ""


@dataclass
class ProductSponsorship(Fact):
    artg_id: str = ""
    product_name: str = ""
