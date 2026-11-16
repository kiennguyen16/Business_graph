"""Tier 3 adapters: name-only attachment sources.

ACCC infringement notices register (``accc_notice``)
----------------------------------------------------
https://www.accc.gov.au/public-registers/infringement-notices-register,
CC BY 4.0 ("Source: ACCC (c) Commonwealth of Australia"); third-party content
linked from entries is excluded from that licence and is not collected.

Collection (see outputs/sources.md, "ACCC fetch log"): robots.txt allows
``/public-registers/`` but disallows faceted listings (``?f[...]``) and
``/search``, so a collector pages the plain listing (``?page=N``) and fetches
each entry page, at least 2 s apart, with a descriptive User-Agent. Raw HTML is
cached under ``data/raw/accc_notice/notices/*.html`` so parsing reruns offline.
As of 2026-11-17 the site's CDN answers automated clients with HTTP 403. The
real sample is a FIELD EXTRACT taken in the user's own browser session
(``data/raw/accc_notice/extract_YYYYMMDD.txt``: '#' header, then one notice per
line ``slug|field=value|...`` with the Drupal field machine names
infringe-date-paid, infringe-number, infringe-section, name, acn, abn,
reference-number, plus list_title). `parse` reads extracts and cached HTML pages.

Real entry pages state NO penalty amount and only the date the notice was paid.
For extract records the penalty fields are None (basis "not_stated_on_register"),
identifiers come only from the stated abn / acn fields (checksum, plus the ACN
legal-form guard; an ACN is never derived from an ABN here), and
``reference-number`` (e.g. a Spanish CIF) stays in the payload as a foreign tax id.

Parsing is deliberately structure-light (the page template is Drupal and can
change): it reads the canonical URL, the <h1>, labelled fields
(``<dt>/<dd>``, ``field__label``/``field__item``, ``<th>/<td>``, "Label: value"
lines), ``<time datetime>``, then falls back to regexes over the text.

What a record carries (one record per register entry):
* record_id: the URL slug (stable), else the file stem.
* parties: recipient names as stated. An entry can name several parties
  ("A Pty Ltd and B Pty Ltd") or a natural person; each gets a party type
  using the tier 2 person/organisation rules. The record's name is the first party.
* date_issued (ISO), penalty_amounts_aud (every dollar amount stated next to
  "penalty"/"infringement"/"paid"), notice_count, penalty_total_aud (an amount
  stated as a total; else the single amount times the notice count when the
  text says "each"; else the single amount; else None + reason).
* legislation (Act / Law / Code names), description (first paragraph), url.
* Identifiers: NONE unless the page states an ABN or ACN explicitly; then it
  must pass the checksum, and an ACN also the tier 2 legal-form guard.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar

from lxml import html as lxml_html

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.normalise.identifiers import validator_for
from bizgraph.sources.adapters.tier2 import acn_guard, classify_party, clean
from bizgraph.sources.base import RawRow, RejectRecord, SourceAdapter
from bizgraph.sources.registry import registry

_ABN = validator_for(IdScheme.ABN)
_ACN = validator_for(IdScheme.ACN)

REGISTER_URL = "https://www.accc.gov.au/public-registers/infringement-notices-register"

_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?!\s*(?:million|m\b|billion))", re.I)
_MONEY_CONTEXT = re.compile(r"penalt|infringement|paid|pay\b|pays\b", re.I)
_TOTAL_CONTEXT = re.compile(r"\btotal(?:ling|ing)?\b|\bin total\b|\bcombined\b", re.I)
_EACH_CONTEXT = re.compile(r"\beach\b", re.I)
_NUMBER_WORDS = {
    "one": 1, "an": 1, "a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_NOTICE_COUNT = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|an|a)\s+"
    r"infringement\s+notices?\b",
    re.I,
)
_LEGISLATION = re.compile(
    r"\b([A-Z][\w()']*\s+(?:(?:[A-Z][\w()']*|and|of|the|for)\s+){0,7}"
    r"(?:Act|Law|Code|Regulations?)(?:\s+\d{4})?)\b"
)
_LEGISLATION_STOP = re.compile(r"^(?:The|Under|Of|In|And|Section|A|An)\s+", re.I)
_ID = re.compile(r"\b(ABN|ACN)\s*:?\s*((?:\d[\s]?){9,11})\b")
_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y")
_DATE_TEXT = re.compile(
    r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{4})\b"
)
_PARTY_SPLIT = re.compile(r"\s*;\s*|\s*&\s*|\s+and\s+|,\s+(?=[A-Z])", re.I)
_ORG_FORM_END = re.compile(
    r"(?:\bPty\.?|\bLtd\.?|\bLimited|\bInc\.?|\bLLC|\bPLC|\bCorporation|\bN\.?L\.?)\s*$", re.I
)
_TITLE_NOISE = re.compile(
    r"\s*(?:[-:|]\s*)?(?:pays?|paid|issued with|receives?|received)\b.*$", re.I
)
_DATE_LABELS = ("date issued", "date of issue", "issue date", "date", "published", "notice date")
_AMOUNT_LABELS = ("penalty", "amount", "infringement notice amount", "penalty amount")
_PARTY_LABELS = ("company", "trader", "recipient", "issued to", "business", "party", "parties")
_LEG_LABELS = ("legislation", "law", "act", "provision", "alleged contravention")


def _parse_date(text: str | None) -> date | None:
    t = clean(text)
    if not t:
        return None
    t = t.split("T")[0] if re.match(r"\d{4}-\d{2}-\d{2}T", t) else t
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    m = _DATE_TEXT.search(t)
    if m:
        return datetime.strptime(m.group(1), "%d %B %Y").date()
    return None


def _money(match: re.Match[str]) -> Decimal | None:
    try:
        return Decimal(match.group(1).replace(",", "") + "." + (match.group(2) or "00"))
    except InvalidOperation:
        return None


def split_parties(name: str) -> list[str]:
    """'A Pty Ltd and B Pty Ltd' -> two parties; 'Smith & Jones Pty Ltd' stays one.

    Split only when EVERY resulting part ends in a legal form, or the parts are separated
    by ';' (the register's own list separator)."""
    n = clean(name)
    if not n:
        return []
    if ";" in n:
        return [p for p in (clean(x) for x in n.split(";")) if p]
    parts = [p for p in (clean(x) for x in _PARTY_SPLIT.split(n)) if p]
    if len(parts) > 1 and all(_ORG_FORM_END.search(p) for p in parts):
        return parts
    return [n]


def party_type_hint(name: str) -> tuple[PartyType, str]:
    """Tier 2 rules. The ACCC writes people 'Given Family' in mixed case, never 'LAST, GIVEN'."""
    return classify_party(name, comma_person_format=False)


@registry.register
class AcccNoticeAdapter(SourceAdapter):
    source_id: ClassVar[str] = "accc_notice"
    tier: ClassVar[int] = 3
    licence: ClassVar[str] = "CC BY 4.0"
    description: ClassVar[str] = "ACCC infringement notices register (accc.gov.au, cached HTML)"
    adapter_version: ClassVar[str] = "accc_notice/1"

    # ------------------------------------------------------------------ parse

    def parse(self, path: Path) -> Iterator[RawRow]:
        """`path` is one cached entry page, one field extract (``extract_*.txt``), or a
        directory holding either (``notices/*.html`` and/or ``extract_*.txt``).

        Listing pages (``listing/``) are not records; they only feed the collector.
        A slug present in both an extract and a cached page is yielded once (extract wins)."""
        path = Path(path)
        if path.is_dir():
            extracts = sorted(path.rglob("extract_*.txt"))
            pages = sorted(p for p in path.rglob("*.html") if "listing" not in p.parts)
        elif path.suffix.lower() == ".txt":
            extracts, pages = [path], []
        else:
            extracts, pages = [], [path]
        seen: set[str] = set()
        for f in extracts:
            for row in parse_extract(f):
                seen.add(row["slug"])
                yield row
        for f in pages:
            raw = f.read_bytes()
            if not raw.strip():
                continue
            row = self.extract(raw, file_name=f.name)
            if (_slug(row.get("url")) or f.stem) in seen:
                continue
            yield row

    def extract(self, raw: bytes | str, file_name: str = "") -> RawRow:
        doc = lxml_html.fromstring(raw)
        for bad in doc.xpath("//script|//style|//nav|//header|//footer|//noscript"):
            bad.drop_tree()
        url = (
            _first(doc.xpath("//link[@rel='canonical']/@href"))
            or _first(doc.xpath("//meta[@property='og:url']/@content"))
        )
        main = next(
            (el for el in (_first(doc.xpath("//main")), _first(doc.xpath("//article"))) if el is not None),
            doc,
        )
        fields = _labelled_fields(main)
        paragraphs = [clean(p.text_content()) for p in main.xpath(".//p")]
        return {
            "file": file_name,
            "url": clean(url) or None,
            "title": clean(_first(doc.xpath("//h1//text()")) or ""),
            "fields": fields,
            "times": [clean(t) for t in main.xpath(".//time/@datetime")],
            "paragraphs": [p for p in paragraphs if p],
            "text": clean(main.text_content()),
        }

    # ------------------------------------------------------------------ map

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        if row.get("format") == "extract":
            return self._extract_record(row, snapshot_date)
        url = row.get("url")
        record_id = _slug(url) or Path(row.get("file") or "").stem
        if not record_id:
            raise RejectRecord("missing_record_id")
        fields: dict[str, str] = row.get("fields") or {}
        text: str = row.get("text") or ""

        party_field = _field(fields, _PARTY_LABELS)
        title = row.get("title") or ""
        recipient = party_field or _TITLE_NOISE.sub("", title).strip()
        if not recipient:
            raise RejectRecord("missing_recipient")
        parties = []
        for name in split_parties(recipient):
            ptype, basis = party_type_hint(name)
            parties.append({"name": name, "party_type": ptype.value, "party_type_basis": basis})

        payload: dict[str, Any] = {
            "register": "ACCC infringement notices register",
            "url": url,
            "title": title or None,
            "recipient_as_stated": recipient,
            "parties": parties,
            "multi_party": len(parties) > 1,
        }

        issued = _parse_date(_field(fields, _DATE_LABELS))
        if issued is None:
            issued = next((d for d in map(_parse_date, row.get("times") or []) if d), None)
        if issued is None:
            m = _DATE_TEXT.search(text)
            issued = _parse_date(m.group(1)) if m else None
        payload["date_issued"] = issued.isoformat() if issued else None

        self._amounts(payload, fields, row.get("paragraphs") or [], text)

        leg_field = _field(fields, _LEG_LABELS)
        legislation = [leg_field] if leg_field else []
        for m in _LEGISLATION.finditer(text):
            name = _LEGISLATION_STOP.sub("", m.group(1)).strip()
            if name and name not in legislation:
                legislation.append(name)
        payload["legislation"] = legislation
        paras = row.get("paragraphs") or []
        payload["description"] = paras[0] if paras else None

        ids = self._identifiers(text, parties, payload)
        first = parties[0]
        norm = self.names.normalise(first["name"])
        return SourceRecord(
            source=self.source_id,
            record_id=record_id,
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=first["name"],
            name_norm=norm.norm if norm else None,
            party_type=PartyType(first["party_type"]),
            identifiers=tuple(ids),
        )

    def _extract_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        """A line of the field extract. Real entry pages state no penalty amount, so the
        penalty fields stay None (no guessing); identifiers come only from the stated
        `abn` / `acn` fields, never from free text and never derived from each other."""
        slug = row["slug"]
        f: dict[str, str] = row["fields"]
        name = clean(f.get("name")) or clean(f.get("list_title"))
        if not name:
            raise RejectRecord("missing_recipient")
        ptype, basis = party_type_hint(name)
        title = clean(f.get("list_title")) or None
        trading_as = None
        if title:
            m = _TRADING_AS.search(title)
            trading_as = (clean(title[m.end():]) or None) if m else None
        numbers = split_notice_numbers(f.get("infringe-number"))
        section = clean(f.get("infringe-section")) or None
        issued = _parse_date(f.get("infringe-date-paid"))
        payload: dict[str, Any] = {
            "register": "ACCC infringement notices register",
            "input_format": "field_extract",
            "url": f"{REGISTER_URL}/{slug}",
            "title": title,
            "recipient_as_stated": name,
            "trading_as": trading_as,
            "parties": [{"name": name, "party_type": ptype.value, "party_type_basis": basis}],
            "multi_party": False,
            "date_paid": issued.isoformat() if issued else None,
            # The register's only date is the date the notice was PAID; kept under the
            # common key too so HTML and extract records query the same way.
            "date_issued": issued.isoformat() if issued else None,
            "date_raw": clean(f.get("infringe-date-paid")) or None,
            "infringement_numbers": numbers,
            "notice_count": len(numbers) or None,
            "section": section,
            "legislation": [m.group(1).strip()] if section and (m := _OF_THE.search(section)) else [],
            "reference_number": clean(f.get("reference-number")) or None,
            # e.g. 'Sociedad unipersonal con CIF B-61965778': a foreign tax id, never an identifier.
            "reference_kind": (
                "foreign_tax_id"
                if _FOREIGN_TAX_ID.search(f.get("reference-number") or "")
                else ("other" if f.get("reference-number") else None)
            ),
            "penalty_amounts_aud": [],
            "penalty_total_aud": None,
            "penalty_total_basis": "not_stated_on_register",
            "description": None,
        }

        ids: list[Identifier] = []
        stated: list[dict[str, Any]] = []
        for scheme, validator in (("abn", _ABN), ("acn", _ACN)):
            raw = clean(f.get(scheme))
            if not raw:
                continue
            digits = re.sub(r"\D", "", raw)
            ident = validator.parse(digits)
            entry: dict[str, Any] = {"scheme": scheme, "raw": raw, "valid": ident is not None}
            if ident is not None:
                guard = acn_guard(name) if scheme == "acn" else None
                if guard is None:
                    ids.append(ident)
                else:
                    entry["withheld_reason"] = guard
            stated.append(entry)
        payload["identifiers_stated"] = stated
        if stated and len(ids) == 2:
            abn, acn = (i.value for i in ids)
            payload["abn_acn_consistent"] = abn[2:] == acn

        norm = self.names.normalise(name)
        return SourceRecord(
            source=self.source_id,
            record_id=slug,
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=name,
            name_norm=norm.norm if norm else None,
            party_type=ptype,
            identifiers=tuple(ids),
        )

    @staticmethod
    def _amounts(payload: dict[str, Any], fields: dict[str, str], paragraphs: list[str], text: str) -> None:
        amounts: list[Decimal] = []
        total: Decimal | None = None
        each = False
        amount_field = _field(fields, _AMOUNT_LABELS)
        sentences = ([amount_field] if amount_field else []) + [
            s for p in paragraphs for s in re.split(r"(?<=[.;])\s+", p)
        ]
        if not sentences:
            sentences = re.split(r"(?<=[.;])\s+", text)
        for s in sentences:
            if not (_MONEY_CONTEXT.search(s) or s is amount_field):
                continue
            for m in _MONEY.finditer(s):
                v = _money(m)
                if v is None:
                    continue
                window = s[max(0, m.start() - 40): m.end() + 40]
                if _TOTAL_CONTEXT.search(window) and total is None:
                    total = v
                elif v not in amounts:
                    amounts.append(v)
                if _EACH_CONTEXT.search(window):
                    each = True
        counts = [
            int(c) if c.isdigit() else _NUMBER_WORDS[c.lower()]
            for c in (m.group(1) for m in _NOTICE_COUNT.finditer(text))
        ]
        notice_count = max(counts) if counts else None
        basis = None
        if total is not None:
            basis = "stated_total"
        elif len(amounts) == 1 and each and notice_count:
            total, basis = amounts[0] * notice_count, "per_notice_times_count"
        elif len(amounts) == 1:
            total, basis = amounts[0], "single_amount"
        elif amounts:
            basis = "ambiguous_multiple_amounts"
        payload["penalty_amounts_aud"] = [str(a) for a in amounts]
        payload["notice_count"] = notice_count
        payload["penalty_total_aud"] = str(total) if total is not None else None
        payload["penalty_total_basis"] = basis or "no_amount_stated"

    @staticmethod
    def _identifiers(text: str, parties: list[dict[str, Any]], payload: dict[str, Any]) -> list[Identifier]:
        """Only identifiers the page states, checksum-valid; an ACN also needs the legal-form guard
        on the (single) party it would belong to. Multi-party pages keep them in the payload only."""
        out: list[Identifier] = []
        stated: list[dict[str, Any]] = []
        for m in _ID.finditer(text):
            scheme, digits = m.group(1).upper(), re.sub(r"\D", "", m.group(2))
            ident = _ABN.parse(digits) if scheme == "ABN" else _ACN.parse(digits)
            entry: dict[str, Any] = {"scheme": scheme.lower(), "raw": digits, "valid": ident is not None}
            if ident is not None and len(parties) == 1:
                guard = acn_guard(parties[0]["name"]) if scheme == "ACN" else None
                if guard is None:
                    out.append(ident)
                else:
                    entry["withheld_reason"] = guard
            elif ident is not None:
                entry["withheld_reason"] = "multi_party_page"
            stated.append(entry)
        payload["identifiers_stated"] = stated
        seen: set[Identifier] = set()
        return [i for i in out if not (i in seen or seen.add(i))]


# ---------------------------------------------------------------------- helpers


_TRADING_AS = re.compile(r"\s+(?:trading\s+as|t/as|t/a)\s+", re.I)
_OF_THE = re.compile(r"\bof\s+the\s+(.+)$", re.I)
_FOREIGN_TAX_ID = re.compile(r"\b(?:CIF|NIF|VAT|EIN|TIN)\b")
_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def split_notice_numbers(value: str | None) -> list[str]:
    """'2627/05, 2627/06 and 2627/09' -> ['2627/05', '2627/06', '2627/09']."""
    parts = re.split(r"\s*,\s*|\s+and\s+|\s*;\s*", clean(value))
    return [p for p in (clean(x) for x in parts) if p]


def parse_extract(path: Path) -> Iterator[RawRow]:
    """Field extract: '#' header lines, then one notice per line 'slug|field=value|...'.

    Values are as displayed on the entry page (Drupal ``field--name-field-acccgov-*``)."""
    with Path(path).open(encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            slug, *pairs = line.split("|")
            slug = slug.strip()
            if not _SLUG_OK.match(slug):
                raise ValueError(f"{path}:{line_no}: bad slug {slug!r}")
            fields: dict[str, str] = {}
            for pair in pairs:
                key, sep, value = pair.partition("=")
                if sep:
                    fields[key.strip()] = value.strip()
            yield {"format": "extract", "file": Path(path).name, "line": line_no, "slug": slug, "fields": fields}


def _first(xs: list[Any]) -> Any:
    return xs[0] if xs else None


def _slug(url: str | None) -> str | None:
    if not url:
        return None
    path = re.sub(r"[?#].*$", "", url).rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    return slug or None


def _labelled_fields(root: Any) -> dict[str, str]:
    """label (lower case, no trailing colon) -> value, from the common Drupal / HTML patterns."""
    out: dict[str, str] = {}

    def put(label: str, value: str) -> None:
        k = clean(label).rstrip(":").strip().lower()
        v = clean(value)
        if k and v and k not in out and len(k) <= 40:
            out[k] = v

    for dt in root.xpath(".//dt"):
        dd = _first(dt.xpath("following-sibling::dd[1]"))
        if dd is not None:
            put(dt.text_content(), dd.text_content())
    for fld in root.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' field ')]"):
        label = _first(fld.xpath(".//*[contains(@class, 'field__label')]"))
        item = _first(fld.xpath(".//*[contains(@class, 'field__item')]"))
        if label is not None and item is not None:
            put(label.text_content(), item.text_content())
    for tr in root.xpath(".//tr"):
        cells = tr.xpath("./th|./td")
        if len(cells) == 2:
            put(cells[0].text_content(), cells[1].text_content())
    for el in root.xpath(".//p|.//li"):
        t = clean(el.text_content())
        m = re.match(r"^([A-Za-z][A-Za-z ]{1,38}):\s+(.+)$", t)
        if m:
            put(m.group(1), m.group(2))
    return out


def _field(fields: dict[str, str], labels: tuple[str, ...]) -> str | None:
    for label in labels:
        if label in fields:
            return fields[label]
    return None
