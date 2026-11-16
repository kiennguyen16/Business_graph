"""Traversal and projection services on a synthetic graph (no Fuseki needed).

The same SPARQL the services send to Fuseki runs here over an rdflib Dataset with a union
default graph (`LocalEndpoint`). The fixture has: an ownership cycle A->B->C->A, a 6-deep
chain, a node with a majority parent, a node with two parents and no percentages, a
parent change over time, a GLEIF ULTIMATE edge that disagrees, linked parties with
licences, a ban, a shareholding and a trusteeship (for the 2-hop question), ACCC notices,
and a DuckDB side with licence_event, link and party_canonical rows.
"""

from __future__ import annotations

from datetime import date

import pytest

from bizgraph.config import REPO_ROOT
from bizgraph.pipeline.licence_history import LICENCE_EVENT_DDL
from bizgraph.services.endpoint import LocalEndpoint
from bizgraph.services.projection import (
    NAMED_SPECS,
    CriteriaSpec,
    ProjectionService,
    TimeWindow,
    load_spec,
    write_projection,
)
from bizgraph.services.traversal import (
    OwnershipEdge,
    TraversalBudget,
    TraversalService,
    choose_parent,
)
from bizgraph.store.duckdb_store import DuckDBStore

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")  # rdflib Dataset internals

BG = "https://w3id.org/bizgraph/ont#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PROV = "http://www.w3.org/ns/prov#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LINKS = "urn:graph:links:test-v1"
G_L1 = "urn:graph:source:gleif_l1:2026-11-01"
G_L2 = "urn:graph:source:gleif_l2:2026-11-01"
G_AFSL = "urn:graph:source:asic_afsl:2026-11-01"
G_BAN = "urn:graph:source:asic_banned_org:2026-11-01"
G_SH = "urn:graph:source:shareholding:2026-11-01"
G_ACCC = "urn:graph:source:accc_notice:2026-11-01"
CANON = "urn:graph:canonical"
AS_OF = date(2026, 11, 17)


def lei(tag: str) -> str:
    """A pattern-valid LEI: 18 alphanumerics + 2 digits."""
    return (tag.upper() + "X" * 18)[:18] + "00"


def rec(tag: str) -> str:
    return f"urn:src:gleif_l1:{lei(tag)}"


class NT:
    def __init__(self) -> None:
        self.graphs: dict[str, list[str]] = {}

    def add(self, g: str, s: str, p: str, o: str) -> None:
        self.graphs.setdefault(g, []).append(f"{s} {p} {o} .")

    @staticmethod
    def i(x: str) -> str:
        return f"<{x}>"

    @staticmethod
    def bg(x: str) -> str:
        return f"<{BG}{x}>"

    @staticmethod
    def s(x: str) -> str:
        return '"' + x.replace('"', '\\"') + '"'

    @staticmethod
    def d(x: str) -> str:
        return f'"{x}"^^<{XSD}date>'

    @staticmethod
    def dec(x: float) -> str:
        return f'"{x}"^^<{XSD}decimal>'


