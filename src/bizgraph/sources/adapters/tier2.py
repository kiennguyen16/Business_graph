"""Tier 2 adapters: keyed attachment sources (ASIC professional registers, GLEIF).

These carry an ABN / ACN / LEI / licence number some of the time and only a
name the rest of the time. Each adapter emits only identifiers that pass the
checksum validators in `bizgraph.normalise.identifiers`; anything else stays in
the payload as raw text so the name path can still use it.

ASIC registers (data.gov.au, CC BY 3.0 AU)
------------------------------------------
* ``asic_afsl``        afs_lic_YYYYMM.csv      one row per current AFS licence
* ``asic_credit``      credit_lic_YYYYMM.csv   one row per approved/suspended credit licence
* ``asic_banned_org``  bd_org_YYYYMM.csv       one row per organisation ban
* ``asic_liquidator``  liquidator_YYYYMM.csv   one row per registered liquidator (a person)

ASIC's help files say the ``.csv`` files are TAB separated; in the November
2026 snapshot the AFSL, credit and liquidator ``.csv`` files are actually comma
separated and the banned organisation ``.csv`` is tab separated. `parse` sniffs
the delimiter from the header line so either works.

Dates are DD/MM/YYYY. Free-text list fields (authorisations, business names,
status history, pre-FSR licences) are tilde ``~`` separated.

ABN/ACN column (``*_ABN_ACN``): 11 digits = ABN, 9 digits = ACN. The credit
file strips leading zeros from ACNs (7 and 8 digit values); these are
zero-padded and kept only if the padded value passes the ACN checksum.
``0`` means "not provided".

Whose number is it? An ACN is trusted (stated or derived from an ABN's last 9
digits) only when the entity's OWN name carries an Australian company legal
form (PTY / LTD / LIMITED / NL) and the name is not a trust ("ATF", "AS TRUSTEE
FOR", "... TRUST"), not two entities joined by "&" / "AND", and not a foreign
body. A sole trader's ABN passes the ACN check by chance about 1 time in 10,
and a trust's ABN or 9-digit number belongs to (or is derived from) its
trustee, so without these guards the exact path would merge different parties.
* foreign body (foreign legal form without PTY, or an "International" address)
  -> the 9-digit number is an ARBN (`IdScheme.ARBN`), never an ACN;
* trust-like or no legal form -> a 9-digit value is kept as
  ``payload["unverified_acn"]`` only.
Provenance of every ACN/ARBN is in ``payload["identifier_provenance"]``.

GLEIF (golden copy, CC0 1.0)
----------------------------
* ``gleif_l1``  LEI-CDF golden copy CSV (``*-gleif-lei2*.csv``), filtered to
  AU/NZ entities plus out-of-region counterparties referenced by kept
  relationships. Unfiltered golden copy zips also parse (streamed).
* ``gleif_l2``  RR-CDF golden copy CSV (``*-gleif-rr*.csv``), relationships
  with at least one AU/NZ end.

GLEIF L1 ``RegistrationAuthorityEntityID`` is the entity's number at its
business register. See `GleifL1Adapter.registration_identifiers` for which
registers are trusted and how trusts, funds, schemes, foreign bodies and
ANNULLED LEIs are handled.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, ClassVar

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.normalise.identifiers import validator_for
from bizgraph.sources.base import CsvSourceAdapter, RawRow, RejectRecord
from bizgraph.sources.registry import registry

csv.field_size_limit(2**31 - 1)  # AFSL condition text can run past the 128 KiB default

_ABN = validator_for(IdScheme.ABN)
_ACN = validator_for(IdScheme.ACN)
_LEI = validator_for(IdScheme.LEI)
_AFSL = validator_for(IdScheme.AFSL)
_ACL = validator_for(IdScheme.ACL)

_NON_DIGIT = re.compile(r"\D")
_WS = re.compile(r"\s+")

# --------------------------------------------------------------------------- helpers


def clean(value: Any) -> str:
    """Strip, fold non-breaking spaces (common in the ASIC files) and collapse whitespace."""
    if value is None:
        return ""
    return _WS.sub(" ", str(value).replace("\xa0", " ")).strip()


def parse_au_date(value: str | None) -> date | None:
    """DD/MM/YYYY -> date. Empty -> None. Anything else raises ValueError."""
    v = clean(value)
    if not v:
        return None
    return datetime.strptime(v, "%d/%m/%Y").date()


def _date_field(payload: dict[str, Any], key: str, raw: str | None) -> date | None:
    """Parse into payload[key] (ISO string); unparseable values are kept under date_errors."""
    try:
        d = parse_au_date(raw)
    except ValueError:
        payload.setdefault("date_errors", {})[key] = clean(raw)
        payload[key] = None
        return None
    payload[key] = d.isoformat() if d else None
    return d


def _iso_ts(value: str | None) -> str | None:
    """GLEIF timestamps (2012-11-29T00:00:00.000Z) -> ISO date."""
    v = clean(value)
    if len(v) < 10:
        return None
    try:
        return date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        return None


def split_tilde(value: str | None) -> list[str]:
    return [s for s in (clean(p) for p in (value or "").split("~")) if s]


def _unquote_fields(segment: str) -> list[str]:
    """Parse one tilde segment like '"a","b"' into ['a', 'b']."""
    try:
        fields = next(csv.reader([segment]))
    except (StopIteration, csv.Error):
        fields = [segment]
    return [clean(f) for f in fields]


# Australian company legal forms: only these allow an ACN (stated or derived from an ABN).
_COMPANY_FORM = re.compile(
    r"\b(PTY|PROPRIETARY|LTD|LIMITED|N\.?L\.?|NO LIABILITY)\b\.?", re.IGNORECASE
)
# Trustee markers: the name is (or acts for) a trust, so any ACN in the row is the trustee's.
_TRUSTEE_MARKER = re.compile(
    r"\bATF\b|\bA/T/F\b|\bAS\s+(?:THE\s+)?TRUSTEES?\s+(?:FOR|OF)\b|\bTRUSTEES?\s+FOR\b"
    r"|\bTRUSTEES\s+OF\b|^THE\s+TRUSTEES?\b(?!\s+(?:COMPANY|CORPORATION|LIMITED|LTD|PTY))",
    re.IGNORECASE,
)
# A name that ENDS in a trust / fund / scheme word is the trust itself, whatever precedes it.
_TRUST_END = re.compile(
    r"\b(?:TRUST|FUND|SCHEME|ETF|SETTLEMENT|PORTFOLIO)(?:\s+(?:NO\.?\s*)?#?\d+[A-Z]?)?"
    r"(?:\s*-\s*[A-Z ]+)?(?:\s*\([^)]*\))?\s*$",
    re.IGNORECASE,
)
# Foreign legal forms. A foreign body registered in Australia has an ARBN, not an ACN.
# Short forms (AG, SE, SA, NV ...) count only as the LAST token: 'SA' and 'ASA' also occur
# inside Australian names ('CREDIT UNION SA LTD', 'ASA FUNDS MANAGEMENT LIMITED').
_FOREIGN_FORM = re.compile(
    r"\b(?:LLP|L\.L\.P|L\.P|LLC|L\.L\.C|GMBH|AKTIENGESELLSCHAFT|S\.A|S\.P\.A|N\.V|B\.V|U\.A"
    r"|KABUSHIKI KAISHA|K\.K|SARL|S\.A\.R\.L|A/S|BHD|BERHAD|PTE|NATIONAL ASSOCIATION"
    r"|INCORPORATED)\b\.?"
    r"|\b(?:AG|SE|SA|SPA|NV|BV|ASA|OYJ|AB|LP|INC|SAS|KK|PLC)\.?\s*$"
    r"|,\s*INC\b|\bCO\.,\s*LTD|,\s*LTD\.?\s*$|,\s*LIMITED\s*$",
    re.IGNORECASE,
)
# Words that mark a name as an organisation (Australian and foreign forms, sector words).
_ORG_WORDS = re.compile(
    r"\b("
    r"PTY|PROPRIETARY|LTD|LIMITED|NL|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|"
    r"LLC|LLP|LP|L\.P|PLC|AG|SE|SA|SPA|S\.P\.A|NV|N\.V|BV|B\.V|U\.A|GMBH|ASA|OYJ|"
    r"TRUST|TRUSTEE|TRUSTEES|FUND|FOUNDATION|PARTNERSHIP|PARTNERS|ASSOCIATION|SOCIETY|SOCIETE|"
    r"COOPERATIVE|CO-OPERATIVE|COOPERATIEVE|BANK|BANKING|INSURANCE|ASSURANCE|FINANCE|FINANCIAL|"
    r"CAPITAL|INVESTMENTS?|MANAGEMENT|ADVISORS|ADVISERS|SERVICES|GROUP|HOLDINGS|MARKETS|"
    r"SECURITIES|CHURCH|COUNCIL|UNIVERSITY|AUTHORITY|DEPARTMENT|GOVERNMENT|CREDIT|UNION|"
    r"MUTUAL|LENDING|LOANS|MORTGAGES?|ENTERPRISES|INDUSTRIES|SOLUTIONS|CONSULTING|AUSTRALIA|"
    r"AUSTRALIAN|INTERNATIONAL|GLOBAL|GENERALE|PARIBAS|BROKERS?|AGENCY|CLUB|NOMINEES"
    r")\b",
    re.IGNORECASE,
)
# Entity words that rule out the 'LAST, GIVEN' person reading. Deliberately excludes short
# foreign forms (SE, SA) and sector words (BANK, UNION, CAPITAL, CHURCH): those are real
# surnames and given names ('KIM, SE JIN', 'BANK, MARY').
_COMMA_ENTITY = re.compile(
    r"\b(?:PTY|PROPRIETARY|LTD|LIMITED|INC|INCORPORATED|LLC|LLP|L\.?P|PLC|GMBH|CORP|CORPORATION"
    r"|COMPANY|CO\.|TRUST|TRUSTEES?|ASSOCIATION|HOLDINGS|NOMINEES|FUND|N\.?L)\b\.?",
    re.IGNORECASE,
)
_MULTI_SPLIT = re.compile(r"\s*&\s*|\s+AND\s+", re.IGNORECASE)
# A legal form that ENDS a part: 'A PTY LTD & B PTY LTD' has two; 'SA & JR PTY LTD' and
# 'PROPRIETARY & FIDUCIARY SERVICES PTY LTD' have one.
_FORM_AT_END = re.compile(
    r"(?:\bPTY\.?|\bLTD\.?|\bLIMITED|\bN\.?L\.?|\bLLC|\bLLP|\bPLC|\bINC\.?)\s*$",
    re.IGNORECASE,
)
_PERSON_TOKEN = re.compile(r"^[A-Z][A-Z'\-]*\.?$|^[A-Z]$", re.IGNORECASE)


def is_trust_like(name: str) -> bool:
    """Trustee marker anywhere, or the name ends in TRUST / FUND / SCHEME / ETF ..."""
    n = clean(name)
    return bool(_TRUSTEE_MARKER.search(n) or _TRUST_END.search(n))


def is_multi_party(name: str) -> bool:
    """Two or more legal-form names joined by '&' / 'AND' ('A PTY LTD & B PTY LTD')."""
    parts = _MULTI_SPLIT.split(clean(name))
    return sum(1 for p in parts if _FORM_AT_END.search(p.strip())) >= 2


def is_foreign_body(name: str, international: bool = False) -> bool:
    """Foreign legal form (or a foreign address) and no Australian 'PTY'."""
    n = clean(name)
    if re.search(r"\bPTY\b|\bPROPRIETARY\b", n, re.IGNORECASE):
        return False
    return bool(_FOREIGN_FORM.search(n)) or international


def acn_guard(name: str, international: bool = False) -> str | None:
    """None when a 9-digit number in this row may be the entity's own ACN, else why it is not."""
    n = clean(name)
    if not n:
        return "no_name"
    if is_foreign_body(n, international):
        return "foreign_body"
    if _TRUSTEE_MARKER.search(n):
        return "trustee_marker"
    if _TRUST_END.search(n):
        return "trust_or_fund_name"
    if is_multi_party(n):
        return "multi_party_name"
    if not _COMPANY_FORM.search(n):
        return "no_company_legal_form"
    return None


