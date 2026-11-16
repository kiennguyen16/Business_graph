"""Synthetic canonical-store builder for the independent resolution tests.

Builds party_canonical / identifier / alias rows the way the canonical build does
(name_norm from NameNormaliser; persons via normalise_person), with checksum-valid
synthetic identifiers. Small stores only (memory-limited machine).
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from datetime import date

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.normalise.identifiers import AbnValidator, AcnValidator, LeiValidator
from bizgraph.normalise.names import NameNormaliser
from bizgraph.store.duckdb_store import DuckDBStore

NORM = NameNormaliser()
_ACN_W = (8, 7, 6, 5, 4, 3, 2, 1)


def make_acn(n: int) -> str:
    body = f"{n:08d}"[-8:]
    total = sum(int(c) * w for c, w in zip(body, _ACN_W))
    acn = body + str((10 - total % 10) % 10)
    assert AcnValidator().is_valid(acn)
    return acn


def abn_from_acn(acn: str) -> str:
    for p in range(10, 100):
        abn = f"{p}{acn}"
        if AbnValidator().is_valid(abn):
            return abn
    raise AssertionError("no ABN prefix")  # pragma: no cover


def make_abn(n: int) -> str:
    return abn_from_acn(make_acn(n))


def bad_abn(n: int) -> str:
    """11 digits that fail the ABN checksum."""
    good = make_abn(n)
    last = (int(good[-1]) + 1) % 10
    cand = good[:-1] + str(last)
    assert not AbnValidator().is_valid(cand)
    return cand


def make_lei(n: int) -> str:
    base = f"5493{n:014d}"[:18]
    numeric = "".join(str(int(c, 36)) for c in base + "00")
    check = 98 - int(numeric) % 97
    lei = base + f"{check:02d}"
    assert LeiValidator().is_valid(lei)
    return lei


@dataclass
class P:
    key: str
    name: str
    party_type: str = "organisation"
    abn: str | None = None
    acn: str | None = None
    lei: str | None = None
    state: str | None = None
    quarantined: bool = False
    ids: list[tuple[str, str]] = field(default_factory=list)  # extra identifier rows (scheme, value)
    aliases: list[tuple[str, str]] = field(default_factory=list)  # (alias, alias_type)


def norm_of(name: str, party_type: str) -> str:
    n = NORM.normalise_person(name) if party_type == "person" else NORM.normalise(name)
    return n.norm if n else ""


def new_store(path: str = ":memory:") -> DuckDBStore:
    s = DuckDBStore(path)
    s.con.execute("SET memory_limit='1GB'")
    s.con.execute("SET threads=2")
    return s


def load_parties(store: DuckDBStore, parties: list[P]) -> None:
    con = store.con
    prow, irow, arow = [], [], []
    for p in parties:
        prow.append((p.key, p.party_type, p.name, norm_of(p.name, p.party_type), p.abn, p.acn, p.lei,
                     p.state, p.quarantined, "abr", p.key))
        seen = set()
        for scheme, value in ([("abn", p.abn)] if p.abn else []) + ([("acn", p.acn)] if p.acn else []) + (
                [("lei", p.lei)] if p.lei else []) + p.ids:
            if (scheme, value) not in seen:
                seen.add((scheme, value))
                irow.append((p.key, scheme, value))
        for alias, atype in p.aliases:
            n = NORM.normalise(alias)
            arow.append((p.key, alias, n.norm if n else None, atype, "abr", p.key))
    con.executemany(
        """INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, abn, acn, lei, state,
                                        quarantined, source, record_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        prow,
    )
    if irow:
        con.executemany("INSERT OR IGNORE INTO identifier VALUES (?,?,?)", irow)
    if arow:
        con.executemany("INSERT INTO alias VALUES (?,?,?,?,?,?)", arow)


def record(source: str, rid: str, name: str | None, ptype: PartyType = PartyType.ORGANISATION,
           ids: tuple[Identifier, ...] = (), **payload) -> SourceRecord:
    nn = None
    if name:
        n = NORM.normalise_person(name) if ptype is PartyType.PERSON else NORM.normalise(name)
        nn = n.norm if n else None
    return SourceRecord(source=source, record_id=rid, snapshot_date=date(2026, 11, 1),
                        payload={"name": name, **payload}, name_raw=name, name_norm=nn,
                        party_type=ptype, identifiers=ids)


# --------------------------------------------------------------------------- scenario store

SURNAMES = ["SMITH", "JONES", "WILLIAMS", "BROWN", "TAYLOR", "WILSON", "NGUYEN", "WHITE", "MARTIN",
            "ANDERSON", "THOMPSON", "WALKER", "HARRIS", "LEE", "RYAN", "ROBINSON", "KELLY", "KING"]
WORDS = ["PLUMBING", "ELECTRICAL", "ROOFING", "BAKERY", "MOTORS", "TIMBER", "LOGISTICS", "DENTAL", "LEGAL",
         "PHARMACY", "BUILDERS", "CONCRETE", "CARPENTRY", "PAINTING", "LANDSCAPING", "TRANSPORT", "FREIGHT",
         "MEDICAL", "ENGINEERING", "MARINE", "AVIATION", "PROPERTY", "REALTY", "FOODS", "DAIRY", "WINES",
         "BREWING", "TEXTILES", "PRINTING", "SECURITY", "CLEANING", "GARDENS", "POOLS", "FENCING", "GLASS",
         "STEEL", "MINING", "ENERGY", "SOLAR", "WATER", "TILES", "FLOORING", "KITCHENS", "CABINETS"]