def build_graph() -> LocalEndpoint:
    nt = NT()
    i, b, s, d = nt.i, nt.bg, nt.s, nt.d

    def l1(tag: str, name: str, acn: str | None = None) -> None:
        r = i(rec(tag))
        nt.add(G_L1, r, i(RDF_TYPE), b("SourceRecord"))
        nt.add(G_L1, r, b("sourceId"), s("gleif_l1"))
        nt.add(G_L1, r, b("nameRaw"), s(name))
        nt.add(G_L1, r, b("lei"), s(lei(tag)))
        if acn:
            nt.add(G_L1, r, b("acn"), s(acn))

    def own(child: str, parent: str, kind: str = "IS_DIRECTLY_CONSOLIDATED_BY", pct: float | None = None,
            vfrom: str | None = None, vto: str | None = None, n: int = 0) -> str:
        f = f"urn:fact:gleif_l2:{lei(child)}%7C{kind}%7C{lei(parent)}{'-' + str(n) if n else ''}"
        src = f"urn:src:gleif_l2:{lei(child)}%7C{kind}%7C{lei(parent)}"
        nt.add(G_L2, i(f), i(RDF_TYPE), b("Ownership"))
        nt.add(G_L2, i(f), b("relationshipKind"), b(kind))
        nt.add(G_L2, i(f), b("relationshipStatus"), s("ACTIVE"))
        nt.add(G_L2, i(f), b("aboutRecord"), i(rec(child)))
        nt.add(G_L2, i(f), b("counterpartyRecord"), i(rec(parent)))
        nt.add(G_L2, i(f), f"<{PROV}wasDerivedFrom>", i(src))
        if pct is not None:
            nt.add(G_L2, i(f), b("ownershipPercentage"), nt.dec(pct))
        if vfrom:
            nt.add(G_L2, i(f), b("validFrom"), d(vfrom))
        if vto:
            nt.add(G_L2, i(f), b("validTo"), d(vto))
        return f

    def party(iri: str, name: str, lei_v: str | None = None, abn: str | None = None) -> None:
        nt.add(CANON, i(iri), i(RDF_TYPE), b("Organisation"))
        nt.add(CANON, i(iri), b("name"), s(name))
        if lei_v:
            nt.add(CANON, i(iri), b("lei"), s(lei_v))
        if abn:
            nt.add(CANON, i(iri), b("abn"), s(abn))

    def link(src: str, record: str, party_iri: str, mt: str = "EXACT_ABN", conf: float = 1.0) -> None:
        lk = f"urn:link:test-v1:{src}:{record.rsplit(':', 1)[1]}"
        nt.add(LINKS, i(lk), i(RDF_TYPE), b("Link"))
        nt.add(LINKS, i(lk), b("sourceRecord"), i(record))
        nt.add(LINKS, i(lk), b("party"), i(party_iri))
        nt.add(LINKS, i(lk), b("matchType"), b(mt))
        nt.add(LINKS, i(lk), b("confidence"), nt.dec(conf))
        nt.add(LINKS, i(lk), b("matcherVersion"), s("test-v1"))

    # --- cycle A -> B -> C -> A
    for t in ("A", "B", "C"):
        l1(t, f"CYCLE {t} LTD")
    own("A", "B"), own("B", "C"), own("C", "A")
    # --- chain D1 -> ... -> D6, with a GLEIF ULTIMATE edge from D1 to an unrelated entity
    for k in range(1, 7):
        l1(f"D{k}", f"DEEP {k} LTD")
    for k in range(1, 6):
        own(f"D{k}", f"D{k + 1}")
    l1("ELSEWHERE", "ELSEWHERE HOLDINGS")
    own("D1", "ELSEWHERE", kind="IS_ULTIMATELY_CONSOLIDATED_BY")
    # --- multiple parents: majority (M) and ambiguous (N)
    for t in ("M", "MP1", "MP2", "N", "NP1", "NP2"):
        l1(t, f"MULTI {t} LTD")
    own("M", "MP1", pct=60), own("M", "MP2", pct=30)
    own("N", "NP1"), own("N", "NP2")
    # --- parent changes over time
    for t in ("V", "POLD", "PNEW"):
        l1(t, f"TIME {t} LTD")
    own("V", "POLD", vfrom="2000-01-01", vto="2010-12-31")
    own("V", "PNEW", vfrom="2011-01-01")
    # --- linked parties: X (urn:abn:111) owned by XP (urn:abn:222)
    l1("X", "X RECORD NAME")
    l1("XP", "XP RECORD NAME")
    nt.add(G_L1, i(rec("XP")), b("country"), s("GB"))
    fx = own("X", "XP", pct=100)
    own("X", "XP", kind="IS_ULTIMATELY_CONSOLIDATED_BY")
    party("urn:abn:11111111111", "X CANONICAL PTY LTD", lei("X"), "11111111111")
    party("urn:abn:22222222222", "XP CANONICAL LIMITED", lei("XP"), "22222222222")
    link("gleif_l1", rec("X"), "urn:abn:11111111111", "EXACT_LEI")
    link("gleif_l1", rec("XP"), "urn:abn:22222222222", "EXACT_LEI")
    nt.add(LINKS, i(fx), b("owned"), i("urn:abn:11111111111"))
    nt.add(LINKS, i(fx), b("owner"), i("urn:abn:22222222222"))

    # --- five licences on party X: three active, two historical
    for k, (vfrom, vto) in enumerate([("2020-01-01", None), ("2024-01-01", None), ("2022-01-01", None),
                                      ("2001-01-01", "2010-01-01"), ("2011-01-01", "2015-01-01")], start=1):
        r = f"urn:src:asic_afsl:{1000 + k}"
        f = f"urn:fact:asic_afsl:{1000 + k}"
        nt.add(G_AFSL, i(r), i(RDF_TYPE), b("SourceRecord"))
        nt.add(G_AFSL, i(r), b("sourceId"), s("asic_afsl"))
        nt.add(G_AFSL, i(r), b("nameRaw"), s("X CANONICAL PTY LTD"))
        nt.add(G_AFSL, i(f), i(RDF_TYPE), b("Licence"))
        nt.add(G_AFSL, i(f), b("licenceKind"), b("AFSL"))
        nt.add(G_AFSL, i(f), b("licenceNumber"), s(str(1000 + k)))
        nt.add(G_AFSL, i(f), b("aboutRecord"), i(r))
        nt.add(G_AFSL, i(f), b("validFrom"), d(vfrom))
        if vto:
            nt.add(G_AFSL, i(f), b("validTo"), d(vto))
        link("asic_afsl", r, "urn:abn:11111111111")
        nt.add(LINKS, i(f), b("licensee"), i("urn:abn:11111111111"))

    # --- identifier equality: Q's ACN is on exactly one party, R's ACN on two
    l1("Q", "Q RECORD", acn="999000111")
    l1("R", "R RECORD", acn="999000222")
    party("urn:acn:999000111", "Q CANONICAL PTY LTD")
    nt.add(CANON, i("urn:acn:999000111"), b("acn"), s("999000111"))
    for k in ("urn:acn:999000222", "urn:party:r-duplicate"):
        party(k, "R CANONICAL PTY LTD")
        nt.add(CANON, i(k), b("acn"), s("999000222"))

    # --- 2-hop question: banned party 333, owned by 444 (shareholding), 444 trustee of trust 555
    party("urn:abn:33333333333", "BANNED CO PTY LTD", abn="33333333333")
    party("urn:abn:44444444444", "HOLDCO PTY LTD", abn="44444444444")
    party("urn:abn:55555555555", "THE FAMILY TRUST", abn="55555555555")
    party("urn:abn:66666666666", "FAR AWAY PTY LTD", abn="66666666666")
    br, bf = "urn:src:asic_banned_org:333", "urn:fact:asic_banned_org:333"
    nt.add(G_BAN, i(br), i(RDF_TYPE), b("SourceRecord"))
    nt.add(G_BAN, i(br), b("sourceId"), s("asic_banned_org"))
    nt.add(G_BAN, i(br), b("nameRaw"), s("BANNED CO PTY LTD"))
    nt.add(G_BAN, i(bf), i(RDF_TYPE), b("Ban"))
    nt.add(G_BAN, i(bf), b("aboutRecord"), i(br))
    nt.add(G_BAN, i(bf), b("validFrom"), d("2020-01-01"))
    link("asic_banned_org", br, "urn:abn:33333333333", "EXACT_ACN")
    nt.add(LINKS, i(bf), b("bannedParty"), i("urn:abn:33333333333"))
    sh = "urn:fact:shareholding:333-444"
    nt.add(G_SH, i(sh), i(RDF_TYPE), b("Ownership"))
    nt.add(G_SH, i(sh), b("relationshipKind"), b("SHAREHOLDING"))
    nt.add(G_SH, i(sh), b("ownershipPercentage"), nt.dec(80))
    nt.add(LINKS, i(sh), b("owned"), i("urn:abn:33333333333"))
    nt.add(LINKS, i(sh), b("owner"), i("urn:abn:44444444444"))
    tr = "urn:fact:gleif_l1:TRUST:trustee"
    nt.add(G_L1, i(tr), i(RDF_TYPE), b("Trusteeship"))
    nt.add(G_L1, i(tr), b("relationshipKind"), b("HAS_TRUSTEE"))
    nt.add(LINKS, i(tr), b("trust"), i("urn:abn:55555555555"))
    nt.add(LINKS, i(tr), b("trustee"), i("urn:abn:44444444444"))
    sh2 = "urn:fact:shareholding:555-666"  # 3 hops from the banned party: must not appear at hops=2
    nt.add(G_SH, i(sh2), i(RDF_TYPE), b("Ownership"))
    nt.add(G_SH, i(sh2), b("relationshipKind"), b("SHAREHOLDING"))
    nt.add(LINKS, i(sh2), b("owned"), i("urn:abn:66666666666"))
    nt.add(LINKS, i(sh2), b("owner"), i("urn:abn:55555555555"))

    # --- ACCC notices for the projection
    party("urn:abn:77777777777", "SEVEN PTY LTD", abn="77777777777")
    party("urn:abn:88888888888", "EIGHT PTY LTD", abn="88888888888")
    for tag, who, when, conf in (("n1", "urn:abn:11111111111", "2026-06-01", 1.0),
                                 ("n6", "urn:abn:66666666666", "2025-01-01", 1.0),
                                 ("n7", "urn:abn:77777777777", "2024-03-03", 0.7)):
        r, f = f"urn:src:accc_notice:{tag}", f"urn:fact:accc_notice:{tag}"
        nt.add(G_ACCC, i(r), i(RDF_TYPE), b("SourceRecord"))
        nt.add(G_ACCC, i(r), b("sourceId"), s("accc_notice"))
        nt.add(G_ACCC, i(f), i(RDF_TYPE), b("InfringementNotice"))
        nt.add(G_ACCC, i(f), b("aboutRecord"), i(r))
        nt.add(G_ACCC, i(f), b("validFrom"), d(when))
        nt.add(G_ACCC, i(f), b("validTo"), d(when))
        nt.add(G_ACCC, i(f), b("amountAud"), nt.dec(13200))
        link("accc_notice", r, who, "NAME_NORMALISED_EXACT", conf)
        nt.add(LINKS, i(f), b("noticeRecipient"), i(who))

    ep = LocalEndpoint()
    for g, lines in nt.graphs.items():
        ep.add_ntriples(g, "\n".join(lines) + "\n")
    ep.add_file("urn:graph:ontology", REPO_ROOT / "ontology" / "schema.ttl")
    return ep


