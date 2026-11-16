"""Ontology tests: schema and shapes parse, shapes only reference terms the
schema defines, the example data produces exactly the deliberate violations,
and each invariant in shapes.ttl actually fires on a minimal bad input.

Validation runs over example data + schema merged, which mirrors production:
Fuseki validates the union of the source, canonical, one links graph and
urn:graph:ontology (sh:class needs rdfs:subClassOf, the role checks need
rdfs:subPropertyOf).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pyshacl import validate
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, SKOS

ONT_DIR = Path(__file__).resolve().parents[1] / "ontology"
BG = Namespace("https://w3id.org/bizgraph/ont#")
SH = Namespace("http://www.w3.org/ns/shacl#")

ACN_CONFLICT_PARTIES = {URIRef("urn:abn:23610005555"), URIRef("urn:abn:55610004441")}
SCA = URIRef("urn:abn:38610001119")
PERSON = URIRef("urn:party:person:6b1f0c2e9d")


@pytest.fixture(scope="module")
def schema() -> Graph:
    return Graph().parse(ONT_DIR / "schema.ttl")


@pytest.fixture(scope="module")
def shapes() -> Graph:
    return Graph().parse(ONT_DIR / "shapes.ttl")


@pytest.fixture(scope="module")
def examples() -> Graph:
    return Graph().parse(ONT_DIR / "examples.ttl")


def _run(data: Graph, schema: Graph, shapes: Graph) -> tuple[bool, list[dict]]:
    merged = Graph()
    for g in (data, schema):
        for t in g:
            merged.add(t)
    conforms, report, _ = validate(
        merged, shacl_graph=shapes, inference="none", advanced=True, allow_warnings=False
    )
    results = []
    for r in report.subjects(RDF.type, SH.ValidationResult):
        results.append(
            {
                "focus": report.value(r, SH.focusNode),
                "severity": report.value(r, SH.resultSeverity),
                "component": report.value(r, SH.sourceConstraintComponent),
                "path": report.value(r, SH.resultPath),
                "message": str(report.value(r, SH.resultMessage)),
            }
        )
    return conforms, results


def _clean(examples: Graph) -> Graph:
    """Example data with the deliberate ACN conflict removed."""
    g = Graph()
    for t in examples:
        g.add(t)
    g.remove((URIRef("urn:abn:55610004441"), BG.acn, Literal("610005555")))
    return g


# --------------------------------------------------------------------------
# Parsing and structure
# --------------------------------------------------------------------------


def test_files_have_no_em_dash():
    for p in ONT_DIR.glob("*"):
        if p.is_file():
            assert chr(0x2014) not in p.read_text(encoding="utf-8"), p.name


def test_schema_is_owl_ontology(schema: Graph):
    assert (URIRef("https://w3id.org/bizgraph/ont"), RDF.type, OWL.Ontology) in schema
    questions = set(schema.subjects(RDF.type, BG.DrivingQuestion))
    assert questions == {BG.Q1, BG.Q2, BG.Q3, BG.Q4, BG.Q5}


def test_core_classes_exist_and_are_motivated(schema: Graph):
    core = [
        "Party", "Organisation", "Person", "Fact", "Relationship", "Licence", "Ban",
        "Ownership", "InfringementNotice", "ProductSponsorship", "SourceRecord",
        "Link", "Abstention",
    ]
    for name in core:
        cls = BG[name]
        assert (cls, RDF.type, OWL.Class) in schema, name
        assert schema.value(cls, BG.motivatedBy) is not None, f"{name} has no bg:motivatedBy"


def test_organisation_and_person_are_disjoint(schema: Graph):
    found = False
    for adc in schema.subjects(RDF.type, OWL.AllDisjointClasses):
        members = set(schema.items(schema.value(adc, OWL.members)))
        if {BG.Organisation, BG.Person} <= members:
            found = True
    assert found


def test_no_owl_keys(schema: Graph):
    """Uniqueness lives in SHACL. OWL keys would infer owl:sameAs, i.e. merge."""
    assert not list(schema.subject_objects(OWL.hasKey))
    assert not list(schema.subjects(RDF.type, OWL.InverseFunctionalProperty))


def test_match_type_scheme(schema: Graph, shapes: Graph):
    expected = {
        "EXACT_ABN", "EXACT_ACN", "EXACT_LEI", "EXACT_LICENCE_NO",
        "NAME_NORMALISED_EXACT", "NAME_FUZZY", "NAME_SEMANTIC", "WIKIDATA_ALIAS",
    }
    concepts = set(schema.subjects(RDF.type, BG.MatchType))
    assert {str(schema.value(c, SKOS.notation)) for c in concepts} == expected
    for c in concepts:
        assert (c, SKOS.inScheme, BG.MatchTypeScheme) in schema
        assert schema.value(c, SKOS.broader) in {BG.ExactPath, BG.SemanticPath}
    # The sh:in list in LinkShape must be exactly the scheme.
    in_lists = [
        set(shapes.items(lst))
        for ps in shapes.objects(URIRef("https://w3id.org/bizgraph/shapes#LinkShape"), SH.property)
        if (lst := shapes.value(ps, SH["in"])) is not None
    ]
    assert concepts in in_lists


_BG_TERM = re.compile(r"\bbg:([A-Za-z_][A-Za-z0-9_]*)")


def test_every_term_in_shapes_is_defined_in_schema(schema: Graph, shapes: Graph):
    referenced: set[URIRef] = set()
    for t in shapes:
        for node in t:
            if isinstance(node, URIRef) and str(node).startswith(str(BG)):
                referenced.add(node)
            if isinstance(node, Literal):  # SPARQL constraint text
                referenced |= {BG[m] for m in _BG_TERM.findall(str(node))}
    defined = set(schema.subjects())
    missing = sorted(str(r) for r in referenced if r not in defined)
    assert not missing, f"shapes reference undefined terms: {missing}"


def test_every_bg_predicate_in_examples_is_defined(schema: Graph, examples: Graph):
    defined = set(schema.subjects())
    used = {p for p in examples.predicates() if str(p).startswith(str(BG))}
    used |= {o for o in examples.objects(None, RDF.type) if str(o).startswith(str(BG))}
    missing = sorted(str(u) for u in used if u not in defined)
    assert not missing, missing


# --------------------------------------------------------------------------
# Example data
# --------------------------------------------------------------------------


def test_examples_report_exactly_the_acn_conflict(examples, schema, shapes):
    conforms, results = _run(examples, schema, shapes)
    assert not conforms
    assert {r["focus"] for r in results} == ACN_CONFLICT_PARTIES
    assert all(r["component"] == SH.SPARQLConstraintComponent for r in results)
    assert all("ACN 610005555" in r["message"] for r in results)
    assert all(r["severity"] == SH.Violation for r in results)


def test_examples_without_conflict_conform(examples, schema, shapes):
    conforms, results = _run(_clean(examples), schema, shapes)
    assert conforms, results


def test_example_contains_required_cases(examples):
    assert (SCA, BG.abn, None) in examples and (SCA, BG.acn, None) in examples
    lic = URIRef("urn:fact:asic_afsl:512345")
    assert examples.value(lic, BG.licenceStatus) == Literal("Cancelled")
    assert examples.value(lic, BG.validTo) is not None
    assert (None, BG.bannedParty, PERSON) in examples
    assert (PERSON, RDF.type, BG.Person) in examples
    assert len(set(examples.subjects(RDF.type, BG.Abstention))) >= 1
    assert len(set(examples.subjects(RDF.type, BG.Link))) >= 1


def test_ownership_chain_has_cycle(examples):
    """Follow bg:owner from SCA; must revisit a node within 3 hops."""
    parent = {}
    for o in examples.subjects(RDF.type, BG.Ownership):
        if examples.value(o, BG.relationshipKind) == BG.IS_DIRECTLY_CONSOLIDATED_BY:
            parent[examples.value(o, BG.owned)] = examples.value(o, BG.owner)
    seen, node, depth = [SCA], SCA, 0
    while node in parent and depth < 10:
        node = parent[node]
        depth += 1
        if node in seen:
            break
        seen.append(node)
    assert node in seen and depth <= 4
    assert len(seen) == 3  # SCA, Beta, Gamma


# --------------------------------------------------------------------------
# Each invariant fires on a minimal bad input (mutation tests)
# --------------------------------------------------------------------------

_PREFIX = """
@prefix bg: <https://w3id.org/bizgraph/ont#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
"""

MUTATIONS = {
    "abn_format": ("<urn:abn:38610001119> bg:abn '3861000111' .", "urn:abn:38610001119"),
    "acn_format": ("<urn:src:abr:38610001119> bg:acn '61000111' .", "urn:src:abr:38610001119"),
    "lei_format": ("<urn:lei:9845EXAMPLE000000211> bg:lei '9845example000000211' .",
                   "urn:lei:9845EXAMPLE000000211"),
    "two_abns_on_party": ("<urn:abn:38610001119> bg:abn '18610002223' .", "urn:abn:38610001119"),
    "abn_used_by_two_parties": ("<urn:lei:9845EXAMPLE000000308> bg:abn '38610001119' .",
                                "urn:lei:9845EXAMPLE000000308"),
    "lei_used_by_two_parties": ("<urn:lei:9845EXAMPLE000000308> bg:lei '9845EXAMPLE000000211' .",
                                "urn:lei:9845EXAMPLE000000308"),
    "ownership_pct_over_100": (
        "<urn:fact:gleif_l2:9845EXAMPLE000000308-DIRECT> bg:ownershipPercentage 120.0 .",
        "urn:fact:gleif_l2:9845EXAMPLE000000308-DIRECT"),
    "ownership_pct_negative": (
        "<urn:fact:gleif_l2:9845EXAMPLE000000308-DIRECT> bg:ownershipPercentage -1.0 .",
        "urn:fact:gleif_l2:9845EXAMPLE000000308-DIRECT"),
    "valid_from_after_valid_to": (
        "<urn:fact:asic_banned:BD-0042> bg:validFrom '2031-01-01'^^xsd:date .",
        "urn:fact:asic_banned:BD-0042"),
    "link_two_parties": (
        "<urn:link:m-2026.11.1:asic_afsl:512345> bg:party <urn:lei:9845EXAMPLE000000211> .",
        "urn:link:m-2026.11.1:asic_afsl:512345"),
    "link_two_source_records": (
        "<urn:link:m-2026.11.1:asic_afsl:512345> bg:sourceRecord <urn:src:abr:38610001119> .",
        "urn:link:m-2026.11.1:asic_afsl:512345"),
    "link_no_match_type": (
        "<urn:link:x> a bg:Link ; bg:sourceRecord <urn:src:accc:IN-2026-017> ; "
        "bg:party <urn:abn:38610001119> ; bg:confidence 0.5 ; bg:evidence '{}' ; "
        "bg:matcherVersion 'm-x' .",
        "urn:link:x"),
    "link_unknown_match_type": (
        "<urn:link:m-2026.11.1:asic_company:610001119> bg:matchType bg:NO_CANDIDATE .",
        "urn:link:m-2026.11.1:asic_company:610001119"),
    "link_confidence_over_1": (
        "<urn:link:x> a bg:Link ; bg:sourceRecord <urn:src:accc:IN-2026-017> ; "
        "bg:party <urn:abn:38610001119> ; bg:matchType bg:NAME_FUZZY ; bg:confidence 1.5 ; "
        "bg:evidence '{}' ; bg:matcherVersion 'm-x' .",
        "urn:link:x"),
    "ban_two_parties": (
        "<urn:fact:asic_banned:BD-0042> bg:bannedParty <urn:abn:38610001119> .",
        "urn:fact:asic_banned:BD-0042"),
    "ban_two_records": (
        "<urn:fact:asic_banned:BD-0042> bg:aboutRecord <urn:src:accc:IN-2026-017> .",
        "urn:fact:asic_banned:BD-0042"),
    "ban_without_record": (
        "<urn:fact:x> a bg:Ban ; bg:banType 'Disqualified director' ; "
        "prov:wasDerivedFrom <urn:src:asic_banned:BD-0042> .",
        "urn:fact:x"),
    "role_without_backing_link": (
        "<urn:fact:accc:IN-2026-017> bg:noticeRecipient <urn:abn:38610001119> .",
        "urn:fact:accc:IN-2026-017"),
    "two_decisions_same_record_same_version": (
        "<urn:abstention:dup> a bg:Abstention ; bg:sourceRecord <urn:src:asic_afsl:512345> ; "
        "bg:abstainReason bg:AMBIGUOUS ; bg:evidence '{}' ; bg:matcherVersion 'm-2026.11.1' .",
        "urn:abstention:dup"),
    "licence_overlapping_holders": (
        "<urn:fact:x> a bg:Licence ; bg:licenceNumber '512345' ; bg:licenceKind bg:AFSL ; "
        "bg:validFrom '2020-01-01'^^xsd:date ; bg:aboutRecord <urn:src:abr:23610005555> ; "
        "prov:wasDerivedFrom <urn:src:abr:23610005555> ; bg:licensee <urn:abn:23610005555> . "
        "<urn:link:y> a bg:Link ; bg:sourceRecord <urn:src:abr:23610005555> ; "
        "bg:party <urn:abn:23610005555> ; bg:matchType bg:EXACT_ABN ; bg:confidence 1.0 ; "
        "bg:evidence '{}' ; bg:matcherVersion 'm-2026.11.1' .",
        "urn:fact:x"),
    "party_without_provenance": (
        "<urn:abn:12884213570> a bg:Person ; bg:name 'SAM SOLE TRADER' ; bg:abn '12884213570' .",
        "urn:abn:12884213570"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_invariant_fires(name, examples, schema, shapes):
    ttl, focus = MUTATIONS[name]
    g = _clean(examples)
    g.parse(data=_PREFIX + ttl, format="turtle")
    conforms, results = _run(g, schema, shapes)
    assert not conforms
    focuses = {str(r["focus"]) for r in results}
    assert focus in focuses, (name, results)


def test_untyped_party_is_a_warning_only(examples, schema, shapes):
    g = _clean(examples)
    g.parse(
        data=_PREFIX + "<urn:party:x> a bg:Party ; bg:name 'X' ; "
        "prov:wasDerivedFrom <urn:src:accc:IN-2026-017> .",
        format="turtle",
    )
    _, results = _run(g, schema, shapes)
    mine = [r for r in results if str(r["focus"]) == "urn:party:x"]
    assert mine and all(r["severity"] == SH.Warning for r in mine)
