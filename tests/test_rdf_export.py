"""RDF export: escaping, IRI patterns, determinism, schema coverage, SHACL on a synthetic store,
and a live Fuseki round trip (skipped when Fuseki is not reachable).

The synthetic store mirrors ontology/examples.ttl: Southern Cross Advisory with an AFSL and a
GLEIF ownership chain that cycles, a liquidator person, a banned organisation, and the
deliberate ACN conflict (ACN 610005555 under two ABNs). All identifiers are synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import OWL

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.rdf.exporter import NamedGraph, RdfExporter
from bizgraph.rdf.publish import ShaclValidator, find_java
from bizgraph.rdf.vocab import (
    BG,
    IriFactory,
    decimal_lexical,
    escape_literal,
    lit,
    predicates_used,
)
from bizgraph.store.duckdb_store import DuckDBStore

ONT_DIR = Path(__file__).resolve().parents[1] / "ontology"
SNAP = date(2026, 11, 10)
MV = "m-test.1"
TRICKY_NAME = 'Smith "Q" \\ Co\nLtd\r\tCAFÉ 漢字 \x01end'

SCA_ABN, SCA_ACN = "38610001119", "610001119"
LEI_SCA, LEI_BETA, LEI_GAMMA = "9845EXAMPLE000000114", "9845EXAMPLE000000211", "9845EXAMPLE000000308"
LEI_TRUST, LEI_TRUST_BAD, LEI_SCHEME = "9845EXAMPLE000000405", "9845EXAMPLE000000502", "9845EXAMPLE000000609"
SCHEME_ARSN = "601234567"
CONFLICT_PARTIES = {"urn:abn:23610005555", "urn:abn:55610004441"}


def _rec(source, rid, name=None, ptype=PartyType.ORGANISATION, ids=(), payload=None, snap=SNAP):
    return SourceRecord(
        source=source, record_id=rid, snapshot_date=snap, payload=payload or {"name": name},
        name_raw=name, name_norm=(name or "").lower() or None, party_type=ptype,
        identifiers=tuple(Identifier(s, v) for s, v in ids),
    )


def build_store(with_alias: bool = True) -> DuckDBStore:
    st = DuckDBStore(":memory:")
    recs = [
        _rec("abr", SCA_ABN, "SOUTHERN CROSS ADVISORY PTY LTD", ids=[(IdScheme.ABN, SCA_ABN), (IdScheme.ACN, SCA_ACN)]),
        _rec("abr", "23610005555", "HARBOUR FREIGHT PTY LTD",
             ids=[(IdScheme.ABN, "23610005555"), (IdScheme.ACN, "610005555")]),
        _rec("abr", "55610004441", "HARBOURSIDE LOGISTICS PTY LTD",
             ids=[(IdScheme.ABN, "55610004441"), (IdScheme.ACN, "610005555")]),
        _rec("asic_company", SCA_ACN, "SOUTHERN CROSS ADVISORY PTY. LTD.",
             ids=[(IdScheme.ACN, SCA_ACN), (IdScheme.ABN, SCA_ABN)]),
        _rec("asic_afsl", "512345", TRICKY_NAME, ids=[(IdScheme.AFSL, "512345"), (IdScheme.ABN, SCA_ABN)],
             payload={"licence_number": "512345", "status": "current", "licence_start": "2016-07-01",
                      "licence_end": None, "authorisation_format": 2,
                      "authorisations": ["Deal in securities | retail", "Advise on deposits \"basic\""]}),
        _rec("asic_credit", "387654", "EXAMPLE, Jo", ptype=PartyType.PERSON, ids=[(IdScheme.ACL, "387654")],
             payload={"licence_number": "387654", "status": "approved", "licence_start": "2018-01-01",
                      "licence_end": "2027-01-01", "authorisations": []}),
        _rec("asic_liquidator", "030471", "EXAMPLE, Jordan Avery", ptype=PartyType.PERSON,
             ids=[(IdScheme.LIQUIDATOR_NO, "030471")],
             payload={"liquidator_number": "030471", "status": "approved", "registration_start": "2019-01-14",
                      "country": "AUSTRALIA", "firm": "EXAMPLE & PARTNERS"}),
        # a register row with a zero number: no bg:liquidatorNumber and no Licence fact
        _rec("asic_liquidator", "000000", "ZERO, Nobody", ptype=PartyType.PERSON,
             ids=[(IdScheme.LIQUIDATOR_NO, "0")], payload={"liquidator_number": "0", "status": "approved"}),
        _rec("asic_banned_org", "harbour freight|credit_ban|2025-06-01", "HARBOUR FREIGHT PTY LTD",
             payload={"ban_type": "Credit ban", "ban_start": "2025-06-01", "ban_end": "2030-05-31",
                      "comment": "line1\nline2"}),
        _rec("gleif_l1", LEI_SCA, "SOUTHERN CROSS ADVISORY PTY LTD",
             ids=[(IdScheme.LEI, LEI_SCA), (IdScheme.ACN, SCA_ACN)], snap=date(2026, 11, 16)),
        _rec("gleif_l1", LEI_BETA, "BETA REGIONAL HOLDINGS LIMITED", ids=[(IdScheme.LEI, LEI_BETA)],
             snap=date(2026, 11, 16)),
        _rec("gleif_l1", LEI_GAMMA, "GAMMA GROUP INVESTMENTS LIMITED", ids=[(IdScheme.LEI, LEI_GAMMA)],
             snap=date(2026, 11, 16)),
        # a trust whose GLEIF registration number is its trustee's ACN (SCA)
        _rec("gleif_l1", LEI_TRUST, "SCA FAMILY TRUST", ids=[(IdScheme.LEI, LEI_TRUST)], snap=date(2026, 11, 16),
             payload={"trustee_acn": SCA_ACN, "entity_status": "ACTIVE", "lei_status": "ISSUED",
                      "legal_form_code": "TRST", "country": "AU", "legal_jurisdiction": "AU",
                      "legal_address": {"country": "AU"}, "headquarters_address": {"country": "GI"}}),
        # a trust whose trustee ACN is the quarantined, two-party ACN: no roles may be attributed
        _rec("gleif_l1", LEI_TRUST_BAD, "HARBOUR TRUST", ids=[(IdScheme.LEI, LEI_TRUST_BAD)],
             snap=date(2026, 11, 16), payload={"trustee_acn": "610005555", "headquarters_address": {"country": "NZ"}}),
        # ACCC infringement notices: one single-party (no penalty stated), one naming two parties
        _rec("accc_notice", "southern-cross-advisers-0", "Southern Cross Advisers", snap=date(2026, 11, 17),
             payload={"regulator": "ACCC", "date_paid": "2026-10-21", "date_issued": "2026-10-21",
                      "parties": [{"name": "Southern Cross Advisers", "party_type": "organisation"}],
                      "multi_party": False, "penalty_total_aud": None, "description": None,
                      "section": "Section 48(1) of the Australian Consumer Law",
                      "infringement_numbers": ["2526/49", "2526/48"], "notice_count": 2,
                      "legislation": ["Australian Consumer Law"],
                      "url": "https://www.accc.gov.au/public-registers/infringement-notices-register/southern-cross-advisers-0",
                      "reference_kind": "foreign_tax_id", "reference_number": "CIF B-00000000"}),
        _rec("accc_notice", "harbour-freight-and-beta-0", "HARBOUR FREIGHT PTY LTD", snap=date(2026, 11, 17),
             payload={"date_paid": None, "date_issued": "2026-09-01",
                      "parties": [{"name": "HARBOUR FREIGHT PTY LTD"}, {"name": "BETA REGIONAL HOLDINGS LIMITED"}],
                      "multi_party": True, "penalty_total_aud": "39600.00",
                      "description": "Alleged false or misleading representations."}),
        # a managed investment scheme: ARSN, NZ identifiers
        _rec("gleif_l1", LEI_SCHEME, "EXAMPLE INCOME FUND", snap=date(2026, 11, 16),
             ids=[(IdScheme.LEI, LEI_SCHEME), (IdScheme.ARSN, SCHEME_ARSN), (IdScheme.NZBN, "9429000000000"),
                  (IdScheme.NZ_COMPANY_NO, "1234567")]),
    ]
    for child, parent, pct in ((LEI_SCA, LEI_BETA, "100.00"), (LEI_BETA, LEI_GAMMA, "75.5"), (LEI_GAMMA, LEI_BETA, None)):
        rt = "IS_DIRECTLY_CONSOLIDATED_BY"
        recs.append(_rec("gleif_l2", f"{child}|{rt}|{parent}", None, ptype=PartyType.UNKNOWN, snap=date(2026, 11, 16),
                         payload={"relationship_type": rt, "relationship_status": "ACTIVE", "child_lei": child,
                                  "parent_lei": parent, "valid_from": "2018-03-31", "valid_to": None,
                                  "quantifiers": [{"method": "ACCOUNTING_CONSOLIDATION", "amount": pct,
                                                   "units": "PERCENTAGE"}] if pct else []}))
    # a non-ownership L2 edge: no Ownership fact
    recs.append(_rec("gleif_l2", f"{LEI_GAMMA}|IS_FUND-MANAGED_BY|{LEI_SCA}", None, ptype=PartyType.UNKNOWN,
                     snap=date(2026, 11, 16), payload={"relationship_type": "IS_FUND-MANAGED_BY"}))
    st.records.upsert(recs)
    for src, d in {(r.source, r.snapshot_date) for r in recs}:
        st.execute("INSERT INTO source_snapshot (source, snapshot_date, file_hash, records_in) VALUES (?, ?, ?, ?)",
                   [src, d, f"hash-{src}", sum(1 for r in recs if r.source == src)])

    parties = [
        # key, type, name, abn, acn, lei, source, record_id, asic_record_id
        (f"abn:{SCA_ABN}", "organisation", "SOUTHERN CROSS ADVISORY PTY LTD", SCA_ABN, SCA_ACN, LEI_SCA, "abr", SCA_ABN, SCA_ACN),
        ("abn:23610005555", "organisation", "HARBOUR FREIGHT PTY LTD", "23610005555", "610005555", None, "abr", "23610005555", None),
        ("abn:55610004441", "organisation", "HARBOURSIDE LOGISTICS PTY LTD", "55610004441", "610005555", None, "abr", "55610004441", None),
        (f"lei:{LEI_BETA}", "organisation", "BETA REGIONAL HOLDINGS LIMITED", None, None, LEI_BETA, "gleif_l1", LEI_BETA, None),
        (f"lei:{LEI_GAMMA}", "organisation", "GAMMA GROUP INVESTMENTS LIMITED", None, None, LEI_GAMMA, "gleif_l1", LEI_GAMMA, None),
        ("party:person:6b1f0c2e9d", "person", "Jordan Avery EXAMPLE", None, None, None, "asic_liquidator", "030471", None),
        (f"lei:{LEI_TRUST}", "organisation", "SCA FAMILY TRUST", None, None, LEI_TRUST, "gleif_l1", LEI_TRUST, None),
        # the ACN column is (wrongly) filled with the ARSN: the exporter must not write it as bg:acn
        (f"lei:{LEI_SCHEME}", "organisation", "EXAMPLE INCOME FUND", None, SCHEME_ARSN, LEI_SCHEME, "gleif_l1",
         LEI_SCHEME, None),
    ]
    for key, pt, name, abn, acn, lei, src, rid, arid in parties:
        st.execute(
            """INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, abn, acn, lei, entity_type,
                   status, state, postcode, valid_from, source, record_id, asic_record_id)
               VALUES (?, ?, ?, lower(?), ?, ?, ?, 'PRV', 'ACT', 'NSW', '2000', DATE '2015-02-11', ?, ?, ?)""",
            [key, pt, name, name, abn, acn, lei, src, rid, arid],
        )
        for scheme, value in (("abn", abn), ("lei", lei), ("arsn", SCHEME_ARSN if lei == LEI_SCHEME else None)):
            if value:
                st.execute("INSERT INTO identifier VALUES (?, ?, ?)", [key, scheme, value])
    if with_alias:
        st.execute("INSERT INTO alias VALUES (?, ?, ?, ?, ?, ?)",
                   [f"abn:{SCA_ABN}", "SCA \"Advisory\"", "sca advisory", "BN", "abr", SCA_ABN])
    else:
        st.execute("DROP TABLE alias")

    links = [
        ("asic_afsl", "512345", f"abn:{SCA_ABN}", "EXACT_ABN", 1.0),
        ("gleif_l1", LEI_SCA, f"abn:{SCA_ABN}", "EXACT_ACN", 1.0),
        ("gleif_l1", LEI_BETA, f"lei:{LEI_BETA}", "EXACT_LEI", 1.0),
        ("gleif_l1", LEI_GAMMA, f"lei:{LEI_GAMMA}", "EXACT_LEI", 1.0),
        ("gleif_l1", LEI_TRUST, f"lei:{LEI_TRUST}", "EXACT_LEI", 1.0),
        ("accc_notice", "harbour-freight-and-beta-0", "abn:23610005555", "NAME_NORMALISED_EXACT", 0.97),
        ("asic_liquidator", "030471", "party:person:6b1f0c2e9d", "EXACT_LICENCE_NO", 1.0),
        ("asic_banned_org", "harbour freight|credit_ban|2025-06-01", "abn:23610005555", "NAME_NORMALISED_EXACT", 0.96),
    ]
    for src, rid, key, mt, conf in links:
        st.links.save(f"{MV}:{src}:{rid}", MV, src, rid, key, mt, conf, {"rule": mt, "note": 'quote " here'})
    st.abstentions.save(MV, "asic_credit", "387654", "BELOW_THRESHOLD", f"abn:{SCA_ABN}", 0.81)
    return st


@pytest.fixture()
def store():
    st = build_store()
    yield st
    st.close()


@pytest.fixture()
def exported(store, tmp_path) -> dict[str, Path]:
    ex = RdfExporter(store, ONT_DIR)
    return {r.graph.iri: r.path for r in ex.export_all(tmp_path / "rdf")}


def _graph(*paths: Path) -> Graph:
    g = Graph()
    for p in paths:
        g.parse(p, format="nt")
    return g


# --------------------------------------------------------------------------- escaping


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("plain", "plain"),
        ('say "hi"', 'say \\"hi\\"'),
        ("back\\slash", "back\\\\slash"),
        ("a\nb\rc\td", "a\\nb\\rc\\td"),
        ("bell\x07 del\x7f", "bell\\u0007 del\\u007F"),
        ("CAFÉ 漢字 😀", "CAFÉ 漢字 😀"),  # non-ASCII stays raw UTF-8
        ("lone \ud800 surrogate", "lone � surrogate"),
    ],
)
def test_escape_literal(raw, expected):
    assert escape_literal(raw) == expected


@pytest.mark.parametrize("raw", [TRICKY_NAME, "x\\\"y", "\\n is not a newline", "tab\tand sep", "😀"])
def test_literal_round_trips_through_rdflib(raw):
    line = f"<urn:s> <urn:p> {lit(raw)} .\n"
    g = Graph().parse(data=line, format="nt")
    (o,) = list(g.objects())
    assert str(o) == raw


def test_decimal_lexical():
    assert decimal_lexical(1.0) == "1.0"
    assert decimal_lexical("100.00") == "100.0"
    assert decimal_lexical(1e-05) == "0.00001"
    assert decimal_lexical(0.96) == "0.96"
    assert decimal_lexical("abc") is None


# --------------------------------------------------------------------------- IRIs


def test_iri_patterns():
    f = IriFactory
    assert f.party(abn="38610001119", acn="610001119", lei=LEI_SCA) == "urn:abn:38610001119"
    assert f.party(acn="610001119", lei=LEI_SCA) == "urn:acn:610001119"
    assert f.party(lei=LEI_SCA) == f"urn:lei:{LEI_SCA}"
    assert f.party(canonical_key="abn:38610001119") == "urn:abn:38610001119"
    assert f.party(canonical_key="urn:party:x") == "urn:party:x"
    assert f.party(canonical_key="party:person:ab12") == "urn:party:person:ab12"
    assert f.source_record("asic_afsl", "512345") == "urn:src:asic_afsl:512345"
    assert f.source_record("gleif_l2", "A|IS_X|B") == "urn:src:gleif_l2:A%7CIS_X%7CB"
    assert f.source_record("asic_banned_org", "harbour freight|ban|2025-06-01") == (
        "urn:src:asic_banned_org:harbour%20freight%7Cban%7C2025-06-01"
    )
    assert f.source_record("x", "100%") == "urn:src:x:100%25"
    assert f.fact("asic_afsl", "512345") == "urn:fact:asic_afsl:512345"
    assert f.fact("asic_liquidator", "30471", 1) == "urn:fact:asic_liquidator:30471:1"
    assert f.link("m-1", "asic_afsl", "512345") == "urn:link:m-1:asic_afsl:512345"
    assert f.abstention("m-1", "accc", "IN-1") == "urn:abstention:m-1:accc:IN-1"
    assert f.source_graph("abr", date(2026, 11, 9)) == "urn:graph:source:abr:2026-11-09"
    assert f.links_graph("m-2026.11.1") == "urn:graph:links:m-2026.11.1"


def test_graph_catalogue(store):
    ex = RdfExporter(store, ONT_DIR)
    iris = [g.iri for g in ex.graphs()]
    assert iris[0] == "urn:graph:ontology"
    assert "urn:graph:source:asic_afsl:2026-11-10" in iris
    assert "urn:graph:source:gleif_l2:2026-11-16" in iris
    assert "urn:graph:canonical" in iris
    assert f"urn:graph:links:{MV}" in iris


def test_exported_iris_and_structure(exported):
    src = _graph(exported["urn:graph:source:asic_afsl:2026-11-10"])
    rec = URIRef("urn:src:asic_afsl:512345")
    fact = URIRef("urn:fact:asic_afsl:512345")
    assert (rec, RDF.type, URIRef(BG + "SourceRecord")) in src
    assert str(src.value(rec, URIRef(BG + "nameRaw"))) == TRICKY_NAME
    assert (fact, URIRef(BG + "aboutRecord"), rec) in src
    assert (fact, URIRef(BG + "licenceKind"), URIRef(BG + "AFSL")) in src
    assert src.value(fact, URIRef(BG + "validFrom")) == Literal(date(2016, 7, 1))
    # no party-level role in a source graph
    assert not list(src.triples((None, URIRef(BG + "licensee"), None)))

    l2 = _graph(exported["urn:graph:source:gleif_l2:2026-11-16"])
    own = URIRef(f"urn:fact:gleif_l2:{LEI_SCA}%7CIS_DIRECTLY_CONSOLIDATED_BY%7C{LEI_BETA}")
    assert (own, URIRef(BG + "aboutRecord"), URIRef(f"urn:src:gleif_l1:{LEI_SCA}")) in l2
    assert (own, URIRef(BG + "counterpartyRecord"), URIRef(f"urn:src:gleif_l1:{LEI_BETA}")) in l2
    assert str(l2.value(own, URIRef(BG + "ownershipPercentage"))) == "100.0"
    assert len(set(l2.subjects(RDF.type, URIRef(BG + "Ownership")))) == 3  # fund-managed edge excluded

    canon = _graph(exported["urn:graph:canonical"])
    sca = URIRef(f"urn:abn:{SCA_ABN}")
    assert (sca, RDF.type, URIRef(BG + "Organisation")) in canon
    assert (URIRef("urn:party:person:6b1f0c2e9d"), RDF.type, URIRef(BG + "Person")) in canon
    assert (URIRef(f"urn:lei:{LEI_BETA}"), RDF.type, URIRef(BG + "Organisation")) in canon
    assert str(canon.value(sca, URIRef(BG + "otherName"))) == 'SCA "Advisory"'
    prov = set(canon.objects(sca, URIRef("http://www.w3.org/ns/prov#wasDerivedFrom")))
    assert prov == {URIRef(f"urn:src:abr:{SCA_ABN}"), URIRef(f"urn:src:asic_company:{SCA_ACN}")}

    links = _graph(exported[f"urn:graph:links:{MV}"])
    link = URIRef(f"urn:link:{MV}:asic_afsl:512345")
    assert (link, URIRef(BG + "party"), sca) in links
    assert (link, URIRef(BG + "matchType"), URIRef(BG + "EXACT_ABN")) in links
    assert json.loads(str(links.value(link, URIRef(BG + "evidence"))))["note"] == 'quote " here'
    assert (URIRef("urn:fact:asic_afsl:512345"), URIRef(BG + "licensee"), sca) in links
    assert (own, URIRef(BG + "owned"), sca) in links
    assert (own, URIRef(BG + "owner"), URIRef(f"urn:lei:{LEI_BETA}")) in links
    ab = URIRef(f"urn:abstention:{MV}:asic_credit:387654")
    assert (ab, URIRef(BG + "abstainReason"), URIRef(BG + "BELOW_THRESHOLD")) in links
    assert (ab, URIRef(BG + "bestCandidate"), sca) in links


def test_nquads_carry_graph(store, tmp_path):
    ex = RdfExporter(store, ONT_DIR)
    g = NamedGraph.source_snapshot("asic_banned_org", SNAP)
    res = ex.export(g, tmp_path, "nq")
    lines = res.path.read_text(encoding="utf-8").splitlines()
    assert res.path.suffix == ".nq" and len(lines) == res.triples > 0
    assert all(ln.endswith(f" <{g.iri}> .") for ln in lines)


# --------------------------------------------------------------------------- determinism


def test_export_is_byte_identical(tmp_path):
    hashes = []
    for run in ("a", "b"):
        st = build_store()
        ex = RdfExporter(st, ONT_DIR)
        files = ex.export_all(tmp_path / run)
        hashes.append({r.path.name: hashlib.sha256(r.path.read_bytes()).hexdigest() for r in files})
        st.close()
    assert hashes[0] == hashes[1]
    assert len(hashes[0]) >= 9


def test_missing_optional_tables(tmp_path):
    st = build_store(with_alias=False)
    st.execute("DROP TABLE identifier")
    st.execute("DROP TABLE abstention")
    ex = RdfExporter(st, ONT_DIR)
    res = ex.export(NamedGraph.canonical(), tmp_path)
    assert res.counts["parties"] == 8  # no identifier table: the ARSN (and so the scheme type) is unknown
    res = ex.export(NamedGraph.links(MV), tmp_path)
    assert res.counts["links"] == 8 and res.counts["abstentions"] == 0
    st.close()


# --------------------------------------------------------------------------- schema coverage


@pytest.fixture(scope="module")
def schema() -> Graph:
    return Graph().parse(ONT_DIR / "schema.ttl")


EXTERNAL_OK = {str(RDF.type)}  # prov:wasDerivedFrom is declared in schema.ttl 0.2.0


def _defined(schema: Graph) -> set[str]:
    return {str(s) for s in schema.subjects() if isinstance(s, URIRef)}


def test_every_exporter_predicate_is_in_schema(schema):
    missing = sorted(p for p in predicates_used() if p not in EXTERNAL_OK and p not in _defined(schema))
    assert missing == []


def test_every_exported_term_is_in_schema(exported, schema):
    g = _graph(*[p for iri, p in exported.items() if iri != "urn:graph:ontology"])
    defined = _defined(schema)
    preds = {str(p) for p in g.predicates()}
    assert sorted(p for p in preds if p not in EXTERNAL_OK and p not in defined) == []
    bg_objects = {str(o) for o in g.objects() if isinstance(o, URIRef) and str(o).startswith(BG)}
    assert sorted(o for o in bg_objects if o not in defined) == []
    # every predicate the exporter uses is a declared property of the right kind
    for p in preds - EXTERNAL_OK:
        kinds = set(schema.objects(URIRef(p), RDF.type))
        assert kinds & {OWL.DatatypeProperty, OWL.ObjectProperty}, p


def test_ontology_graph_matches_schema(exported, schema):
    from rdflib.compare import isomorphic

    assert isomorphic(_graph(exported["urn:graph:ontology"]), schema)


# --------------------------------------------------------------------------- SHACL


def _violations(report):
    return [v for v in report.violations if v.severity == "Violation"]


def test_shacl_pyshacl_reports_only_the_acn_conflict(exported, tmp_path):
    files = [p for iri, p in exported.items() if iri != "urn:graph:ontology"]
    report = ShaclValidator("pyshacl", ONT_DIR).validate_files(files, workdir=tmp_path / "shacl")
    vs = _violations(report)
    assert not report.conforms
    assert {v.focus for v in vs} == CONFLICT_PARTIES, [(v.shape, v.focus, v.message) for v in vs]
    assert {v.shape for v in vs} == {"PartyShape"}
    assert all("610005555" in v.message for v in vs)


def _has_java() -> bool:
    try:
        find_java()
        return (Path(__file__).resolve().parents[1] / "tools" / "apache-jena-5.5.0" / "lib").exists()
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not _has_java(), reason="portable JDK / Jena not installed")
def test_shacl_jena_agrees(exported, tmp_path):
    files = [p for iri, p in exported.items() if iri != "urn:graph:ontology"]
    report = ShaclValidator("jena", ONT_DIR).validate_files(files, workdir=tmp_path / "shacl")
    vs = _violations(report)
    assert {v.focus for v in vs} == CONFLICT_PARTIES
    assert {v.shape for v in vs} == {"PartyShape"}


def test_shacl_catches_property_violations(store, tmp_path):
    """A bad percentage and an inverted validity interval are reported against the right shapes."""
    store.execute(
        """UPDATE source_record SET payload = json_merge_patch(payload,
               '{"quantifiers": [{"method": "ACCOUNTING_CONSOLIDATION", "amount": "150", "units": "PERCENTAGE"}],
                 "valid_to": "2001-01-01"}')
           WHERE source = 'gleif_l2' AND record_id LIKE ?""",
        [f"{LEI_SCA}|%"],
    )
    ex = RdfExporter(store, ONT_DIR)
    files = [r.path for r in ex.export_all(tmp_path / "rdf") if r.graph.kind != "ontology"]
    report = ShaclValidator("pyshacl", ONT_DIR).validate_files(files)
    shapes = {v.shape for v in _violations(report)}
    assert "OwnershipShape/ownershipPercentage" in shapes
    assert "FactShape/validFrom" in shapes


def test_shacl_sample_keeps_types(exported, tmp_path):
    files = [p for iri, p in exported.items() if iri != "urn:graph:ontology"]
    v = ShaclValidator("pyshacl", ONT_DIR)
    n_full = v.merge(files, tmp_path / "full.nt")
    n_sample = v.merge(files, tmp_path / "sample.nt", sample_every=7)
    assert n_sample < n_full
    sample = (tmp_path / "sample.nt").read_text(encoding="utf-8")
    assert sample.count("22-rdf-syntax-ns#type>") == (tmp_path / "full.nt").read_text(encoding="utf-8").count(
        "22-rdf-syntax-ns#type>"
    )


def test_quarantine_rows(store, exported):
    files = [p for iri, p in exported.items() if iri != "urn:graph:ontology"]
    report = ShaclValidator("pyshacl", ONT_DIR).validate_files(files)
    n = ShaclValidator.to_quarantine(store, report.violations)
    rows = store.query("SELECT source, record_id, invariant FROM quarantine ORDER BY record_id")
    assert n == len(rows) == 2
    assert {r["record_id"] for r in rows} == CONFLICT_PARTIES
    assert {r["invariant"] for r in rows} == {"shacl:PartyShape"}


# --------------------------------------------------------------------------- live Fuseki


def _fuseki():
    from bizgraph.config import get_settings
    from bizgraph.store.fuseki import FusekiClient

    c = FusekiClient(get_settings())
    return c if c.ping() else None


@pytest.mark.skipif(_fuseki() is None, reason="Fuseki not reachable")
def test_live_put_and_count(exported):
    from bizgraph.rdf.publish import GraphLoader

    client = _fuseki()
    loader = GraphLoader(client)
    graph = "urn:graph:test:rdf-export"
    path = exported["urn:graph:source:asic_afsl:2026-11-10"]
    n = sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
    try:
        loader.replace(graph, path)
        loader.replace(graph, path)  # idempotent
        assert client.count_triples(graph) == n
        rows = client.query(
            f"SELECT ?n WHERE {{ GRAPH <{graph}> {{ <urn:src:asic_afsl:512345> <{BG}nameRaw> ?n }} }}"
        )
        assert rows == [{"n": TRICKY_NAME}]
    finally:
        loader.drop(graph)
    assert client.count_triples(graph) == 0


# --------------------------------------------------------------------------- schema 0.2.0 additions


def test_record_identifiers_and_descriptive_literals(exported):
    l1 = _graph(exported["urn:graph:source:gleif_l1:2026-11-16"])
    scheme_rec = URIRef(f"urn:src:gleif_l1:{LEI_SCHEME}")
    assert str(l1.value(scheme_rec, URIRef(BG + "arsn"))) == SCHEME_ARSN
    assert (scheme_rec, URIRef(BG + "acn"), None) not in l1
    assert str(l1.value(scheme_rec, URIRef(BG + "nzbn"))) == "9429000000000"
    assert str(l1.value(scheme_rec, URIRef(BG + "nzCompanyNumber"))) == "1234567"
    trust_rec = URIRef(f"urn:src:gleif_l1:{LEI_TRUST}")
    for pred, value in (("registrationStatus", "ACTIVE"), ("leiRegistrationStatus", "ISSUED"),
                        ("legalFormCode", "TRST"), ("country", "AU"), ("legalJurisdiction", "AU")):
        assert str(l1.value(trust_rec, URIRef(BG + pred))) == value, pred

    afsl = _graph(exported["urn:graph:source:asic_afsl:2026-11-10"])
    assert str(afsl.value(URIRef("urn:src:asic_afsl:512345"), URIRef(BG + "afslNumber"))) == "512345"
    credit = _graph(exported["urn:graph:source:asic_credit:2026-11-10"])
    assert str(credit.value(URIRef("urn:src:asic_credit:387654"), URIRef(BG + "aclNumber"))) == "387654"

    liq = _graph(exported["urn:graph:source:asic_liquidator:2026-11-10"])
    assert str(liq.value(URIRef("urn:src:asic_liquidator:030471"), URIRef(BG + "liquidatorNumber"))) == "30471"
    zero = URIRef("urn:src:asic_liquidator:000000")
    assert (zero, URIRef(BG + "liquidatorNumber"), None) not in liq
    assert (URIRef("urn:fact:asic_liquidator:000000"), None, None) not in liq
    assert not [o for o in liq.objects(None, URIRef(BG + "licenceNumber")) if str(o) in ("", "0")]


def test_managed_investment_scheme_never_has_acn(exported):
    canon = _graph(exported["urn:graph:canonical"])
    scheme = URIRef(f"urn:lei:{LEI_SCHEME}")
    assert (scheme, RDF.type, URIRef(BG + "ManagedInvestmentScheme")) in canon
    assert str(canon.value(scheme, URIRef(BG + "arsn"))) == SCHEME_ARSN
    assert (scheme, URIRef(BG + "acn"), None) not in canon
    assert not list(canon.subjects(URIRef(BG + "acn"), Literal(SCHEME_ARSN)))
    assert URIRef(f"urn:acn:{SCHEME_ARSN}") not in set(canon.subjects())


def test_trusteeship_fact_and_roles(exported):
    l1 = _graph(exported["urn:graph:source:gleif_l1:2026-11-16"])
    fact = URIRef(f"urn:fact:gleif_l1:{LEI_TRUST}:trustee")
    assert (fact, RDF.type, URIRef(BG + "Trusteeship")) in l1
    assert (fact, URIRef(BG + "relationshipKind"), URIRef(BG + "HAS_TRUSTEE")) in l1
    assert (fact, URIRef(BG + "aboutRecord"), URIRef(f"urn:src:gleif_l1:{LEI_TRUST}")) in l1
    assert str(l1.value(fact, URIRef(BG + "counterpartyAcn"))) == SCA_ACN
    assert len(set(l1.subjects(RDF.type, URIRef(BG + "Trusteeship")))) == 2
    assert (fact, URIRef(BG + "trustee"), None) not in l1  # roles only in the links graph

    links = _graph(exported[f"urn:graph:links:{MV}"])
    assert (fact, URIRef(BG + "trustee"), URIRef(f"urn:abn:{SCA_ABN}")) in links
    assert (fact, URIRef(BG + "trust"), URIRef(f"urn:lei:{LEI_TRUST}")) in links
    bad = URIRef(f"urn:fact:gleif_l1:{LEI_TRUST_BAD}:trustee")
    assert not list(links.triples((bad, None, None)))  # ACN on two parties: no attribution


def test_gleif_country_prefers_legal_address(exported):
    l1 = _graph(exported["urn:graph:source:gleif_l1:2026-11-16"])
    country = URIRef(BG + "country")
    assert str(l1.value(URIRef(f"urn:src:gleif_l1:{LEI_TRUST}"), country)) == "AU"  # legal AU, HQ GI
    assert str(l1.value(URIRef(f"urn:src:gleif_l1:{LEI_TRUST_BAD}"), country)) == "NZ"  # HQ only


def test_infringement_notices(exported):
    g = _graph(exported["urn:graph:source:accc_notice:2026-11-17"])
    notice = URIRef(BG + "InfringementNotice")
    single = URIRef("urn:fact:accc_notice:southern-cross-advisers-0")
    assert (single, RDF.type, notice) in g
    assert str(g.value(single, URIRef(BG + "regulator"))) == "ACCC"
    assert g.value(single, URIRef(BG + "validFrom")) == Literal(date(2026, 10, 21))
    assert g.value(single, URIRef(BG + "validTo")) == Literal(date(2026, 10, 21))
    assert (single, URIRef(BG + "amountAud"), None) not in g  # no penalty stated: nothing emitted
    assert "Section 48(1)" in str(g.value(single, URIRef(BG + "description")))
    assert (single, URIRef(BG + "aboutRecord"), URIRef("urn:src:accc_notice:southern-cross-advisers-0")) in g

    multi = [URIRef(f"urn:fact:accc_notice:harbour-freight-and-beta-0:{n}") for n in (1, 2)]
    assert all((f, RDF.type, notice) in g for f in multi)
    assert len(set(g.subjects(RDF.type, notice))) == 3
    assert g.value(multi[0], URIRef(BG + "validFrom")) == Literal(date(2026, 9, 1))  # date issued fallback
    assert (URIRef("urn:fact:accc_notice:harbour-freight-and-beta-0"), None, None) not in g

    links = _graph(exported[f"urn:graph:links:{MV}"])
    recipient = URIRef(BG + "noticeRecipient")
    assert (multi[0], recipient, URIRef("urn:abn:23610005555")) in links
    assert (multi[1], recipient, None) not in links
    assert (single, recipient, None) not in links  # unlinked record: no attribution


def test_notice_details_and_record_url(exported):
    g = _graph(exported["urn:graph:source:accc_notice:2026-11-17"])
    fact = URIRef("urn:fact:accc_notice:southern-cross-advisers-0")
    rec = URIRef("urn:src:accc_notice:southern-cross-advisers-0")
    assert {str(o) for o in g.objects(fact, URIRef(BG + "infringementNumber"))} == {"2526/48", "2526/49"}
    count = g.value(fact, URIRef(BG + "noticeCount"))
    assert count.datatype == URIRef("http://www.w3.org/2001/XMLSchema#integer") and int(count) == 2
    assert str(g.value(fact, URIRef(BG + "legislation"))) == "Australian Consumer Law"
    url = g.value(rec, URIRef(BG + "sourceUrl"))
    assert url.datatype == URIRef("http://www.w3.org/2001/XMLSchema#anyURI")
    assert str(url).endswith("/southern-cross-advisers-0")
    assert str(g.value(rec, URIRef(BG + "foreignReference"))) == "CIF B-00000000"
    other = URIRef("urn:src:accc_notice:harbour-freight-and-beta-0")
    assert (other, URIRef(BG + "foreignReference"), None) not in g
    assert (URIRef("urn:fact:accc_notice:harbour-freight-and-beta-0:1"), URIRef(BG + "noticeCount"), None) not in g


def test_liquidator_affiliation_is_unresolved(exported):
    g = _graph(exported["urn:graph:source:asic_liquidator:2026-11-10"])
    aff = URIRef("urn:fact:asic_liquidator:030471:affiliation")
    assert (aff, RDF.type, URIRef(BG + "Affiliation")) in g
    assert (aff, URIRef(BG + "relationshipKind"), URIRef(BG + "ACTS_FOR")) in g
    assert str(g.value(aff, URIRef(BG + "counterpartyName"))) == "EXAMPLE & PARTNERS"
    assert (aff, URIRef(BG + "aboutRecord"), URIRef("urn:src:asic_liquidator:030471")) in g
    assert (URIRef("urn:fact:asic_liquidator:000000:affiliation"), None, None) not in g  # no firm

    links = _graph(exported[f"urn:graph:links:{MV}"])
    assert (aff, URIRef(BG + "member"), URIRef("urn:party:person:6b1f0c2e9d")) in links
    assert not list(links.triples((None, URIRef(BG + "affiliatedWith"), None)))  # a name never backs a role


def test_licence_end_bounds_from_events(store, tmp_path):
    from bizgraph.pipeline.licence_history import LICENCE_EVENT_DDL

    ex = RdfExporter(store, ONT_DIR)
    g = NamedGraph.source_snapshot("asic_afsl", SNAP)
    no_table = ex.export(g, tmp_path / "before").path.read_text(encoding="utf-8")
    assert "validToNotBefore" not in no_table

    store.execute(LICENCE_EVENT_DDL)
    for source, no, ev_date, after in (
        ("asic_afsl", "512345", date(2026, 11, 17), SNAP),   # gone in the next weekly snapshot
        ("asic_afsl", "512345", date(2027, 1, 5), date(2026, 12, 29)),  # a later disappearance: ignored
        ("asic_credit", "387654", date(2026, 11, 17), SNAP),  # has a stated end date: no bounds
    ):
        store.execute(
            """INSERT INTO licence_event (licence_kind, source, licence_no, event_type, event_date,
                   observed_after, record_iri) VALUES ('AFSL', ?, ?, 'CANCELLED_OR_LAPSED', ?, ?, ?)""",
            [source, no, ev_date, after, f"urn:src:{source}:{no}"],
        )
    afsl = _graph(ex.export(g, tmp_path / "after").path)
    fact = URIRef("urn:fact:asic_afsl:512345")
    assert afsl.value(fact, URIRef(BG + "validToNotBefore")) == Literal(SNAP)
    assert afsl.value(fact, URIRef(BG + "validToNotAfter")) == Literal(date(2026, 11, 16))
    assert (fact, URIRef(BG + "validTo"), None) not in afsl

    credit = _graph(ex.export(NamedGraph.source_snapshot("asic_credit", SNAP), tmp_path / "after").path)
    cfact = URIRef("urn:fact:asic_credit:387654")
    assert (cfact, URIRef(BG + "validToNotBefore"), None) not in credit
    assert credit.value(cfact, URIRef(BG + "validTo")) == Literal(date(2027, 1, 1))

    # the bounded fact still conforms
    files = [r.path for r in ex.export_all(tmp_path / "all") if r.graph.kind != "ontology"]
    report = ShaclValidator("pyshacl", ONT_DIR).validate_files(files)
    assert {v.focus for v in _violations(report)} == CONFLICT_PARTIES


# --------------------------------------------------------------------------- derived licence history


def _add_ended_licence(store):
    """AFSL 300001 seen only in an earlier weekly snapshot, gone in SNAP; 512345 dipped out and is
    back (so it is still in the latest snapshot graph)."""
    from bizgraph.pipeline.licence_history import LICENCE_EVENT_DDL

    earlier = date(2026, 11, 3)
    store.records.upsert([
        _rec("asic_afsl", "300001", "GONE ADVISERS PTY LTD", ids=[(IdScheme.AFSL, "300001")], snap=earlier,
             payload={"licence_number": "300001", "status": "current", "licence_start": "2010-05-01",
                      "authorisations": []}),
    ])
    store.execute(LICENCE_EVENT_DDL)
    for no, ev_date, after in (("300001", SNAP, earlier), ("512345", date(2026, 10, 20), date(2026, 10, 13))):
        store.execute(
            """INSERT INTO licence_event (licence_kind, source, licence_no, event_type, event_date,
                   observed_after, record_iri) VALUES ('AFSL', 'asic_afsl', ?, 'CANCELLED_OR_LAPSED', ?, ?, ?)""",
            [no, ev_date, after, f"urn:src:asic_afsl:{no}"],
        )


def test_published_set_is_latest_per_source_plus_history(store):
    _add_ended_licence(store)
    ex = RdfExporter(store, ONT_DIR)
    iris = [g.iri for g in ex.graphs()]
    afsl = [i for i in iris if i.startswith("urn:graph:source:asic_afsl:")]
    assert afsl == ["urn:graph:source:asic_afsl:2026-11-10"]  # the 2026-11-03 snapshot is not published
    assert iris[-1] == "urn:graph:derived:licence_history"
    # the historical graph is still exportable for audit



def test_historical_snapshot_still_exportable(store, tmp_path):
    _add_ended_licence(store)
    ex = RdfExporter(store, ONT_DIR)
    res = ex.export(NamedGraph.source_snapshot("asic_afsl", date(2026, 11, 3)), tmp_path)
    g = _graph(res.path)
    assert (URIRef("urn:src:asic_afsl:300001"), RDF.type, URIRef(BG + "SourceRecord")) in g


def test_licence_history_graph(store, tmp_path):
    _add_ended_licence(store)
    ex = RdfExporter(store, ONT_DIR)
    res = ex.export(NamedGraph.licence_history(), tmp_path)
    g = _graph(res.path)
    assert res.counts["ended_licences"] == 2 and res.counts["records_described"] == 1

    gone = URIRef("urn:fact:asic_afsl:300001:ended:2026-11-10")
    rec = URIRef("urn:src:asic_afsl:300001")
    assert (gone, RDF.type, URIRef(BG + "Licence")) in g
    assert str(g.value(gone, URIRef(BG + "licenceNumber"))) == "300001"
    assert (gone, URIRef(BG + "licenceKind"), URIRef(BG + "AFSL")) in g
    assert g.value(gone, URIRef(BG + "validToNotBefore")) == Literal(date(2026, 11, 3))
    assert g.value(gone, URIRef(BG + "validToNotAfter")) == Literal(date(2026, 11, 9))
    assert (gone, URIRef(BG + "validTo"), None) not in g
    assert (gone, URIRef(BG + "aboutRecord"), rec) in g
    assert (gone, URIRef("http://www.w3.org/ns/prov#wasDerivedFrom"), rec) in g
    # the vanished record is described here (it is in no published snapshot graph) ...
    assert g.value(rec, URIRef(BG + "snapshotDate")) == Literal(date(2026, 11, 3))
    assert (rec, RDF.type, URIRef(BG + "SourceRecord")) in g
    assert str(g.value(rec, URIRef(BG + "afslNumber"))) == "300001"
    assert str(g.value(rec, URIRef(BG + "nameRaw"))) == "GONE ADVISERS PTY LTD"
    assert g.value(rec, URIRef(BG + "contentHash")) is not None
    # ... the one still in the latest snapshot is not repeated
    back = URIRef("urn:fact:asic_afsl:512345:ended:2026-10-20")
    assert (back, URIRef(BG + "aboutRecord"), URIRef("urn:src:asic_afsl:512345")) in g
    assert (URIRef("urn:src:asic_afsl:512345"), None, None) not in g

    latest = _graph(ex.export(NamedGraph.source_snapshot("asic_afsl", SNAP), tmp_path).path)
    assert (rec, None, None) not in latest


def test_published_set_passes_shacl(store, tmp_path):
    _add_ended_licence(store)
    ex = RdfExporter(store, ONT_DIR)
    files = [r.path for r in ex.export_all(tmp_path) if r.graph.kind != "ontology"]
    assert any(f.name == "derived__licence_history.nt" for f in files)
    report = ShaclValidator("pyshacl", ONT_DIR).validate_files(files)
    assert {v.focus for v in _violations(report)} == CONFLICT_PARTIES


def test_asic_company_published_only_when_referenced(store, tmp_path):
    # Exercise each independent inclusion path, including a trustee with no ACN column.
    references = {"999999991", "999999992", "999999993", "999999994", "999999995", "999999996"}
    store.records.upsert([
        _rec("asic_company", acn, "REFERENCED COMPANY", ids=[(IdScheme.ACN, acn)])
        for acn in sorted(references)
    ] + [
        _rec("asic_afsl", "scope-afsl", ids=[(IdScheme.ACN, "999999992")]),
        _rec("accc_notice", "scope-notice", ids=[(IdScheme.ACN, "999999993")]),
        _rec("gleif_l1", "scope-trust", payload={"trustee_acn": "999999994"}),
    ])
    store.execute("UPDATE party_canonical SET asic_record_id = '999999991' WHERE acn = ?", [SCA_ACN])
    store.execute("INSERT INTO identifier VALUES (?, 'acn', '999999995')", [f"urn:abn:{SCA_ABN}"])
    store.execute("INSERT INTO quarantine (source, record_id, invariant) VALUES "
                  "('asic_company', '999999996', 'ACN_MULTIPLE_ABN')")
    store.records.upsert([_rec("asic_company", "999999990", "UNRELATED HOLDINGS PTY LTD",
                               ids=[(IdScheme.ACN, "999999990")])])
    g = NamedGraph.source_snapshot("asic_company", SNAP)
    trimmed = _graph(RdfExporter(store, ONT_DIR).export(g, tmp_path / "trim").path)
    full = _graph(RdfExporter(store, ONT_DIR, all_asic_company=True).export(g, tmp_path / "full").path)
    kept = URIRef(f"urn:src:asic_company:{SCA_ACN}")  # the ACN of a canonical party
    other = URIRef("urn:src:asic_company:999999990")
    assert (kept, RDF.type, URIRef(BG + "SourceRecord")) in trimmed
    assert (other, None, None) not in trimmed
    assert (other, RDF.type, URIRef(BG + "SourceRecord")) in full
    for acn in references:
        assert (URIRef(f"urn:src:asic_company:{acn}"), RDF.type, URIRef(BG + "SourceRecord")) in trimmed