@pytest.fixture(scope="module")
def ep() -> LocalEndpoint:
    return build_graph()


@pytest.fixture()
def svc(ep: LocalEndpoint) -> TraversalService:
    return TraversalService(ep)


@pytest.fixture()
def store():
    st = DuckDBStore(":memory:")
    st.con.execute(LICENCE_EVENT_DDL)
    parties = [("urn:abn:11111111111", "X CANONICAL PTY LTD", "11111111111"),
               ("urn:abn:66666666666", "FAR AWAY PTY LTD", "66666666666"),
               ("urn:abn:77777777777", "SEVEN PTY LTD", "77777777777"),
               ("urn:abn:88888888888", "EIGHT PTY LTD", "88888888888")]
    for key, name, abn in parties:
        st.con.execute("INSERT INTO party_canonical (canonical_key, party_type, name, abn, state) "
                       "VALUES (?, 'organisation', ?, ?, 'NSW')", [key, name, abn])
    st.con.execute("INSERT INTO link (link_id, matcher_version, source, record_id, canonical_key, match_type, "
                   "confidence) VALUES ('L1', 'test-v1', 'asic_afsl', '9001', 'urn:abn:11111111111', 'EXACT_ABN', 1.0),"
                   " ('L6', 'test-v1', 'asic_afsl', '9006', 'urn:abn:66666666666', 'EXACT_ABN', 1.0),"
                   " ('L8', 'test-v1', 'asic_afsl', '9008', 'urn:abn:88888888888', 'EXACT_ABN', 1.0),"
                   " ('LOLD', 'old-v0', 'asic_afsl', '9007', 'urn:abn:88888888888', 'EXACT_ABN', 1.0)")
    ev = ("INSERT INTO licence_event (licence_kind, source, licence_no, event_type, event_date, observed_after, "
          "holder_name_before, holder_abn_before, record_iri) VALUES (?, 'asic_afsl', ?, ?, ?, ?, ?, ?, ?)")
    for no, etype, ed, oa, name, abn in (
        ("9001", "CANCELLED_OR_LAPSED", date(2026, 10, 14), date(2026, 10, 7), "X CANONICAL PTY LTD", "11111111111"),
        ("9006", "CANCELLED_OR_LAPSED", date(2026, 5, 1), date(2026, 4, 1), "FAR AWAY PTY LTD", "66666666666"),
        # 7: no link in test-v1 (only in an old version), attributed by the holder ABN on the event
        ("9007", "CANCELLED_OR_LAPSED", date(2026, 9, 30), date(2026, 6, 2), "SEVEN PTY LTD", "77777777777"),
        ("9008", "CANCELLED_OR_LAPSED", date(2026, 10, 14), date(2026, 10, 7), "EIGHT PTY LTD", "88888888888"),
        ("9001", "GRANTED", date(2026, 9, 2), date(2026, 8, 5), "X CANONICAL PTY LTD", "11111111111"),
    ):
        st.con.execute(ev, ["AFSL", no, etype, ed, oa, name, abn, f"urn:src:asic_afsl:{no}"])
    yield st
    st.close() if hasattr(st, "close") else st.con.close()