def classify_party(name: str, *, comma_person_format: bool = False) -> tuple[PartyType, str]:
    """Person vs organisation from the register name alone. Returns (type, basis).

    `comma_person_format`: the register writes people as 'LAST, GIVEN' (credit,
    liquidator). That shape is checked FIRST, because surnames and given names
    collide with organisation words ('CHURCH, JOHN', 'KIM, SE JIN'); it is
    rejected only by entity words or legal forms ('MIZUHO BANK, LTD.').
    The AFSL register switched to 'GIVEN LAST' in August 2026, so there the test
    is: no organisation word, 2 to 5 alphabetic tokens.
    Partnerships of individuals ('F PALMER & M E PALMER') are organisations.
    """
    n = clean(name).upper()
    if not n:
        return PartyType.UNKNOWN, "empty_name"
    if comma_person_format and n.count(",") == 1 and "&" not in n and " AND " not in n:
        family, given = (p.strip() for p in n.split(","))
        if (
            family
            and given
            and not _COMMA_ENTITY.search(n)
            and len(family.split()) <= 3
            and len(given.split()) <= 4
        ):
            return PartyType.PERSON, "last_comma_given_format"
    if _ORG_WORDS.search(n):
        return PartyType.ORGANISATION, "organisation_word"
    if "&" in n or " AND " in n:
        return PartyType.ORGANISATION, "partnership_of_individuals"
    if comma_person_format:
        return PartyType.ORGANISATION, "no_person_format"
    tokens = n.split()
    if 2 <= len(tokens) <= 5 and all(_PERSON_TOKEN.match(t) for t in tokens):
        return PartyType.PERSON, "given_last_format"
    return PartyType.ORGANISATION, "default_organisation"