PLACES = ["BONDI", "PARRAMATTA", "GEELONG", "BALLARAT", "TOWNSVILLE", "CAIRNS", "FREMANTLE", "HOBART",
          "LAUNCESTON", "DARWIN", "WOLLONGONG", "NEWCASTLE", "BENDIGO", "MILDURA", "TOOWOOMBA", "BUNBURY",
          "ALBANY", "DUBBO", "ORANGE", "BATHURST", "TAMWORTH", "ARMIDALE", "LISMORE", "MACKAY", "GLADSTONE"]
COINED = ["ZENTRIX", "QUORVA", "BLUEGUM", "IRONBARK", "WATTLEBIRD", "KOOKABURRA", "SILVERGULL", "REDGUM",
          "MULGA", "BRIGALOW", "COOLABAH", "YARRAWOOD", "JARRAH", "KARRI", "TUART", "MARRI", "BANKSIA",
          "GREVILLEA", "BORONIA", "CORREA", "ACACIA", "HAKEA", "WARATAH", "LILLYPILLY", "TELOPEA"]
STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]
FORMS = ["PTY LTD", "PTY LTD", "PTY LTD", "PROPRIETARY LIMITED", "LIMITED", "PTY. LTD."]


def scenario_parties() -> list[P]:
    """Hand-built traps around famous names."""
    ps: list[P] = []
    n = itertools.count(100_000)

    def add(key, name, **kw):
        acn = make_acn(next(n))
        kw.setdefault("acn", acn)
        kw.setdefault("abn", abn_from_acn(acn))
        ps.append(P(key, name, **kw))

    add("cba", "COMMONWEALTH BANK OF AUSTRALIA", state="NSW", lei=make_lei(1),
        aliases=[("COMMBANK", "trading_name")])
    add("csc", "COMMONWEALTH SUPERANNUATION CORPORATION", state="ACT")
    add("cbf", "COMMONWEALTH SECURITIES LIMITED", state="NSW")
    add("wbc", "WESTPAC BANKING CORPORATION", state="NSW")
    add("wsec", "WESTPAC SECURITIES LIMITED", state="NSW")
    add("amp", "AMP LIMITED", state="NSW")
    add("ampcap", "AMP CAPITAL INVESTORS LIMITED", state="NSW")
    add("anz", "AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED", state="VIC", aliases=[("ANZ", "trading_name")])
    add("nab", "NATIONAL AUSTRALIA BANK LIMITED", state="VIC")
    add("acme_pty", "ACME PTY LTD", state="NSW")
    add("acme_ltd", "ACME LIMITED", state="VIC")
    add("smith_pty", "SMITH PTY LTD", state="QLD")
    for i, w in enumerate(WORDS[:30]):
        add(f"smith_{i}", f"SMITH {w} PTY LTD", state=STATES[i % 8])
    add("bluegum_trust", "THE TRUSTEE FOR BLUEGUM FAMILY TRUST", state="WA")
    add("bluegum_pty", "BLUEGUM PTY LTD", state="WA")
    add("ironbark_nsw", "IRONBARK CONSTRUCTIONS PTY LTD", state="NSW")
    add("ironbark_qld", "IRONBARK CONSTRUCTIONS PTY LTD", state="QLD")
    add("jones_co", "JONES & CO PTY LTD", state="SA")
    add("joneshire", "JONES HIRE PTY LTD", state="SA")
    add("redgum", "REDGUM WINES PTY LTD", state="SA", aliases=[("REDGUM CELLARS", "business_name")])
    add("johnsmith_pty", "JOHN SMITH PTY LTD", state="NSW")
    ps.append(P("person_js", "SMITH, JOHN", party_type="person", state="NSW", abn=None, acn=None))
    add("quar", "ZENTRIX ANALYTICS PTY LTD", state="VIC", quarantined=True)
    add("twin_a", "QUORVA TRADING PTY LTD", state="NSW")
    add("twin_b", "QUORVA TRADERS PTY LTD", state="NSW")
    # ARSN-carrying scheme and an ARBN foreign company
    add("scheme", "KARRI GROWTH FUND", acn=None, abn=None, ids=[("arsn", make_acn(777_001))])
    add("foreign", "TUART HOLDINGS INC", acn=None, abn=None, ids=[("arbn", make_acn(777_002))])
    # AFSL holders: licence moved from old holder to new holder (both still carry the number in identifier?)
    add("afsl_old", "MARRI FINANCIAL PLANNING PTY LTD", ids=[("afsl", "234567")])
    add("afsl_new", "BANKSIA WEALTH PTY LTD")
    # LEI duplicate case: entity with two LEIs
    add("lei_ent", "GREVILLEA RESOURCES LIMITED", lei=make_lei(2))
    return ps


def bulk_parties(n: int, seed: int = 7) -> list[P]:
    """n synthetic organisations with realistic near-name neighbourhoods."""
    rng = random.Random(seed)
    out: list[P] = []
    seen: set[str] = set()
    i = 0
    while len(out) < n:
        i += 1
        shape = rng.random()
        if shape < 0.35:
            base = f"{rng.choice(SURNAMES)} {rng.choice(WORDS)}"
        elif shape < 0.6:
            base = f"{rng.choice(PLACES)} {rng.choice(WORDS)}"
        elif shape < 0.8:
            base = f"{rng.choice(COINED)} {rng.choice(WORDS)} {rng.choice(['SERVICES', 'GROUP', 'SOLUTIONS', 'HOLDINGS', ''])}".strip()
        else:
            base = f"{rng.choice(SURNAMES)} {rng.choice(PLACES)} {rng.choice(WORDS)}"
        form = rng.choice(FORMS)
        name = f"{base} {form}"
        state = rng.choice(STATES)
        key_name = (norm_of(name, "organisation"), state)
        if key_name in seen:
            continue
        seen.add(key_name)
        acn = make_acn(1_000_000 + i)
        out.append(P(f"b{i}", name, abn=abn_from_acn(acn), acn=acn, state=state))
    return out