# --------------------------------------------------------------------------- ultimate parent


def test_cycle_terminates_and_reports_path(svc: TraversalService) -> None:
    ch = svc.ultimate_parent(lei("A"), as_of=AS_OF)
    assert ch.status == "CYCLE"
    assert ch.cycle_detected and ch.ultimate_parent is None
    assert ch.cycle_path == [rec("A"), rec("B"), rec("C"), rec("A")]
    assert ch.depth == 3


def test_depth_cap_truncates(svc: TraversalService) -> None:
    ch = svc.ultimate_parent(lei("D1"), as_of=AS_OF, max_depth=3)
    assert ch.status == "TRUNCATED" and ch.truncated
    assert ch.depth == 3 and ch.top.key == rec("D4")
    full = svc.ultimate_parent(lei("D1"), as_of=AS_OF, max_depth=10)
    assert full.status == "TOP_REACHED" and full.depth == 5
    assert full.ultimate_parent.key == rec("D6")


def test_gleif_ultimate_cross_check_reports_disagreement(svc: TraversalService) -> None:
    ch = svc.ultimate_parent(lei("D1"), as_of=AS_OF)
    assert [n.key for n in ch.gleif_ultimate] == [rec("ELSEWHERE")]
    assert ch.gleif_check == "disagree_off_chain"