def split_person_name(name: str) -> tuple[str | None, str | None]:
    """'LAST, GIVEN NAMES' -> (given, family). Other formats -> (None, None)."""
    n = clean(name)
    if n.count(",") != 1:
        return None, None
    family, given = (p.strip() for p in n.split(","))
    return (given or None), (family or None)


def abn_acn_identifiers(
    raw: str | None, name: str, payload: dict[str, Any], *, international: bool = False
) -> list[Identifier]:
    """Interpret an ASIC '*_ABN_ACN' cell. Writes raw value, provenance and guards into payload.

    11 digits: ABN (checksum). Its last 9 digits become an ACN only if `acn_guard` passes
    (never an ARBN: for a foreign body they go to payload `unverified_arbn`). 9 digits or fewer (zero-padded): ACN if `acn_guard`
    passes, ARBN for a foreign body, otherwise payload `unverified_acn` only.
    """
    digits = _NON_DIGIT.sub("", raw or "")
    payload["abn_acn_raw"] = clean(raw) or None
    prov: dict[str, str] = {}
    out: list[Identifier] = []
    guard = acn_guard(name, international)
    if not digits or set(digits) == {"0"}:
        payload["abn_acn_kind"] = "absent"
    elif len(digits) == 11:
        abn = _ABN.parse(digits)
        if abn:
            out.append(abn)
            prov["abn"] = "source"
            payload["abn_acn_kind"] = "abn"
            tail = _ACN.parse(digits[2:])
            if tail and guard is None:
                out.append(tail)
                prov["acn"] = "derived_from_abn"
            elif tail and guard == "foreign_body":
                # Not derived: a foreign body's ABN tail passes the checksum by chance as
                # often as a sole trader's (14 of 71 such AFSL values are in no register).
                payload["unverified_arbn"] = tail.value
                payload["acn_withheld_reason"] = guard
            elif tail:
                payload["acn_withheld_reason"] = guard
        else:
            payload["abn_acn_kind"] = "invalid_abn"
    elif len(digits) <= 9:
        padded = digits.zfill(9)
        how = "source" if len(digits) == 9 else "source_zero_padded"
        if not _ACN.is_valid(padded):
            payload["abn_acn_kind"] = "invalid_acn"
        elif guard is None:
            out.append(Identifier(IdScheme.ACN, padded))
            prov["acn"] = how
            payload["abn_acn_kind"] = "acn"
        elif guard == "foreign_body":
            out.append(Identifier(IdScheme.ARBN, padded))
            prov["arbn"] = how
            payload["abn_acn_kind"] = "arbn"
        else:
            payload["unverified_acn"] = padded
            payload["acn_withheld_reason"] = guard
            payload["abn_acn_kind"] = "unverified_acn"
    else:
        payload["abn_acn_kind"] = "invalid_length"
    payload["identifier_provenance"] = prov
    return out


# --------------------------------------------------------------------------- ASIC base


class _AsicRegisterAdapter(CsvSourceAdapter):
    """Delimiter-sniffing CSV/TSV reader for the ASIC data.gov.au registers."""

    tier: ClassVar[int] = 2
    licence: ClassVar[str] = "CC BY 3.0 AU"

    def parse(self, path: Path) -> Iterator[RawRow]:
        with path.open(newline="", encoding=self.encoding, errors="replace") as fh:
            header = fh.readline()
            delimiter = "\t" if header.count("\t") > header.count(",") else ","
            fh.seek(0)
            reader = csv.DictReader(fh, delimiter=delimiter)
            for row in reader:
                yield {
                    clean(k).lstrip("﻿"): (v.strip() if isinstance(v, str) else v)
                    for k, v in row.items()
                    if k is not None
                }

    def _record(
        self,
        row_id: str,
        snapshot_date: date,
        name: str,
        payload: dict[str, Any],
        party_type: PartyType,
        identifiers: list[Identifier],
        name_for_norm: str | None = None,
    ) -> SourceRecord:
        norm = self.names.normalise(name_for_norm or name)
        # dedupe identifiers, keep order
        seen: set[Identifier] = set()
        ids = tuple(i for i in identifiers if not (i in seen or seen.add(i)))
        return SourceRecord(
            source=self.source_id,
            record_id=row_id,
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=name,
            name_norm=norm.norm if norm else None,
            party_type=party_type,
            identifiers=ids,
        )


# --------------------------------------------------------------------------- AFSL


@registry.register
class AfslAdapter(_AsicRegisterAdapter):
    """ASIC AFS licensees (current licences only: there is no end date or cancelled status
    in this dataset, so cancellations are only visible as a licence disappearing between
    weekly snapshots). record_id = AFS licence number."""

    source_id: ClassVar[str] = "asic_afsl"
    description: ClassVar[str] = "ASIC Australian Financial Services licensees (data.gov.au)"

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        lic_raw = clean(row.get("AFS_LIC_NUM"))
        if not lic_raw:
            raise RejectRecord("missing_licence_number")
        lic = _AFSL.parse(lic_raw)
        if lic is None:
            raise RejectRecord("invalid_licence_number")
        name = clean(row.get("AFS_LIC_NAME"))
        if not name:
            raise RejectRecord("missing_name")

        party_type, basis = classify_party(name)
        payload: dict[str, Any] = {
            "register": clean(row.get("REGISTER_NAME")),
            "licence_kind": "AFSL",
            "licence_number": lic.value,
            "licence_number_raw": lic_raw,
            "name": name,
            "party_type_basis": basis,
            # The dataset only lists current licensees.
            "status": "current",
            "locality": clean(row.get("AFS_LIC_ADD_LOCAL")) or None,
            "state": clean(row.get("AFS_LIC_ADD_STATE")) or None,
            "postcode": clean(row.get("AFS_LIC_ADD_PCODE")) or None,
            "country": clean(row.get("AFS_LIC_ADD_COUNTRY")) or None,
        }
        _date_field(payload, "licence_start", row.get("AFS_LIC_START_DT"))
        payload["licence_end"] = None

        pre_fsr = []
        for seg in (row.get("AFS_LIC_PRE_FSR") or "").split("~"):
            if not clean(seg):
                continue
            f = _unquote_fields(seg)
            pre_fsr.append({"type": f[0], "number": f[1] if len(f) > 1 else None})
        payload["pre_fsr_licences"] = pre_fsr

        condition = row.get("AFS_LIC_CONDITION") or ""
        segments = [_unquote_fields(s) for s in condition.split("~") if clean(s)]
        payload["authorisation_format"] = (
            2 if segments and max(len(s) for s in segments) >= 3 else (1 if segments else None)
        )
        payload["authorisations"] = [" | ".join(f for f in s if f) for s in segments]

        international = (payload["country"] or "").lower() == "international"
        ids = [lic, *abn_acn_identifiers(row.get("AFS_LIC_ABN_ACN"), name, payload, international=international)]
        return self._record(lic.value, snapshot_date, name, payload, party_type, ids)


