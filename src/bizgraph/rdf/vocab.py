"""Vocabulary constants, IRI factory and N-Triples term serialisation.

Everything here is pure string work so the exporter can stream tens of
millions of triples without building rdflib objects. Terms are returned as
ready-to-write N-Triples tokens (``<iri>``, ``"literal"^^<dt>``).

IRI patterns (ontology/schema.ttl, NOTES.md):

* party           ``urn:abn:{abn}`` else ``urn:acn:{acn}`` else ``urn:lei:{lei}``
* source record   ``urn:src:{source}:{record_id}``
* fact            ``urn:fact:{source}:{record_id}[:{n}]``
* link            ``urn:link:{matcher_version}:{source}:{record_id}``
* abstention      ``urn:abstention:{matcher_version}:{source}:{record_id}``
* graphs          ``urn:graph:source:{source}:{snapshot_date}``, ``urn:graph:canonical``,
                  ``urn:graph:links:{matcher_version}``, ``urn:graph:ontology``

Record ids are free text in some sources (banned organisations key on a
normalised name with spaces; GLEIF L2 ids contain ``|``), and neither is legal
in an IRI. Each IRI segment is therefore percent-encoded (RFC 3987 unreserved
characters, sub-delims, ``:`` and ``@`` are kept; everything else, including
``%`` itself, becomes ``%XX`` of its UTF-8 bytes). Ids made of letters, digits
and ``-._~`` (ABNs, ACNs, LEIs, licence numbers) are unchanged, and the raw id
is always available as the ``bg:recordId`` literal.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from bizgraph.domain.models import AbstainReason as _AbstainReason

BG = "https://w3id.org/bizgraph/ont#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PROV = "http://www.w3.org/ns/prov#"
SH = "http://www.w3.org/ns/shacl#"

GRAPH_CANONICAL = "urn:graph:canonical"
GRAPH_ONTOLOGY = "urn:graph:ontology"
GRAPH_LICENCE_HISTORY = "urn:graph:derived:licence_history"


def iri(value: str) -> str:
    """N-Triples IRI token for an already-safe absolute IRI."""
    return f"<{value}>"


def bg(local: str) -> str:
    return f"<{BG}{local}>"


RDF_TYPE = f"<{RDF}type>"
PROV_DERIVED = f"<{PROV}wasDerivedFrom>"

XSD_STRING = f"{XSD}string"
XSD_DATE = f"{XSD}date"
XSD_DECIMAL = f"{XSD}decimal"
XSD_INTEGER = f"{XSD}integer"
XSD_ANYURI = f"{XSD}anyURI"


class P:
    """Predicates as N-Triples tokens. Every one must be defined in schema.ttl (tested)."""

    type = RDF_TYPE
    derived = PROV_DERIVED
    # party
    name = bg("name")
    nameNorm = bg("nameNorm")
    otherName = bg("otherName")
    givenNames = bg("givenNames")
    familyName = bg("familyName")
    entityType = bg("entityType")
    registrationStatus = bg("registrationStatus")
    state = bg("state")
    postcode = bg("postcode")
    anzsic = bg("anzsic")
    registeredOn = bg("registeredOn")
    deregisteredOn = bg("deregisteredOn")
    abn = bg("abn")
    acn = bg("acn")
    arbn = bg("arbn")
    arsn = bg("arsn")
    nzbn = bg("nzbn")
    nzCompanyNumber = bg("nzCompanyNumber")
    lei = bg("lei")
    # record-only identifiers (licence / registration numbers move between holders)
    afslNumber = bg("afslNumber")
    aclNumber = bg("aclNumber")
    liquidatorNumber = bg("liquidatorNumber")
    # descriptive attributes, on parties and records
    country = bg("country")
    legalJurisdiction = bg("legalJurisdiction")
    legalFormCode = bg("legalFormCode")
    leiRegistrationStatus = bg("leiRegistrationStatus")
    # source record / snapshot
    sourceId = bg("sourceId")
    recordId = bg("recordId")
    snapshotDate = bg("snapshotDate")
    contentHash = bg("contentHash")
    nameRaw = bg("nameRaw")
    partyTypeHint = bg("partyTypeHint")
    recordsIn = bg("recordsIn")
    fileHash = bg("fileHash")
    # facts
    validFrom = bg("validFrom")
    validTo = bg("validTo")
    validToNotBefore = bg("validToNotBefore")
    validToNotAfter = bg("validToNotAfter")
    aboutRecord = bg("aboutRecord")
    counterpartyRecord = bg("counterpartyRecord")
    counterpartyAcn = bg("counterpartyAcn")
    counterpartyName = bg("counterpartyName")
    description = bg("description")
    licenceNumber = bg("licenceNumber")
    licenceKind = bg("licenceKind")
    licenceStatus = bg("licenceStatus")
    authorisation = bg("authorisation")
    banType = bg("banType")
    relationshipKind = bg("relationshipKind")
    relationshipStatus = bg("relationshipStatus")
    amountAud = bg("amountAud")
    regulator = bg("regulator")
    infringementNumber = bg("infringementNumber")
    noticeCount = bg("noticeCount")
    legislation = bg("legislation")
    sourceUrl = bg("sourceUrl")
    foreignReference = bg("foreignReference")
    ownershipPercentage = bg("ownershipPercentage")
    # party-level roles (links graph only)
    licensee = bg("licensee")
    bannedParty = bg("bannedParty")
    noticeRecipient = bg("noticeRecipient")
    member = bg("member")
    owner = bg("owner")
    owned = bg("owned")
    trust = bg("trust")
    trustee = bg("trustee")
    # resolution
    sourceRecord = bg("sourceRecord")
    matchedRecord = bg("matchedRecord")
    party = bg("party")
    matchType = bg("matchType")
    confidence = bg("confidence")
    evidence = bg("evidence")
    matcherVersion = bg("matcherVersion")
    bestCandidate = bg("bestCandidate")
    score = bg("score")
    abstainReason = bg("abstainReason")


class C:
    """Classes and SKOS concepts used as objects."""

    Party = bg("Party")
    Organisation = bg("Organisation")
    ManagedInvestmentScheme = bg("ManagedInvestmentScheme")
    Person = bg("Person")
    SourceRecord = bg("SourceRecord")
    SourceSnapshot = bg("SourceSnapshot")
    Licence = bg("Licence")
    Ban = bg("Ban")
    InfringementNotice = bg("InfringementNotice")
    Ownership = bg("Ownership")
    Trusteeship = bg("Trusteeship")
    Affiliation = bg("Affiliation")
    Link = bg("Link")
    Abstention = bg("Abstention")
    AFSL = bg("AFSL")
    ACL = bg("ACL")
    REGISTERED_LIQUIDATOR = bg("REGISTERED_LIQUIDATOR")
    HAS_TRUSTEE = bg("HAS_TRUSTEE")
    ACTS_FOR = bg("ACTS_FOR")


MATCH_TYPES = frozenset(
    {
        "EXACT_ABN", "EXACT_ACN", "EXACT_LEI", "EXACT_LICENCE_NO",
        "NAME_NORMALISED_EXACT", "NAME_FUZZY", "NAME_SEMANTIC", "WIKIDATA_ALIAS",
    }
)
# Derived from the domain enum so the exporter cannot drift from the matcher;
# tests/test_ontology.py checks the enum against bg:AbstainReasonScheme.
ABSTAIN_REASONS = frozenset(r.value for r in _AbstainReason)
RELATIONSHIP_KINDS = frozenset(
    {"IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY", "IS_INTERNATIONAL_BRANCH_OF", "SHAREHOLDING", "ACTS_FOR",
     "HAS_TRUSTEE"}
)

# --------------------------------------------------------------------------- literals

# ", \, LF and CR must be escaped (N-Triples STRING_LITERAL_QUOTE); other C0 controls and DEL
# are escaped too (\t \b \f or \u00XX) so no tool chokes on raw control bytes.
_ESCAPES: dict[int, str] = {i: f"\\u{i:04X}" for i in range(0x20)}
_ESCAPES.update({0x7F: "\\u007F", 0x22: '\\"', 0x5C: "\\\\", 0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t", 0x08: "\\b", 0x0C: "\\f"})
_NEEDS_ESCAPE = re.compile(r'[\x00-\x1f\x7f"\\\ud800-\udfff]')
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def escape_literal(value: str) -> str:
    """Escape a lexical form for N-Triples. Non-ASCII is written as raw UTF-8 (legal in N-Triples);
    lone surrogates (not encodable as UTF-8) become U+FFFD."""
    if not _NEEDS_ESCAPE.search(value):
        return value
    value = _SURROGATE.sub("\ufffd", value)
    return value.translate(_ESCAPES)


def lit(value: Any) -> str:
    """Plain string literal (xsd:string is implicit in RDF 1.1)."""
    return f'"{escape_literal(str(value))}"'


def lit_typed(lexical: str, datatype: str) -> str:
    return f'"{escape_literal(lexical)}"^^<{datatype}>'


def as_date(value: Any) -> date | None:
    """date, datetime or ISO 'YYYY-MM-DD...' string -> date; anything else -> None."""
    if value is None:
        return None
    if isinstance(value, date):
        return value if type(value) is date else value.date()  # datetime -> date
    s = str(value).strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def lit_date(value: Any) -> str | None:
    d = as_date(value)
    return None if d is None else lit_typed(d.isoformat(), XSD_DATE)


def decimal_lexical(value: Any) -> str | None:
    """Canonical-ish xsd:decimal lexical form: no exponent, no trailing zeros beyond one decimal."""
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0")
        if s.endswith("."):
            s += "0"
    else:
        s += ".0"
    if s.startswith("-") and set(s[1:]) <= {"0", "."}:
        s = s[1:]
    return s


def lit_decimal(value: Any) -> str | None:
    s = decimal_lexical(value)
    return None if s is None else lit_typed(s, XSD_DECIMAL)


def lit_integer(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return lit_typed(str(int(value)), XSD_INTEGER)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- IRIs

_SAFE = "-._~!$&'()*+,;=:@"


def seg(value: Any) -> str:
    """Percent-encode one IRI segment (see module docstring)."""
    return quote(str(value), safe=_SAFE)


class IriFactory:
    """Deterministic IRIs from natural keys. Returns bare IRI strings (wrap with `iri()`)."""

    @staticmethod
    def party(abn: str | None = None, acn: str | None = None, lei: str | None = None,
              canonical_key: str | None = None) -> str | None:
        if abn:
            return f"urn:abn:{seg(abn)}"
        if acn:
            return f"urn:acn:{seg(acn)}"
        if lei:
            return f"urn:lei:{seg(lei)}"
        return IriFactory.party_from_key(canonical_key) if canonical_key else None

    @staticmethod
    def party_from_key(key: str) -> str:
        """canonical_key -> IRI when no identifier columns are at hand.
        'urn:...' is kept; 'abn:X' / 'acn:X' / 'lei:X' / 'party:...' get the urn: prefix;
        anything else is minted under urn:party:."""
        if key.startswith("urn:"):
            return key
        scheme, sep, rest = key.partition(":")
        if sep and scheme.lower() in ("abn", "acn", "lei", "party", "arbn"):
            return f"urn:{scheme.lower()}:{':'.join(seg(p) for p in rest.split(':'))}"
        return f"urn:party:{seg(key)}"

    @staticmethod
    def source_record(source: str, record_id: str) -> str:
        return f"urn:src:{seg(source)}:{seg(record_id)}"

    @staticmethod
    def fact(source: str, record_id: str, n: int | None = None) -> str:
        base = f"urn:fact:{seg(source)}:{seg(record_id)}"
        return base if n is None else f"{base}:{n}"

    @staticmethod
    def ended_licence(source: str, record_id: str, event_date: date | str) -> str:
        d = event_date.isoformat() if isinstance(event_date, date) else str(event_date)
        return f"urn:fact:{seg(source)}:{seg(record_id)}:ended:{d}"

    @staticmethod
    def affiliation(source: str, record_id: str) -> str:
        return f"urn:fact:{seg(source)}:{seg(record_id)}:affiliation"

    @staticmethod
    def trusteeship(lei: str) -> str:
        return f"urn:fact:gleif_l1:{seg(lei)}:trustee"

    @staticmethod
    def link(matcher_version: str, source: str, record_id: str) -> str:
        return f"urn:link:{seg(matcher_version)}:{seg(source)}:{seg(record_id)}"

    @staticmethod
    def abstention(matcher_version: str, source: str, record_id: str) -> str:
        return f"urn:abstention:{seg(matcher_version)}:{seg(source)}:{seg(record_id)}"

    @staticmethod
    def source_graph(source: str, snapshot_date: date | str) -> str:
        d = snapshot_date.isoformat() if isinstance(snapshot_date, date) else str(snapshot_date)
        return f"urn:graph:source:{seg(source)}:{d}"

    @staticmethod
    def links_graph(matcher_version: str) -> str:
        return f"urn:graph:links:{seg(matcher_version)}"

    canonical_graph = GRAPH_CANONICAL
    ontology_graph = GRAPH_ONTOLOGY


def predicates_used() -> set[str]:
    """Full IRIs of every predicate the exporter can emit (for the schema coverage test)."""
    out = set()
    for name, value in vars(P).items():
        if not name.startswith("_") and isinstance(value, str) and value.startswith("<"):
            out.add(value[1:-1])
    return out