def test_multiple_parents_majority_and_ambiguous(svc: TraversalService) -> None:
    m = svc.ultimate_parent(lei("M"), as_of=AS_OF)
    assert m.status == "TOP_REACHED" and m.ultimate_parent.key == rec("MP1")
    assert m.edges[0].rule == "majority" and m.edges[0].percentage == 60
    n = svc.ultimate_parent(lei("N"), as_of=AS_OF)
    assert n.status == "AMBIGUOUS" and n.ultimate_parent is None
    assert sorted(e.parent for e in n.ambiguous_parents) == [rec("NP1"), rec("NP2")]


def test_choose_parent_rules() -> None:
    def e(p: float | None, k: str) -> OwnershipEdge:
        return OwnershipEdge(k, None, "c", k, p)
    assert choose_parent([e(None, "a")])[1] == "single"
    assert choose_parent([e(40, "a"), e(35, "b")])[0].parent == "a"
    assert choose_parent([e(40, "a"), e(35, "b")])[1] == "plurality"
    assert choose_parent([e(40, "a"), e(40, "b")])[0] is None
    assert choose_parent([e(None, "a"), e(51, "b")])[0].parent == "b"
    assert choose_parent([e(None, "a"), e(30, "b")])[0] is None


def test_validity_filtering(svc: TraversalService) -> None:
    old = svc.ultimate_parent(lei("V"), as_of=date(2005, 6, 1))
    new = svc.ultimate_parent(lei("V"), as_of=AS_OF)
    assert old.ultimate_parent.key == rec("POLD")
    assert new.ultimate_parent.key == rec("PNEW")
    assert svc.ultimate_parent(lei("V"), as_of=date(1999, 1, 1)).status == "NO_PARENT"