# --------------------------------------------------------------------------- Credit


_HISTORY = re.compile(r"^(?P<reason>.*?)\s+(?P<start>\d{2}/\d{2}/\d{4})(?:\s+(?P<end>\d{2}/\d{2}/\d{4}))?$")


def parse_status_history(value: str | None) -> list[dict[str, Any]]:
    out = []
    for seg in split_tilde(value):
        m = _HISTORY.match(seg)
        if not m:
            out.append({"reason": seg, "start": None, "end": None})
            continue
        start = parse_au_date(m["start"])
        end = parse_au_date(m["end"]) if m["end"] else None
        out.append(
            {
                "reason": m["reason"].strip(),
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            }
        )
    return out


@registry.register
class CreditLicenceAdapter(_AsicRegisterAdapter):
    """ASIC Australian credit licensees (approved and suspended). record_id = ACL number.

    People appear as 'LAST, GIVEN'. When the licensee also holds an AFSL the AFSL
    number is emitted as a second identifier, which links the two registers exactly.
    """

    source_id: ClassVar[str] = "asic_credit"
    description: ClassVar[str] = "ASIC Australian credit licensees (data.gov.au)"

    STATUS = {"APPR": "approved", "SUSP": "suspended"}

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        lic_raw = clean(row.get("CRED_LIC_NUM"))
        if not lic_raw:
            raise RejectRecord("missing_licence_number")
        lic = _ACL.parse(lic_raw)
        if lic is None:
            raise RejectRecord("invalid_licence_number")
        name = clean(row.get("CRED_LIC_NAME"))
        if not name:
            raise RejectRecord("missing_name")

        party_type, basis = classify_party(name, comma_person_format=True)
        given, family = split_person_name(name) if party_type is PartyType.PERSON else (None, None)
        status_code = clean(row.get("CRED_LIC_STATUS")).upper()
        payload: dict[str, Any] = {
            "register": clean(row.get("REGISTER_NAME")),
            "licence_kind": "ACL",
            "licence_number": lic.value,
            "licence_number_raw": lic_raw,
            "name": name,
            "party_type_basis": basis,
            "given_names": given,
            "family_name": family,
            "status_code": status_code or None,
            "status": self.STATUS.get(status_code, status_code.lower() or None),
            "status_history": parse_status_history(row.get("CRED_LIC_STATUS_HISTORY")),
            "locality": clean(row.get("CRED_LIC_LOCALITY")) or None,
            "state": clean(row.get("CRED_LIC_STATE")) or None,
            "postcode": clean(row.get("CRED_LIC_PCODE")) or None,
            "lat": clean(row.get("CRED_LIC_LAT")) or None,
            "lng": clean(row.get("CRED_LIC_LNG")) or None,
            "edrs": split_tilde(row.get("CRED_LIC_EDRS")),
            # Business names the licensee trades under: alias candidates for the name path.
            "business_names": split_tilde(row.get("CRED_LIC_BN")),
            "authorisations": split_tilde(row.get("CRED_LIC_AUTHORISATIONS")),
        }
        _date_field(payload, "licence_start", row.get("CRED_LIC_START_DT"))
        _date_field(payload, "licence_end", row.get("CRED_LIC_END_DT"))

        ids: list[Identifier] = [lic]
        afsl_raw = clean(row.get("CRED_LIC_AFSL_NUM"))
        afsl = _AFSL.parse(afsl_raw) if afsl_raw and set(afsl_raw) != {"0"} else None
        payload["afsl_number"] = afsl.value if afsl else None
        if afsl:
            ids.append(afsl)
        # The help file: a null state marks a foreign address.
        ids += abn_acn_identifiers(
            row.get("CRED_LIC_ABN_ACN"), name, payload, international=not payload["state"]
        )
        norm_name = f"{given} {family}" if given and family else name
        return self._record(lic.value, snapshot_date, name, payload, party_type, ids, norm_name)


# --------------------------------------------------------------------------- Banned orgs


@registry.register
class BannedOrgAdapter(_AsicRegisterAdapter):
    """ASIC banned and disqualified organisations. One row per ban.

    record_id = '{ACN or normalised name}|{ban type}|{start date}' because one
    organisation can carry several bans. A wrong link here publishes an
    accusation, so the adapter never derives or guesses identifiers: only an
    ACN that passes its checksum is emitted.
    """

    source_id: ClassVar[str] = "asic_banned_org"
    description: ClassVar[str] = "ASIC banned and disqualified organisations (data.gov.au)"

    PERMANENT = re.compile(r"permanent", re.IGNORECASE)

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        name = clean(row.get("BD_ORG_NAME"))
        if not name:
            raise RejectRecord("missing_name")
        ban_type = clean(row.get("BD_ORG_TYPE"))
        if not ban_type:
            raise RejectRecord("missing_ban_type")

        payload: dict[str, Any] = {
            "register": clean(row.get("REGISTER_NAME")),
            "name": name,
            "ban_type": ban_type,
            "ban_type_key": re.sub(r"[^a-z0-9]+", "_", ban_type.lower()).strip("_"),
            "document_url": None,
            "comment": None,
        }
        url = clean(row.get("BD_ORG_URL"))
        payload["document_url"] = url if url.lower().startswith("http") else None
        comment = clean(row.get("BD_ORG_COMMENT"))
        payload["comment"] = None if comment.lower() in ("", "no comment made") else comment

        start = _date_field(payload, "ban_start", row.get("BD_ORG_START_DT"))
        end_raw = clean(row.get("BD_ORG_END_DT"))
        payload["permanent"] = bool(self.PERMANENT.search(end_raw))
        if payload["permanent"]:
            payload["ban_end"] = None
        else:
            _date_field(payload, "ban_end", end_raw)
        if start is None:
            raise RejectRecord("missing_or_invalid_ban_start")

        acn_raw = clean(row.get("BD_ORG_ACN"))
        payload["acn_raw"] = acn_raw or None
        digits = _NON_DIGIT.sub("", acn_raw)
        number = _ACN.parse(digits.zfill(9)) if digits else None  # checksum only
        guard = acn_guard(name)
        ids: list[Identifier] = []
        payload["identifier_provenance"] = {}
        if number and guard is None:
            ids = [number]
            payload["identifier_provenance"] = {"acn": "source"}
        elif number and guard == "foreign_body":
            ids = [Identifier(IdScheme.ARBN, number.value)]
            payload["identifier_provenance"] = {"arbn": "source"}
        elif number:
            payload["unverified_acn"] = number.value
            payload["acn_withheld_reason"] = guard

        party_type, basis = classify_party(name, comma_person_format=True)
        if ids and party_type is not PartyType.ORGANISATION:
            party_type, basis = PartyType.ORGANISATION, "has_acn"
        payload["party_type_basis"] = basis

        # record_id keys on the checksum-valid number even when it is not trusted as an
        # identifier, so the id stays stable if the guard rules change.
        norm = self.names.normalise(name)
        key = number.value if number else (norm.norm if norm else name)
        record_id = f"{key}|{payload['ban_type_key']}|{start.isoformat()}"
        return self._record(record_id, snapshot_date, name, payload, party_type, ids)


