"""Resolution tests on synthetic canonical data (no dependency on data/bizgraph.duckdb)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from bizgraph.domain.models import AbstainReason, Identifier, IdScheme, MatchType, PartyType, SourceRecord
from bizgraph.normalise.identifiers import AbnValidator, LeiValidator
from bizgraph.normalise.names import NameNormaliser
from bizgraph.resolution import (
    Abstention,
    FeatureExtractor,
    Link,
    Matcher,
    Reference,
    ReferenceParser,
    ThresholdPolicy,
)
from bizgraph.resolution.features import FeatureExtractor as _FE
from bizgraph.store.duckdb_store import DuckDBStore

NAMES = NameNormaliser()


# --------------------------------------------------------------------------- id helpers


def acn(base8: str) -> str:
    w = (8, 7, 6, 5, 4, 3, 2, 1)
    total = sum(int(c) * x for c, x in zip(base8, w))
    return base8 + str((10 - total % 10) % 10)


def abn_for(tail9: str) -> str:
    v = AbnValidator()
    for p in range(10, 100):
        if v.is_valid(f"{p}{tail9}"):
            return f"{p}{tail9}"
    raise AssertionError("no valid ABN prefix")


def lei(base18: str) -> str:
    numeric = "".join(str(int(c, 36)) for c in base18 + "00")
    check = 98 - int(numeric) % 97
    out = f"{base18}{check:02d}"
    assert LeiValidator().is_valid(out)
    return out


CBA_ABN = "48123123124"  # real CBA ABN, checksum-valid
CBA_ACN = "123123124"
CSC_ACN = acn("10000001")
CSC_ABN = abn_for(CSC_ACN)
ACME_ACN = acn("20000002")
ACME_ABN = abn_for(ACME_ACN)
OTHER_ABN = abn_for(acn("30000003"))
SHADY_ACN = acn("40000004")
SHADY2_ACN = acn("40000005")
GUM1_ABN = abn_for(acn("50000005"))
GUM2_ABN = abn_for(acn("50000006"))
SMITH_ABN = abn_for(acn("60000006"))
LEI_A = lei("549300AAAAAAAAAAAA")
LEI_B = lei("549300BBBBBBBBBBBB")
OCEAN_ABN = abn_for(acn("70000007"))
KARRI_ABN = abn_for(acn("80000008"))
KOALA_ABN = abn_for(acn("90000009"))

PARTIES = [
    # key, type, name, abn, acn, lei, state, quarantined
    (f"urn:abn:{CBA_ABN}", "organisation", "COMMONWEALTH BANK OF AUSTRALIA", CBA_ABN, CBA_ACN, None, "NSW", False),
    (f"urn:abn:{CSC_ABN}", "organisation", "COMMONWEALTH SUPERANNUATION CORPORATION", CSC_ABN, CSC_ACN, None, "ACT", False),
    (f"urn:abn:{ACME_ABN}", "organisation", "ACME PLUMBING PTY LTD", ACME_ABN, ACME_ACN, None, "WA", False),
    (f"urn:acn:{SHADY_ACN}", "organisation", "SHADY VENTURES PTY LTD", None, SHADY_ACN, None, "WA", True),
    (f"urn:abn:{GUM1_ABN}", "organisation", "BLUE GUM CONSULTING PTY LTD", GUM1_ABN, None, None, "WA", False),
    (f"urn:abn:{GUM2_ABN}", "organisation", "BLUE GUM CONSULTING PTY LTD", GUM2_ABN, None, None, "WA", False),
    (f"urn:abn:{SMITH_ABN}", "person", "SMITH, JOHN", SMITH_ABN, None, None, "WA", False),
    (f"urn:abn:{OCEAN_ABN}", "organisation", "OCEAN PEARL TRADING PTY LTD", OCEAN_ABN, None, LEI_A, "WA", False),
    (f"urn:abn:{KOALA_ABN}", "organisation", "The Trustee for Koala Holdings", KOALA_ABN, None, None, "WA", False),
    (f"urn:abn:{KARRI_ABN}", "organisation", "KARRI TIMBER MILLING JOINERY CABINET WORKS PTY LTD", KARRI_ABN, None,
     None, "WA", False),
]


def _norm(name: str, ptype: str) -> str:
    n = NAMES.normalise_person(name) if ptype == "person" else NAMES.normalise(name)
    return n.norm


def make_store() -> DuckDBStore:
    s = DuckDBStore(":memory:")
    for key, ptype, name, abn, acn_, lei_, state, q in PARTIES:
        s.execute(
            """INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, abn, acn, lei, state,
                                            source, record_id, quarantined)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'abr', ?, ?)""",
            [key, ptype, name, _norm(name, ptype), abn, acn_, lei_, state, key, q],
        )
        for scheme, value in (("abn", abn), ("acn", acn_), ("lei", lei_)):
            if value and not q:
                s.execute("INSERT INTO identifier VALUES (?, ?, ?)", [key, scheme, value])
    s.execute(
        "INSERT INTO alias VALUES (?, 'CBA', 'CBA', 'trading_name', 'abr', ?)",
        [f"urn:abn:{CBA_ABN}", CBA_ABN],
    )
    s.execute(
        "INSERT INTO alias VALUES (?, 'ACME PIPES', 'ACME PIPES', 'business_name', 'abr', ?)",
        [f"urn:abn:{ACME_ABN}", ACME_ABN],
    )
    s.quarantine.add("asic_company", SHADY_ACN, "NAME_MISMATCH", "synthetic")
    s.execute("UPDATE quarantine SET canonical_key = ?", [f"urn:acn:{SHADY_ACN}"])
    return s


@pytest.fixture()
def store() -> DuckDBStore:
    return make_store()


@pytest.fixture()
def matcher(store: DuckDBStore) -> Matcher:
    return Matcher(store)


def ref(name: str, *, ids=(), ptype=PartyType.ORGANISATION, source="test_src", rid="r1", state=None,
        lei_status=None) -> Reference:
    norm = NAMES.normalise_person(name) if ptype is PartyType.PERSON else NAMES.normalise(name)
    return Reference(name, norm, tuple(Identifier(s, v) for s, v in ids), ptype, state, source, rid, lei_status)


# --------------------------------------------------------------------------- parser


def test_parser_extracts_embedded_identifiers() -> None:
    p = ReferenceParser()
    r = p.parse("Commonwealth Bank of Aust, ABN 48 123 123 124")
    assert r.ids("abn") == [CBA_ABN]
    assert r.name_norm == "COMMONWEALTH BANK OF AUST"
    r = p.parse(f"Acme Plumbing Pty Ltd (ACN {ACME_ACN[:3]} {ACME_ACN[3:6]} {ACME_ACN[6:]}) AFSL 123456 WA")
    assert r.ids("acn") == [ACME_ACN] and r.ids("afsl") == ["123456"]
    assert r.state == "WA" and r.name_norm == "ACME PLUMBING"
    assert r.party_type_hint is PartyType.ORGANISATION
    r = p.parse(f"Ocean Pearl LEI {LEI_B}")
    assert r.ids("lei") == [LEI_B]
    # an unlabelled 9-digit number is never taken as an ACN; an invalid ABN is noted, not used
    r = p.parse("Foo Pty Ltd 123 456 789, ABN 11 111 111 111")
    assert r.identifiers == () and any(n.startswith("invalid_abn") for n in r.notes)


# --------------------------------------------------------------------------- named test case


def test_cba_vs_csc_never_links(store: DuckDBStore, matcher: Matcher) -> None:
    # Remove CBA so CSC is the only "Commonwealth" party: the semantic path must still refuse.
    store.execute("DELETE FROM party_canonical WHERE canonical_key = ?", [f"urn:abn:{CBA_ABN}"])
    store.execute("DELETE FROM alias")
    m = Matcher(store)
    d = m.match(ref("Commonwealth Bank of Australia", source="accc_notice"))
    assert isinstance(d, Abstention)
    csc = next(r for r in d.ranked if r.canonical_key == f"urn:abn:{CSC_ABN}")
    assert not csc.eligible and "BANK" in csc.veto
    assert csc.features["distinctive_missing"] == ["BANK"]
    # Even a perfect embedding score cannot rescue it: the token gate fires first.
    from bizgraph.resolution.decision import StoredCandidate, arbitrate
    from bizgraph.resolution.features import FeatureVector

    fv = FeatureVector.from_dict(csc.features)
    fv.embedding_cosine = 0.99
    forced = arbitrate({"source": "test_src", "record_id": "x", "party_type_hint": "organisation"},
                       [StoredCandidate(csc.canonical_key, ["block_fts"], {}, fv,
                                        {"exact": 0.0, "fuzzy": csc.scores["fuzzy"], "semantic": 0.99})],
                       ThresholdPolicy())
    assert isinstance(forced, Abstention) and forced.reason is AbstainReason.BELOW_THRESHOLD


def test_cba_resolves_to_cba_not_csc(matcher: Matcher) -> None:
    d = matcher.match(ref("Commonwealth Bank of Australia"))
    assert isinstance(d, Link)
    assert d.canonical_key == f"urn:abn:{CBA_ABN}" and d.match_type is MatchType.NAME_NORMALISED_EXACT


def test_abn_in_text_resolves_exactly(matcher: Matcher) -> None:
    d = matcher.resolve("Commonwealth Bank of Aust, ABN 48 123 123 124")
    assert isinstance(d, Link)
    assert d.match_type is MatchType.EXACT_ABN and d.confidence == 1.0
    assert d.canonical_key == f"urn:abn:{CBA_ABN}"
    assert "res_party_identifier" in d.evidence.query_text["exact_identifier"]
    assert CBA_ABN in d.evidence.query_text["exact_identifier"]


# --------------------------------------------------------------------------- vetoes


def test_identifier_conflict_vetoes_name_path(matcher: Matcher) -> None:
    # Name matches ACME exactly, but the reference's ABN is someone else's.
    d = matcher.match(ref("Acme Plumbing Pty Ltd", ids=[(IdScheme.ABN, OTHER_ABN)]))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.IDENTIFIER_CONFLICT


def test_weak_vetoed_candidate_is_below_threshold_not_conflict(matcher: Matcher) -> None:
    # The only candidate disagrees on ABN but is a weak name match anyway: the queue should
    # say "nothing good enough", not "conflict" (the conflict blocked nothing).
    d = matcher.match(ref("Acme Drainage Pty Ltd", ids=[(IdScheme.ABN, OTHER_ABN)]))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.BELOW_THRESHOLD
    assert "identifier conflict" in d.explanation


def test_identifier_conflict_between_schemes(matcher: Matcher) -> None:
    # ABN says ACME, ACN says CSC: two parties -> conflict, never a pick.
    d = matcher.match(ref("Acme Plumbing", ids=[(IdScheme.ABN, ACME_ABN), (IdScheme.ACN, CSC_ACN)]))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.IDENTIFIER_CONFLICT


def test_person_vs_organisation_veto(matcher: Matcher) -> None:
    d = matcher.match(ref("ACME PLUMBING", ptype=PartyType.PERSON))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.PARTY_TYPE_CONFLICT
    d = matcher.match(ref("Smith, John", ids=[(IdScheme.ABN, ACME_ABN)], ptype=PartyType.PERSON))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.PARTY_TYPE_CONFLICT
    # A person is never linked on a name alone, even to a person party with that exact name.
    d = matcher.match(ref("SMITH, JOHN", ptype=PartyType.PERSON))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.BELOW_THRESHOLD


def test_quarantined_target(matcher: Matcher) -> None:
    d = matcher.match(ref("Shady Ventures Pty Ltd", ids=[(IdScheme.ACN, SHADY_ACN)]))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.QUARANTINED_TARGET
    d = matcher.match(ref("Shady Ventures Pty Ltd"))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.QUARANTINED_TARGET


def test_ambiguity_margin(matcher: Matcher) -> None:
    d = matcher.match(ref("Blue Gum Consulting Pty Ltd"))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.AMBIGUOUS
    assert {r.canonical_key for r in d.ranked[:2]} == {f"urn:abn:{GUM1_ABN}", f"urn:abn:{GUM2_ABN}"}


def test_duplicate_lei_is_not_a_conflict(matcher: Matcher) -> None:
    ids = [(IdScheme.LEI, LEI_B), (IdScheme.ABN, OCEAN_ABN)]
    d = matcher.match(ref("Ocean Pearl Trading Pty Ltd", ids=ids, lei_status="DUPLICATE"))
    assert isinstance(d, Link) and d.match_type is MatchType.EXACT_ABN
    d = matcher.match(ref("Ocean Pearl Trading Pty Ltd", ids=ids, lei_status="ISSUED"))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.IDENTIFIER_CONFLICT


def test_annulled_lei_is_ignored() -> None:
    rec = SourceRecord("gleif_l1", LEI_B, date(2026, 11, 1), {"lei_status": "ANNULLED"}, "X PTY LTD",
                       identifiers=(Identifier(IdScheme.LEI, LEI_B),))
    r = Reference.from_record(rec)
    assert r.identifiers == () and "annulled_lei_ignored" in r.notes


# --------------------------------------------------------------------------- thresholds


def test_banned_org_stricter_threshold(matcher: Matcher) -> None:
    # An informal name missing one word of a long company name: fuzzy about 0.91, enough for an
    # ordinary source (0.90), not for ACCC (0.97); on the banned register (a register: the name is
    # a legal name) the extra candidate word makes the candidate ineligible outright.
    name = "Karri Timber Milling Joinery Cabinet"
    ordinary = matcher.match(ref(name, source="test_src"))
    assert isinstance(ordinary, Link) and ordinary.match_type is MatchType.NAME_FUZZY
    assert 0.90 <= ordinary.confidence < 0.97
    for src in ("asic_banned_org", "accc_notice"):
        strict = matcher.match(ref(name, source=src))
        assert isinstance(strict, Abstention) and strict.reason is AbstainReason.BELOW_THRESHOLD


def test_stated_state_mismatch_penalty(matcher: Matcher) -> None:
    d = matcher.match(ref("Acme Plumbing Pty Ltd", state="VIC", source="asic_afsl"))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.BELOW_THRESHOLD
    assert d.best_score == 0.85


def test_unknown_type_gets_strict_floor() -> None:
    p = ThresholdPolicy()
    assert p.threshold("asic_afsl", "organisation") == 0.90
    assert p.threshold("asic_afsl", "unknown") == 0.95
    assert p.threshold("asic_banned_org", "organisation") == 0.97


# --------------------------------------------------------------------------- batch + redecide


def _load_source(store: DuckDBStore) -> None:
    recs = [
        ("1", "COMMONWEALTH BANK OF AUSTRALIA", [(IdScheme.ABN, CBA_ABN)], "organisation", {}),
        ("2", "ACME PLUMBING PTY LTD", [], "organisation", {"state": "VIC"}),
        ("3", "COMMONWEALTH BANK", [], "organisation", {}),
        ("4", "BLUE GUM CONSULTING PTY LTD", [], "organisation", {}),
        ("5", "ACME PLUMBING PTY LTD", [(IdScheme.ABN, OTHER_ABN)], "organisation", {}),
        ("6", "NOTHING LIKE IT PTY LTD", [], "organisation", {}),
        ("7", "OCEAN PEARL TRADNG PTY LTD", [], "organisation", {}),
        ("8", "SMITH, JOHN", [], "person", {}),
    ]
    store.records.upsert([
        SourceRecord("test_src", rid, date(2026, 11, 1), {"name": n, **extra}, n, None, PartyType(pt),
                     tuple(Identifier(s, v) for s, v in ids))
        for rid, n, ids, pt, extra in recs
    ])


def test_batch_persists_every_candidate_and_labels_never_mix(store: DuckDBStore, matcher: Matcher) -> None:
    _load_source(store)
    s = matcher.match_batch("test_src")
    assert s.records == 8 and s.links + s.abstentions == 8
    cand = store.query("SELECT * FROM candidate WHERE run_id = ?", [s.run_id])
    assert len(cand) == s.candidates and len(cand) > 8
    for c in cand:
        blob = json.loads(c["features"])
        assert {"features", "scores", "query_text", "ref"} <= set(blob)
        assert blob["query_text"].startswith("SELECT")
    links = store.links.by_version(s.matcher_version)
    assert len(links) == s.links
    for lk in links:
        ev = json.loads(lk["evidence"])
        mt = MatchType(lk["match_type"])
        if mt.name.startswith("EXACT_"):
            assert ev["features"]["identifier_match"] and ev["path"] == "exact" and lk["confidence"] == 1.0
        elif mt is MatchType.NAME_NORMALISED_EXACT:
            assert ev["features"]["name_exact_unique"] and not ev["features"]["identifier_match"]
            assert ev["path"] == "exact"
        else:
            assert not ev["features"]["identifier_match"] and ev["path"] == "semantic"
    by_rid = {lk["record_id"]: lk for lk in links}
    assert by_rid["1"]["match_type"] == "EXACT_ABN"
    abst = {a["record_id"]: a["reason"] for a in store.abstentions.by_version(s.matcher_version)}
    # 'COMMONWEALTH BANK' carries every distinctive token of CBA's name: a fuzzy link, not CSC.
    assert by_rid["3"]["canonical_key"] == f"urn:abn:{CBA_ABN}" and by_rid["3"]["match_type"] == "NAME_FUZZY"
    # 'TRADNG' is a typo of the generic TRADING, so it does not block the token gate.
    assert by_rid["7"]["canonical_key"] == f"urn:abn:{OCEAN_ABN}"
    assert abst["4"] == "AMBIGUOUS" and abst["5"] == "IDENTIFIER_CONFLICT"
    assert abst["6"] == "NO_CANDIDATE" and abst["8"] == "BELOW_THRESHOLD"
    # Rerunning the same version is idempotent.
    s2 = matcher.match_batch("test_src")
    assert s2.candidates == s.candidates
    assert store.query("SELECT count(*) AS n FROM link WHERE matcher_version = ?", [s.matcher_version])[0]["n"] == s.links


def test_strip_identifiers_runs_name_path_under_own_version(store: DuckDBStore, matcher: Matcher) -> None:
    _load_source(store)
    full = matcher.match_batch("test_src")
    names = matcher.match_batch("test_src", strip_identifiers=True)
    assert names.matcher_version != full.matcher_version
    assert "EXACT_ABN" not in names.by_match_type
    links = {lk["record_id"]: lk for lk in store.links.by_version(names.matcher_version)}
    assert links["1"]["canonical_key"] == f"urn:abn:{CBA_ABN}"  # found by name instead
    assert "5" in links  # no identifier left to veto the ACME name match
    assert len(store.links.by_version(full.matcher_version)) == full.links  # untouched


def test_redecide_flips_without_regenerating(store: DuckDBStore, matcher: Matcher, monkeypatch) -> None:
    _load_source(store)
    s = matcher.match_batch("test_src")
    before = store.query("SELECT count(*) AS n FROM candidate")[0]["n"]

    def boom(*a, **k):  # any feature extraction or candidate generation during redecide fails
        raise AssertionError("redecide must not regenerate or rescore")

    monkeypatch.setattr(_FE, "extract", boom)
    monkeypatch.setattr(Matcher, "candidates", boom)
    monkeypatch.setattr(Matcher, "_batch_generate", boom)

    # A looser policy that allows person name links: records 2 and 8 flip to links; the Blue Gum
    # exact tie stays AMBIGUOUS even with a zero margin (ties never link).
    loose = ThresholdPolicy(default=0.80, min_margin=0.0, person_name_links=True)
    r = matcher.redecide(s.run_id, loose)
    assert r.matcher_version != s.matcher_version and r.matcher_version.startswith("mr-")
    assert store.query("SELECT count(*) AS n FROM candidate")[0]["n"] == before
    assert r.records == s.records
    # record 2 (stated VIC vs WA party, 0.85) and record 8 (person name link now allowed) flip
    assert r.diff == {"links_added": 2, "links_dropped": 0, "links_retargeted": 0, "links_unchanged": s.links}
    flipped = {lk["record_id"]: lk for lk in store.links.by_version(r.matcher_version)}
    assert flipped["8"]["canonical_key"] == f"urn:abn:{SMITH_ABN}"
    assert {a["record_id"]: a["reason"] for a in store.abstentions.by_version(r.matcher_version)}["4"] == "AMBIGUOUS"
    strict = ThresholdPolicy(default=0.999, unknown_type_threshold=0.999, name_exact_confidence=0.95)
    r2 = matcher.redecide(s.run_id, strict)
    new_links = store.links.by_version(r2.matcher_version)
    assert all(lk["match_type"].startswith("EXACT_") for lk in new_links)
    assert r2.diff["links_dropped"] >= 1
    mv = store.matcher_versions.get(r2.matcher_version)
    pol = json.loads(mv["policy"]) if isinstance(mv["policy"], str) else mv["policy"]
    assert pol["candidates_run_id"] == s.run_id and pol["policy"]["default"] == 0.999


def test_cba_csc_feature_vector_is_reported(store: DuckDBStore) -> None:
    fe = FeatureExtractor()
    m = Matcher(store)
    party = m._party_views({f"urn:abn:{CSC_ABN}"})[f"urn:abn:{CSC_ABN}"]
    fv = fe.extract(ref("Commonwealth Bank of Australia"), party)
    assert fv.distinctive_coverage == 0.5 and fv.distinctive_missing == ["BANK"]
    assert fv.distinctive_extra == ["SUPERANNUATION"]


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("sentence_transformers") is None,
    reason="sentence-transformers not installed",
)
def test_semantic_path_with_embeddings(store: DuckDBStore) -> None:
    from bizgraph.resolution import Embedder

    emb = Embedder.load()
    if emb is None:
        pytest.skip("embedding model unavailable")
    # The raw measurement exists (the extractor can compute it) ...
    m0 = Matcher(store)
    party = m0._party_views({f"urn:abn:{CSC_ABN}"})[f"urn:abn:{CSC_ABN}"]
    fv = FeatureExtractor(embedder=emb).extract(ref("Commonwealth Bank of Australia"), party)
    assert fv.embedding_cosine is not None and fv.distinctive_missing == ["BANK"]
    # ... but the matcher only spends embeddings where the semantic path may apply (token gate).
    m = Matcher(store, embedder=emb)
    d = m.match(ref("The Commonwealth Bank of Australia"))
    cba = next(r for r in d.ranked if r.canonical_key == f"urn:abn:{CBA_ABN}")
    assert cba.features["embedding_cosine"] is not None
    store.execute("DELETE FROM party_canonical WHERE canonical_key = ?", [f"urn:abn:{CBA_ABN}"])
    store.execute("DELETE FROM alias")
    m = Matcher(store, embedder=emb)
    d = m.match(ref("Commonwealth Bank of Australia"))
    assert isinstance(d, Abstention)
    csc = next(r for r in d.ranked if r.canonical_key == f"urn:abn:{CSC_ABN}")
    assert csc.features["embedding_cosine"] is None and not csc.eligible


# --------------------------------------------------------------------------- v2 rules


def test_generic_reference_token_gates(matcher: Matcher) -> None:
    # SECURITIES is a generic word but the reference names it: CBA does not carry it.
    d = matcher.match(ref("Commonwealth Bank Securities"))
    assert link_key(d) is None
    cba = next(r for r in d.ranked if r.canonical_key == f"urn:abn:{CBA_ABN}")
    assert "SECURITIES" in cba.features["ref_tokens_missing_in_candidate"] and not cba.eligible


def test_licence_number_never_beats_a_name_rival(store: DuckDBStore) -> None:
    store.execute("INSERT INTO identifier VALUES (?, 'afsl', '234567')", [f"urn:abn:{ACME_ABN}"])
    m = Matcher(store)
    d = m.resolve("Commonwealth Bank of Australia AFSL 234567")
    assert isinstance(d, Abstention) and d.reason is AbstainReason.IDENTIFIER_CONFLICT
    d = m.resolve("AFSL 234567")
    assert isinstance(d, Link) and d.match_type is MatchType.EXACT_LICENCE_NO and d.confidence == 0.95


def test_person_shaped_unknown_reference_is_a_person(matcher: Matcher) -> None:
    r = matcher.prepare(ReferenceParser().parse("John Smith"))
    assert r.party_type_hint is PartyType.PERSON
    assert matcher.prepare(ReferenceParser().parse("Acme Plumbing")).party_type_hint is PartyType.UNKNOWN


def link_key(d):
    return d.canonical_key if isinstance(d, Link) else None


def test_trust_vs_company_and_formal_geo(matcher: Matcher) -> None:
    # A company is not the trust named like it ("The Trustee for Koala Holdings").
    d = matcher.match(ref("Koala Holdings Limited", source="gleif_l1"))
    assert link_key(d) is None
    koala = next(r for r in d.ranked if r.canonical_key == f"urn:abn:{KOALA_ABN}")
    assert koala.features["entity_kind_conflict"]
    # A registered legal name keeps its AUSTRALIA: 'ACME PLUMBING AUSTRALIA PTY LTD' is not ACME PLUMBING.
    d = matcher.match(ref("Acme Plumbing Australia Pty Ltd", source="gleif_l1"))
    assert link_key(d) is None
    # ...while an informal reference may drop or add it.
    assert link_key(matcher.resolve("Commonwealth Bank")) == f"urn:abn:{CBA_ABN}"