def test_linked_records_become_parties(svc: TraversalService) -> None:
    ch = svc.ultimate_parent(lei("X"), as_of=AS_OF)
    assert ch.start.kind == "party" and ch.start.key == "urn:abn:11111111111"
    assert ch.ultimate_parent.key == "urn:abn:22222222222"
    assert ch.ultimate_parent.name == "XP CANONICAL LIMITED"
    assert ch.gleif_check == "agree"
    # the record-level fact and the party-level role edge are the same fact: one edge
    assert ch.depth == 1 and ch.edges[0].percentage == 100


def test_identifier_equality_attribution_only_when_unique(svc: TraversalService) -> None:
    q = svc.resolve(lei("Q"))
    assert (q.kind, q.key, q.attribution) == ("party", "urn:acn:999000111", "acn_equality")
    r = svc.resolve(lei("R"))
    assert r.kind == "record" and r.attribution == "none"


def test_property_path_version_runs_but_misses_the_cycle(svc: TraversalService) -> None:
    res = svc.property_path_ancestors(lei("A"))
    assert res["tops"] == []  # every node of a cycle has a parent: the cycle is invisible
    assert "cannot" in res["why_not_enough"]


def test_ownership_index_matches_online_walk(svc: TraversalService) -> None:
    idx = svc.ownership_index(as_of=AS_OF)
    for tag in ("A", "D1", "M", "N", "V"):
        online = svc.ultimate_parent(lei(tag), as_of=AS_OF, cross_check=False)
        offline = idx.walk(online.start.key)
        assert (offline.status, offline.top.key, offline.depth) == (online.status, online.top.key, online.depth)


# --------------------------------------------------------------------------- caps and views


def test_entity_view_budget_truncation_and_ranking(svc: TraversalService) -> None:
    budget = TraversalBudget(per_fact_type={"licences": 2, "notices": 5, "parents": 5})
    view = svc.entity_view("urn:abn:11111111111", budget, as_of=AS_OF)
    lic = view.facts_by_type["licences"]
    assert view.totals["licences"] == 5
    assert view.truncated_counts["licences"] == 3
    assert [f.detail["licence_number"] for f in lic] == ["1002", "1003"]  # active, most recent first
    assert all(f.active for f in lic)
    assert all(f.other is None for f in lic)  # single-party facts never acquire a counterparty
    assert [f.other for f in view.facts_by_type["parents"]][0].endswith(lei("XP"))
    assert "notices" in view.facts_by_type
    assert any(i["scheme"] == "abn" and i["value"] == "11111111111" for i in view.identifiers)
    assert "3 more licences truncated" in view.truncation_note()


def test_entity_view_category_order(svc: TraversalService) -> None:
    view = svc.entity_view("urn:abn:11111111111", TraversalBudget(), as_of=AS_OF)
    cats = list(view.facts_by_type)
    assert cats.index("notices") < cats.index("licences") < cats.index("parents")