# --------------------------------------------------------------------------- Liquidators


@registry.register
class LiquidatorAdapter(_AsicRegisterAdapter):
    """ASIC registered liquidators. Every row is a natural person ('LAST, GIVEN').

    record_id = registered liquidator number, also emitted as `IdScheme.LIQUIDATOR_NO`
    (format check only: digits, no public checksum). The firm is a name-only
    organisation reference in the payload.
    """

    source_id: ClassVar[str] = "asic_liquidator"
    description: ClassVar[str] = "ASIC registered liquidators (data.gov.au)"

    STATUS = {"APPR": "approved", "SUSP": "suspended"}

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        num = _NON_DIGIT.sub("", clean(row.get("LIQ_NUM")))
        if not num:
            raise RejectRecord("missing_liquidator_number")
        name = clean(row.get("LIQ_NAME"))
        if not name:
            raise RejectRecord("missing_name")
        given, family = split_person_name(name)
        status_code = clean(row.get("LIQ_STATUS")).upper()
        payload: dict[str, Any] = {
            "register": clean(row.get("REGISTER_NAME")),
            "liquidator_number": num,
            "official_liquidator_number": _NON_DIGIT.sub("", clean(row.get("OFF_LIQ_NUM"))) or None,
            "name": name,
            "given_names": given,
            "family_name": family,
            "party_type_basis": "register_lists_natural_persons",
            "status_code": status_code or None,
            "status": self.STATUS.get(status_code, status_code.lower() or None),
            "locality": clean(row.get("LIQ_ADD_LOCAL")) or None,
            "state": clean(row.get("LIQ_ADD_STATE")) or None,
            "postcode": clean(row.get("LIQ_ADD_PCODE")) or None,
            "country": clean(row.get("LIQ_ADD_COUNTRY")) or None,
            "firm": clean(row.get("LIQ_FIRM")) or None,
        }
        _date_field(payload, "registration_start", row.get("LIQ_START_DT"))
        _date_field(payload, "official_liquidator_start", row.get("OFF_LIQ_START_DT"))
        _date_field(payload, "suspension_date", row.get("LIQ_SUSP_DT"))
        norm_name = f"{given} {family}" if given and family else name
        ids = [Identifier(IdScheme.LIQUIDATOR_NO, num.lstrip("0") or "0")] if len(num) <= 9 else []
        return self._record(num, snapshot_date, name, payload, PartyType.PERSON, ids, norm_name)


# --------------------------------------------------------------------------- GLEIF