# --------------------------------------------------------------------------- graph-only questions


def test_within_two_hops_of_banned_party(svc: TraversalService) -> None:
    res = svc.near_flagged("ban", hops=2, as_of=AS_OF)
    got = {r["node"]: r["distance"] for r in res["rows"]}
    assert got == {"urn:abn:44444444444": 1, "urn:abn:55555555555": 2}
    path = next(r["path"] for r in res["rows"] if r["node"] == "urn:abn:55555555555")
    assert "Ownership" in path and "Trusteeship" in path


def test_within_hops_node_budget(svc: TraversalService) -> None:
    hood = svc.within_hops("urn:abn:33333333333", hops=3, budget=TraversalBudget(max_nodes=2), as_of=AS_OF)
    assert len(hood.neighbours) == 2
    assert hood.truncated_counts.get("max_nodes") == 1


def test_group_exposure_finds_sibling_licensee(ep: LocalEndpoint) -> None:
    svc = TraversalService(ep)
    res = svc.group_exposure(as_of=AS_OF)
    tops = {g["top"]: g for g in res["groups"]}
    assert tops["urn:abn:22222222222"]["licences"] == 5  # held by the subsidiary X
    assert res["unresolved_tops"].get("CYCLE") == 3 and res["unresolved_tops"].get("AMBIGUOUS") == 1
    foreign = {r["licensee"]: r for r in res["foreign_controlled"]}
    assert foreign["urn:abn:11111111111"]["country"] == "GB"
    assert foreign["urn:abn:11111111111"]["depth"] == 1
    assert len(foreign["urn:abn:11111111111"]["licences"]) == 5


# --------------------------------------------------------------------------- projection


def test_time_window_bounds() -> None:
    assert TimeWindow(last="P3M").bounds(AS_OF) == (date(2026, 8, 17), AS_OF)
    assert TimeWindow(last="P90D").bounds(AS_OF) == (date(2026, 8, 19), AS_OF)
    assert TimeWindow(start=date(2026, 1, 1)).bounds(AS_OF) == (date(2026, 1, 1), AS_OF)
    with pytest.raises(ValueError):
        TimeWindow(last="3 months").bounds(AS_OF)


def test_spec_round_trip_and_compilation(ep: LocalEndpoint) -> None:
    spec = load_spec("accc_notice_and_afsl_cancelled_3m", as_of=AS_OF)
    again = CriteriaSpec.from_dict(spec.to_dict())
    assert again.to_dict() == spec.to_dict()
    plan = ProjectionService(ep).plan(spec)
    engines = {s.pred.id: s.engine for s in plan.steps}
    assert engines == {"accc_notice": "sparql", "afsl_cancelled": "sql"}
    text = plan.explain()
    assert "bg:noticeRecipient" in text and f"GRAPH <{LINKS}>" in text
    assert "FROM licence_event" in text and "observed_after" in text
    sql_step = next(s for s in plan.steps if s.engine == "sql")
    # ev conditions, then matcher version, then min confidence
    assert sql_step.params == ["CANCELLED_OR_LAPSED", "AFSL", date(2026, 8, 17), AS_OF, "test-v1", 0.0]


def test_not_only_inside_all() -> None:
    with pytest.raises(ValueError):
        CriteriaSpec.from_dict({"match": {"any": [{"not": {"fact": "ban"}}, {"fact": "licence"}]}})
    with pytest.raises(ValueError):
        CriteriaSpec.from_dict({"match": {"all": [{"fact": "unknown_fact"}]}}).predicates[0].engine


def test_brief_example_returns_expected_rows(ep: LocalEndpoint, store, tmp_path) -> None:
    svc = ProjectionService(ep, store)
    df = svc.project(load_spec("accc_notice_and_afsl_cancelled_3m", as_of=AS_OF))
    assert sorted(df["party"]) == ["urn:abn:11111111111", "urn:abn:77777777777"]
    x = df.set_index("party").loc["urn:abn:11111111111"]
    assert x["afsl_cancelled__event_date"] == date(2026, 10, 14)
    assert x["afsl_cancelled__observed_after"] == date(2026, 10, 7)
    assert x["afsl_cancelled__attribution"] == "link" and x["afsl_cancelled__link"] == "L1"
    assert x["accc_notice__source"] == G_ACCC
    assert x["accc_notice__match_type"] == "NAME_NORMALISED_EXACT"
    assert x["accc_notice__regulator"] == "ACCC"
    assert x["name"] == "X CANONICAL PTY LTD"
    seven = df.set_index("party").loc["urn:abn:77777777777"]
    assert seven["afsl_cancelled__attribution"] == "holder_identifier"
    assert seven["afsl_cancelled__match_type"] == "EVENT_HOLDER_ABN"
    assert seven["min_link_confidence"] == pytest.approx(0.7)
    out = write_projection(df, tmp_path / "brief.csv")
    assert out.read_text(encoding="utf-8").count("\n") == 3
    pq = write_projection(df, tmp_path / "brief.parquet")
    assert pq.stat().st_size > 0


def test_confidence_floor_and_certain_window(ep: LocalEndpoint, store) -> None:
    svc = ProjectionService(ep, store)
    spec = load_spec("accc_notice_and_afsl_cancelled_3m", as_of=AS_OF)
    spec.min_confidence = 0.8  # the 0.7 notice link for party 7 no longer counts
    assert sorted(svc.project(spec)["party"]) == ["urn:abn:11111111111"]
    certain = CriteriaSpec.from_dict({**NAMED_SPECS["accc_notice_and_afsl_cancelled_3m"], "as_of": "2026-11-17"})
    certain.predicates[1].params["certain"] = True  # 7's observed_after (2026-06-02) is before the window
    assert sorted(svc.project(certain)["party"]) == ["urn:abn:11111111111"]


def test_notice_window_and_or_not(ep: LocalEndpoint, store) -> None:
    svc = ProjectionService(ep, store)
    win = load_spec("accc_notice_in_window_and_afsl_cancelled_3m", as_of=AS_OF)
    assert sorted(svc.project(win)["party"]) == ["urn:abn:11111111111"]  # 7's notice is from 2024
    anyspec = CriteriaSpec.from_dict({"as_of": "2026-11-17", "match": {"any": [
        {"id": "ban", "fact": "ban"},
        {"id": "ev", "fact": "licence_event", "event_type": "CANCELLED_OR_LAPSED", "window": "P3M"}]}})
    assert sorted(svc.project(anyspec)["party"]) == [
        "urn:abn:11111111111", "urn:abn:33333333333", "urn:abn:77777777777", "urn:abn:88888888888"]
    notspec = CriteriaSpec.from_dict({"as_of": "2026-11-17", "match": {"all": [
        {"id": "ev", "fact": "licence_event", "event_type": "CANCELLED_OR_LAPSED", "window": "P3M"},
        {"not": {"id": "n", "fact": "notice"}}]}, "columns": ["party", "name", "ev__*"]})
    df = svc.project(notspec)
    assert list(df["party"]) == ["urn:abn:88888888888"]
    assert list(df.columns)[:2] == ["party", "name"] and "ev__event_date" in df.columns


def test_party_attribute_predicate_pushdown(ep: LocalEndpoint, store) -> None:
    svc = ProjectionService(ep, store)
    spec = CriteriaSpec.from_dict({"as_of": "2026-11-17", "match": {"all": [
        {"id": "st", "fact": "party", "field": "state", "op": "=", "value": "NSW"},
        {"id": "n", "fact": "notice"}]}})
    df = svc.project(spec)
    assert sorted(df["party"]) == ["urn:abn:11111111111", "urn:abn:66666666666", "urn:abn:77777777777"]
    # the notice (graph) ran first and the SQL predicate got the surviving keys
    assert [q["engine"] for q in svc.last_run["queries"]] == ["sparql", "sql"]
    assert "_proj_restrict" in svc.last_run["queries"][1]["text"]