class _GleifCsvAdapter(CsvSourceAdapter):
    tier: ClassVar[int] = 2
    licence: ClassVar[str] = "CC0 1.0"
    encoding: ClassVar[str] = "utf-8"

    def parse(self, path: Path) -> Iterator[RawRow]:
        """Read the filtered CSV, or stream the first CSV member of a golden copy zip."""
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                with zf.open(member) as raw:
                    yield from self._rows(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            return
        with path.open(newline="", encoding="utf-8-sig") as fh:
            yield from self._rows(fh)

    @staticmethod
    def _rows(fh: Any) -> Iterator[RawRow]:
        reader = csv.reader(fh)
        header = next(reader)
        for values in reader:
            yield {h: v for h, v in zip(header, values) if v != ""}


def _address(row: RawRow, prefix: str) -> dict[str, Any] | None:
    keys = (
        "FirstAddressLine", "AddressNumber", "AddressNumberWithinBuilding", "MailRouting",
        "AdditionalAddressLine.1", "AdditionalAddressLine.2", "AdditionalAddressLine.3",
        "City", "Region", "Country", "PostalCode",
    )
    out = {k.replace(".", "_").lower(): clean(row.get(f"{prefix}.{k}")) or None for k in keys}
    return out if any(out.values()) else None


@registry.register
class GleifL1Adapter(_GleifCsvAdapter):
    """GLEIF Level 1 (who is who). record_id = LEI.

    Emits the LEI plus whatever `registration_identifiers` trusts from the
    RegistrationAuthorityEntityID (ABN, ACN, ARBN, ARSN, NZBN, NZ company number).
    """

    source_id: ClassVar[str] = "gleif_l1"
    description: ClassVar[str] = "GLEIF golden copy Level 1 (LEI-CDF), AU/NZ filtered"

    # GLEIF Registration Authorities (looked up via api.gleif.org/api/v1/registration-authorities):
    #   RA000014 ASIC Register of Companies  -> ACN for an Australian company. For a foreign
    #            body the same ASIC number space holds its ARBN. For a trust or fund GLEIF
    #            records the TRUSTEE company's ACN (or the scheme's ARSN), so see
    #            `registration_identifiers` for how those are split.
    #   RA000013 Australian Business Register, RA000762 ATO Super Fund Lookup,
    #   RA000714 APRA RSE register           -> ABN (11 digits, checksum)
    #   RA001192 ASIC Register of Australian Registered Schemes -> ARSN. Same checksum as an
    #            ACN but numbers a managed investment scheme; emitted only as IdScheme.ARSN.
    #   RA000466 NZ Companies Office         -> NZBN (13 digits, GS1 check) or NZ company
    #            number (up to 8 digits). About 1 in 10 NZ company numbers pass the ACN
    #            checksum by chance; they are never read as ACNs.
    #   RA000016 ORIC Register of Indigenous Corporations -> ICN, payload only (no IdScheme).
    ABN_RA: ClassVar[frozenset[str]] = frozenset({"RA000013", "RA000762", "RA000714"})
    ASIC_COMPANY_RA: ClassVar[str] = "RA000014"
    ARSN_RA: ClassVar[str] = "RA001192"
    NZ_RA: ClassVar[str] = "RA000466"
    PAYLOAD_ONLY_RA: ClassVar[dict[str, str]] = {"RA000016": "oric_icn"}
    # Which identifier schemes each registration authority may produce (used by tests/audit).
    RA_ALLOWED_SCHEMES: ClassVar[dict[str, frozenset[IdScheme]]] = {
        "RA000014": frozenset({IdScheme.ACN, IdScheme.ARBN, IdScheme.ARSN}),
        "RA000013": frozenset({IdScheme.ABN}),
        "RA000762": frozenset({IdScheme.ABN}),
        "RA000714": frozenset({IdScheme.ABN}),
        "RA001192": frozenset({IdScheme.ARSN}),
        "RA000466": frozenset({IdScheme.NZBN, IdScheme.NZ_COMPANY_NO}),
    }
    # ISO 20275 ELF codes for Australia (GLEIF ELF code list v1.6, 2026-02-19, CC0).
    ELF_AU_COMPANY: ClassVar[frozenset[str]] = frozenset(
        {"TXVC", "R4KK", "LZFR", "Q82Q", "PQHL"}
    )  # Pty Ltd, public by shares, by guarantee, unlimited Pty, NL
    ELF_AU_TRUST: ClassVar[str] = "7TPC"  # Trust
    ELF_AU_FUND: ClassVar[str] = "ADXG"  # Fund
    ELF_AU_LP: ClassVar[str] = "J4JC"  # Limited Partnership
    ELF_AU_OTHER: ClassVar[frozenset[str]] = frozenset(
        {"6W6X", "BC38", "XHCV"}
    )  # Co-operative, Incorporated association, Indigenous corporation
    ELF_UNSPECIFIED: ClassVar[frozenset[str]] = frozenset({"", "8888", "9999"})
    # Personal (family / super) trusts: the number in the row is the trustee's ACN.
    PERSONAL_TRUST: ClassVar[re.Pattern[str]] = re.compile(
        r"\bFAMILY\b|\bSUPER(?:ANNUATION)?\b|\bSMSF\b|\bDISCRETIONARY\b|\bPENSION\b", re.IGNORECASE
    )
    # Pooled vehicles: the number in the row is the scheme's ARSN.
    SCHEME_WORDS: ClassVar[re.Pattern[str]] = re.compile(
        r"\bFUND\b|\bETF\b|\bSCHEME\b|\bPORTFOLIO\b|\bINCOME\b|\bEQUITY\b|\bPROPERTY\b"
        r"|\bINDUSTRIAL TRUST\b|\bWHOLESALE\b",
        re.IGNORECASE,
    )
    COUNTRIES: ClassVar[frozenset[str]] = frozenset({"AU", "NZ"})

    @staticmethod
    def _nzbn_valid(digits: str) -> bool:
        """NZBN is a GS1 GTIN-13 starting 94: weights 1,3 alternating, mod 10 check digit."""
        if len(digits) != 13 or not digits.startswith("94"):
            return False
        total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
        return (10 - total % 10) % 10 == int(digits[12])

    def registration_identifiers(
        self, payload: dict[str, Any], name: str
    ) -> tuple[list[Identifier], dict[str, str], str | None]:
        """Map RegistrationAuthorityEntityID to identifiers. Returns (ids, provenance, kind).

        Whose number is it:
        * ANNULLED LEI (issued in error): nothing but the LEI is trusted.
        * RA000014 + trust / LP ELF code, trustee marker or a personal-trust name: the
          number belongs to the trustee (or general partner) -> payload `trustee_acn`.
        * RA000014 + fund ELF code or a pooled-vehicle name without a company legal form:
          the number is the scheme's ARSN -> IdScheme.ARSN.
        * RA000014 + foreign ELF code / foreign jurisdiction / foreign legal form -> ARBN.
        * RA000014 otherwise: ACN when the name has an Australian company legal form, or the
          ELF code says Australian company; else payload `unverified_acn`.
        """
        ra_id = payload["registration_authority_id"] or ""
        raw = payload["registration_authority_entity_id"]
        if not raw:
            return [], {}, None
        digits = _NON_DIGIT.sub("", raw)
        prov_tag = "registration_authority_entity_id"
        if payload["registration_status"] == "ANNULLED" and (
            ra_id in self.ABN_RA or ra_id in (self.ASIC_COMPANY_RA, self.ARSN_RA)
        ):
            payload["withheld_registration_number"] = raw
            return [], {}, "withheld_annulled_lei"

        if ra_id in self.ABN_RA:
            abn = _ABN.parse(digits) if len(digits) == 11 else None
            return ([abn], {"abn": prov_tag}, "abn") if abn else ([], {}, "invalid_or_other")

        if ra_id == self.ARSN_RA:
            payload["arsn"] = raw
            ok = 0 < len(digits) <= 9 and _ACN.is_valid(digits.zfill(9))
            # The scheme register also lists listed investment companies and CCIVs
            # ('WAM Capital Limited'), which carry their company ACN there. A company-named
            # entity on this register is neither a trusted ARSN nor a trusted ACN.
            if ok and (acn_guard(name) is None or re.search(r"\bCCIV\b", name, re.IGNORECASE)):
                payload["unverified_acn"] = digits.zfill(9)
                payload["acn_withheld_reason"] = "company_name_on_scheme_register"
                return [], {}, "unverified_acn"
            if ok:
                return [Identifier(IdScheme.ARSN, digits.zfill(9))], {"arsn": prov_tag}, "arsn"
            return [], {}, "invalid_or_other"

        if ra_id == self.NZ_RA:
            if len(digits) == 13:
                payload["nzbn"] = raw
                if self._nzbn_valid(digits):
                    return [Identifier(IdScheme.NZBN, digits)], {"nzbn": prov_tag}, "nzbn"
                return [], {}, "invalid_or_other"
            payload["nz_company_number"] = raw
            if 0 < len(digits) <= 8 and digits == raw.strip():
                value = digits.lstrip("0") or "0"
                return [Identifier(IdScheme.NZ_COMPANY_NO, value)], {"nz_company_no": prov_tag}, "nz_company_number"
            return [], {}, "invalid_or_other"

        if ra_id in self.PAYLOAD_ONLY_RA:
            kind = self.PAYLOAD_ONLY_RA[ra_id]
            payload[kind] = raw
            return [], {}, kind

        if ra_id != self.ASIC_COMPANY_RA:
            return [], {}, None

        number = digits.zfill(9) if 0 < len(digits) <= 9 and _ACN.is_valid(digits.zfill(9)) else None
        if number is None:
            return [], {}, "invalid_or_other"
        elf = payload["legal_form_code"] or ""
        n = clean(name)
        trustee_marker = bool(_TRUSTEE_MARKER.search(n))
        trust_name = bool(_TRUST_END.search(n))
        own_company_form = bool(_COMPANY_FORM.search(n)) and not trustee_marker and not trust_name

        if elf in (self.ELF_AU_TRUST, self.ELF_AU_FUND) or trustee_marker or trust_name:
            pooled = elf == self.ELF_AU_FUND or bool(self.SCHEME_WORDS.search(n))
            personal = trustee_marker or bool(self.PERSONAL_TRUST.search(n)) or bool(_COMPANY_FORM.search(n))
            if pooled and not personal:
                return [Identifier(IdScheme.ARSN, number)], {"arsn": "registration_authority_entity_id_scheme"}, "arsn"
            if personal:
                payload["trustee_acn"] = number
                return [], {}, "trustee_acn"
            # A named trust with no trustee marker and no pooled-vehicle words ('Dexus
            # Operations Trust'): could be the trustee's ACN or the scheme's ARSN.
            payload["trust_registration_number"] = number
            return [], {}, "trust_number_unclassified"

        foreign_elf = elf not in (
            self.ELF_AU_COMPANY | self.ELF_AU_OTHER | self.ELF_UNSPECIFIED | {self.ELF_AU_LP}
        )
        jurisdiction = payload["legal_jurisdiction"] or ""
        foreign = foreign_elf or (bool(jurisdiction) and not jurisdiction.startswith("AU"))
        guard = acn_guard(n, international=foreign)
        if guard == "foreign_body":
            return [Identifier(IdScheme.ARBN, number)], {"arbn": prov_tag}, "arbn"
        if guard is None or (guard == "no_company_legal_form" and elf in self.ELF_AU_COMPANY):
            return [Identifier(IdScheme.ACN, number)], {"acn": prov_tag}, "acn"
        if elf == self.ELF_AU_LP and not own_company_form:
            payload["general_partner_acn"] = number
            return [], {}, "general_partner_acn"
        payload["unverified_acn"] = number
        payload["acn_withheld_reason"] = guard
        return [], {}, "unverified_acn"

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        raw_lei = clean(row.get("LEI"))
        if not raw_lei:
            raise RejectRecord("missing_lei")
        lei = _LEI.parse(raw_lei)
        if lei is None:
            raise RejectRecord("invalid_lei_checksum")
        name = clean(row.get("Entity.LegalName"))
        if not name:
            raise RejectRecord("missing_name")

        other_names = []
        for i in range(1, 6):
            v = clean(row.get(f"Entity.OtherEntityNames.OtherEntityName.{i}"))
            if v:
                other_names.append({"name": v, "type": row.get(f"Entity.OtherEntityNames.OtherEntityName.{i}.type")})
        for i in range(1, 6):
            v = clean(row.get(f"Entity.TransliteratedOtherEntityNames.TransliteratedOtherEntityName.{i}"))
            if v:
                other_names.append(
                    {
                        "name": v,
                        "type": row.get(
                            f"Entity.TransliteratedOtherEntityNames.TransliteratedOtherEntityName.{i}.type"
                        ),
                    }
                )
        legal = _address(row, "Entity.LegalAddress")
        hq = _address(row, "Entity.HeadquartersAddress")
        state = None
        for addr in (legal, hq):
            region = (addr or {}).get("region") or ""
            if region.startswith("AU-"):
                state = region[3:]
                break
        countries = {(legal or {}).get("country"), (hq or {}).get("country")}
        jurisdiction = clean(row.get("Entity.LegalJurisdiction")) or None
        in_region = bool(countries & self.COUNTRIES) or (jurisdiction or "")[:2] in self.COUNTRIES

        ra_id = clean(row.get("Entity.RegistrationAuthority.RegistrationAuthorityID")) or None
        ra_entity_id = clean(row.get("Entity.RegistrationAuthority.RegistrationAuthorityEntityID")) or None
        category = clean(row.get("Entity.EntityCategory")) or None
        payload: dict[str, Any] = {
            "lei": lei.value,
            "legal_name": name,
            "legal_name_lang": row.get("Entity.LegalName.xmllang"),
            "other_names": other_names,
            "legal_address": legal,
            "headquarters_address": hq,
            "state": state,
            "country": (legal or {}).get("country"),
            "legal_jurisdiction": jurisdiction,
            "in_scope": "au_nz" if in_region else "referenced_counterparty",
            "entity_category": category,
            "entity_sub_category": clean(row.get("Entity.EntitySubCategory")) or None,
            "legal_form_code": clean(row.get("Entity.LegalForm.EntityLegalFormCode")) or None,
            "legal_form_other": clean(row.get("Entity.LegalForm.OtherLegalForm")) or None,
            "entity_status": clean(row.get("Entity.EntityStatus")) or None,
            "entity_creation_date": _iso_ts(row.get("Entity.EntityCreationDate")),
            "entity_expiration_date": _iso_ts(row.get("Entity.EntityExpirationDate")),
            "entity_expiration_reason": clean(row.get("Entity.EntityExpirationReason")) or None,
            "successor_leis": [
                v for i in range(1, 6) if (v := clean(row.get(f"Entity.SuccessorEntity.{i}.SuccessorLEI")))
            ],
            "associated_lei": clean(row.get("Entity.AssociatedEntity.AssociatedLEI")) or None,
            "registration_authority_id": ra_id,
            "registration_authority_other_id": clean(
                row.get("Entity.RegistrationAuthority.OtherRegistrationAuthorityID")
            ) or None,
            "registration_authority_entity_id": ra_entity_id,
            "registration_status": clean(row.get("Registration.RegistrationStatus")) or None,
            "initial_registration_date": _iso_ts(row.get("Registration.InitialRegistrationDate")),
            "last_update_date": _iso_ts(row.get("Registration.LastUpdateDate")),
            "next_renewal_date": _iso_ts(row.get("Registration.NextRenewalDate")),
            "managing_lou": clean(row.get("Registration.ManagingLOU")) or None,
            "validation_sources": clean(row.get("Registration.ValidationSources")) or None,
            "conformity_flag": clean(row.get("ConformityFlag")) or None,
        }

        # Registration status of the LEI itself. DUPLICATE: another LEI exists for the same
        # entity (resolution should not raise an identifier conflict for it); ANNULLED: issued
        # in error (no register number is trusted).
        payload["lei_status"] = payload["registration_status"]
        extra, prov, ra_kind = self.registration_identifiers(payload, name)
        ids: list[Identifier] = [lei, *extra]
        payload["registration_authority_entity_id_kind"] = ra_kind
        payload["identifier_provenance"] = prov

        # SOLE_PROPRIETOR is self-declared and includes business names ('Mega Clicks',
        # '... FAMILY CO PTY LIMITED'). PERSON only for the unambiguous 'LAST, GIVEN' shape;
        # a name with an organisation word is an ORGANISATION; anything else UNKNOWN.
        party_type, basis = PartyType.ORGANISATION, "gleif_entity_category"
        if category == "SOLE_PROPRIETOR":
            pt, name_basis = classify_party(name, comma_person_format=True)
            if pt is PartyType.PERSON:
                party_type = PartyType.PERSON
            elif _ORG_WORDS.search(name) or _COMPANY_FORM.search(name):
                party_type = PartyType.ORGANISATION
            else:
                party_type = PartyType.UNKNOWN
            basis = f"sole_proprietor_{name_basis}"
        payload["party_type_basis"] = basis
        norm = self.names.normalise(name)
        return SourceRecord(
            source=self.source_id,
            record_id=lei.value,
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=name,
            name_norm=norm.norm if norm else None,
            party_type=party_type,
            identifiers=tuple(ids),
        )


@registry.register
class GleifL2Adapter(_GleifCsvAdapter):
    """GLEIF Level 2 relationship records (who owns whom).

    The golden copy has no relationship id, so record_id = 'start|type|end'. The
    record describes an edge, not a party: it carries no name and no identifiers.
    Every record has `start_lei` / `end_lei`. Only accounting-consolidation types
    (`PARENT_TYPES`) also carry `child_lei` (StartNode) / `parent_lei` (EndNode):
    IS_FUND-MANAGED_BY, IS_SUBFUND_OF, IS_FEEDER_TO and IS_INTERNATIONAL_BRANCH_OF
    are not ownership, so no ownership traversal can mistake a fund manager for a
    parent by reading `parent_lei`.
    """

    source_id: ClassVar[str] = "gleif_l2"
    description: ClassVar[str] = "GLEIF golden copy Level 2 relationship records (RR-CDF), AU/NZ filtered"

    PARENT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY"}
    )

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        if clean(row.get("Relationship.StartNode.NodeIDType")) != "LEI" or clean(
            row.get("Relationship.EndNode.NodeIDType")
        ) != "LEI":
            raise RejectRecord("non_lei_node")
        child = _LEI.parse(clean(row.get("Relationship.StartNode.NodeID")))
        parent = _LEI.parse(clean(row.get("Relationship.EndNode.NodeID")))
        if child is None or parent is None:
            raise RejectRecord("invalid_lei_checksum")
        rel_type = clean(row.get("Relationship.RelationshipType"))
        if not rel_type:
            raise RejectRecord("missing_relationship_type")
        if child == parent:
            raise RejectRecord("self_relationship")

        periods = []
        for i in range(1, 6):
            ptype = clean(row.get(f"Relationship.Period.{i}.periodType"))
            start = _iso_ts(row.get(f"Relationship.Period.{i}.startDate"))
            end = _iso_ts(row.get(f"Relationship.Period.{i}.endDate"))
            if ptype or start or end:
                periods.append({"type": ptype or None, "start": start, "end": end})
        rel_period = next((p for p in periods if p["type"] == "RELATIONSHIP_PERIOD"), None)
        qualifiers = [
            {"dimension": d, "category": clean(row.get(f"Relationship.Qualifiers.{i}.QualifierCategory")) or None}
            for i in range(1, 6)
            if (d := clean(row.get(f"Relationship.Qualifiers.{i}.QualifierDimension")))
        ]
        quantifiers = []
        for i in range(1, 6):
            method = clean(row.get(f"Relationship.Quantifiers.{i}.MeasurementMethod"))
            amount = clean(row.get(f"Relationship.Quantifiers.{i}.QuantifierAmount"))
            if method or amount:
                quantifiers.append(
                    {
                        "method": method or None,
                        "amount": amount or None,
                        "units": clean(row.get(f"Relationship.Quantifiers.{i}.QuantifierUnits")) or None,
                    }
                )
        payload: dict[str, Any] = {
            "start_lei": child.value,
            "end_lei": parent.value,
            "relationship_type": rel_type,
            "is_parent_relationship": rel_type in self.PARENT_TYPES,
            "relationship_status": clean(row.get("Relationship.RelationshipStatus")) or None,
            "periods": periods,
            "valid_from": rel_period["start"] if rel_period else None,
            "valid_to": rel_period["end"] if rel_period else None,
            "qualifiers": qualifiers,
            "quantifiers": quantifiers,
            "registration_status": clean(row.get("Registration.RegistrationStatus")) or None,
            "initial_registration_date": _iso_ts(row.get("Registration.InitialRegistrationDate")),
            "last_update_date": _iso_ts(row.get("Registration.LastUpdateDate")),
            "next_renewal_date": _iso_ts(row.get("Registration.NextRenewalDate")),
            "managing_lou": clean(row.get("Registration.ManagingLOU")) or None,
            "validation_sources": clean(row.get("Registration.ValidationSources")) or None,
            "validation_documents": clean(row.get("Registration.ValidationDocuments")) or None,
            "validation_reference": clean(row.get("Registration.ValidationReference")) or None,
        }
        if rel_type in self.PARENT_TYPES:
            payload["child_lei"] = child.value
            payload["parent_lei"] = parent.value
        return SourceRecord(
            source=self.source_id,
            record_id=f"{child.value}|{rel_type}|{parent.value}",
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=None,
            name_norm=None,
            party_type=PartyType.UNKNOWN,
            identifiers=(),
        )


# --------------------------------------------------------------------------- GLEIF slice


def filter_gleif_golden_copy(
    l1_zip: Path, rr_zip: Path, l1_out: Path, rr_out: Path, countries: frozenset[str] = frozenset({"AU", "NZ"})
) -> dict[str, int]:
    """Cut the GLEIF golden copy down to `countries`, keeping the golden copy columns as-is.

    Pass 1: L1 rows whose legal address, headquarters address or legal jurisdiction
            is in `countries`.
    Pass 2: RR rows with at least one end in the pass-1 set.
    Pass 3: L1 rows for counterparties those relationships reference outside `countries`
            (foreign parents and foreign children), so every kept edge has both nodes.
    Streams both zips; the 5 GB L1 CSV is read twice (about 6 minutes on a laptop).
    """

    def reader(zpath: Path) -> Iterator[list[str]]:
        with zipfile.ZipFile(zpath) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(member) as raw:
                yield from csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))

    stats: dict[str, int] = {}
    keep: set[str] = set()
    l1_out.parent.mkdir(parents=True, exist_ok=True)
    rr_out.parent.mkdir(parents=True, exist_ok=True)
    with l1_out.open("w", encoding="utf-8", newline="") as out:
        w = csv.writer(out, quoting=csv.QUOTE_ALL)
        rows = reader(l1_zip)
        header = next(rows)
        ix = {h: i for i, h in enumerate(header)}
        la, hq, jur = (
            ix["Entity.LegalAddress.Country"],
            ix["Entity.HeadquartersAddress.Country"],
            ix["Entity.LegalJurisdiction"],
        )
        w.writerow(header)
        n = 0
        for row in rows:
            n += 1
            if row[la] in countries or row[hq] in countries or row[jur][:2] in countries:
                keep.add(row[0])
                w.writerow(row)
        stats.update(l1_rows=n, l1_in_region=len(keep))

    referenced: set[str] = set()
    with rr_out.open("w", encoding="utf-8", newline="") as out:
        w = csv.writer(out, quoting=csv.QUOTE_ALL)
        rows = reader(rr_zip)
        w.writerow(next(rows))
        n = kept = 0
        for row in rows:
            n += 1
            if row[0] in keep or row[2] in keep:
                kept += 1
                w.writerow(row)
                referenced.update(x for x in (row[0], row[2]) if x not in keep)
        stats.update(rr_rows=n, rr_kept=kept, referenced_outside=len(referenced))

    with l1_out.open("a", encoding="utf-8", newline="") as out:
        w = csv.writer(out, quoting=csv.QUOTE_ALL)
        rows = reader(l1_zip)
        next(rows)
        found = 0
        for row in rows:
            if row[0] in referenced:
                w.writerow(row)
                found += 1
        stats["referenced_found"] = found
    return stats
