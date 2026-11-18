"""Resolution tests on synthetic canonical data (no dependency on data/bizgraph.duckdb)."""

from __future__ import annotations

import dataclasses
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


def make_store(path: str = ":memory:") -> DuckDBStore:
    s = DuckDBStore(path)
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
        lei_status=None, state_basis="register") -> Reference:
    norm = NAMES.normalise_person(name) if ptype is PartyType.PERSON else NAMES.normalise(name)
    return Reference(name, norm, tuple(Identifier(s, v) for s, v in ids), ptype, state, source, rid, lei_status,
                     state_basis=state_basis)


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
    # A state stated in free text that disagrees costs 0.15 ...
    d = matcher.resolve("Acme Plumbing Pty Ltd, VIC")
    assert isinstance(d, Abstention) and d.reason is AbstainReason.BELOW_THRESHOLD
    assert d.best_score == 0.85
    # ... register to register (different kinds of address) only 0.05.
    d = matcher.match(ref("Acme Plumbing Pty Ltd", state="VIC", source="asic_afsl"))
    assert isinstance(d, Link) and d.confidence == 0.95 and d.match_type is MatchType.NAME_FUZZY


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
        assert {"features", "scores", "query_text"} <= set(blob) and "ref" not in blob
        assert blob["query_text"].startswith("SELECT")
    # the reference is stored once per record, not on every candidate row
    n_ref = store.query("SELECT count(*) AS n FROM candidate_ref WHERE run_id = ?", [s.run_id])[0]["n"]
    assert n_ref == s.records
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

    # A looser policy that allows person name links: record 8 flips to a link; the Blue Gum
    # exact tie stays AMBIGUOUS even with a zero margin (ties never link).
    loose = ThresholdPolicy(default=0.80, min_margin=0.0, person_name_links=True)
    r = matcher.redecide(s.run_id, loose)
    assert r.matcher_version != s.matcher_version and r.matcher_version.startswith("mr-")
    assert store.query("SELECT count(*) AS n FROM candidate")[0]["n"] == before
    assert r.records == s.records
    # record 8 (person name link now allowed) flips; record 2 already links (register state penalty 0.05)
    assert r.diff == {"links_added": 1, "links_dropped": 0, "links_retargeted": 0, "links_unchanged": s.links}
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


@pytest.mark.slow
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


def test_redecide_rescores_from_stored_features(store: DuckDBStore, matcher: Matcher, monkeypatch) -> None:
    from bizgraph.resolution import ScorerConfig

    _load_source(store)
    s = matcher.match_batch("test_src")
    monkeypatch.setattr(_FE, "extract", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no re-match")))
    # record 2 (stated VIC, party in WA; register-to-register penalty 0.05) links at 0.95;
    # a harsher scorer config drops it without regenerating anything.
    base = {lk["record_id"]: lk for lk in store.links.by_version(s.matcher_version)}
    assert base["2"]["confidence"] == 0.95
    r = matcher.redecide(s.run_id, matcher.policy, scorer_config=ScorerConfig(state_penalty_register=0.15))
    after = {lk["record_id"] for lk in store.links.by_version(r.matcher_version)}
    assert "2" not in after and r.diff["links_dropped"] == 1
    mv = store.matcher_versions.get(r.matcher_version)
    pol = json.loads(mv["policy"]) if isinstance(mv["policy"], str) else mv["policy"]
    assert pol["config"]["scorer_config"]["state_penalty_register"] == 0.15 and pol["config"]["rescored"]
    # without a scorer config the stored scores are reused: identical decisions
    same = matcher.redecide(s.run_id, matcher.policy)
    assert same.diff["links_added"] == 0 and same.diff["links_dropped"] == 0


def test_cli_match_redecide_and_resolve_file(tmp_path, monkeypatch) -> None:
    from bizgraph.cli import main

    monkeypatch.setenv("BIZGRAPH_EMBEDDINGS", "0")
    db = str(tmp_path / "t.duckdb")
    s = make_store(db)
    _load_source(s)
    s.close()
    assert main(["--db", db, "match", "test_src", "--version-label", "cli"]) == 0
    s = DuckDBStore(db)
    run = s.query("SELECT version FROM matcher_version WHERE version LIKE 'cli-%'")[0]["version"]
    s.close()
    assert main(["--db", db, "redecide", run, "--threshold", "0.8"]) == 0
    src = tmp_path / "in.jsonl"
    src.write_text(json.dumps({"id": "a", "text": "Commonwealth Bank of Aust, ABN 48 123 123 124"}) + "\n"
                   + json.dumps({"reference_id": "b", "reference": "Nothing Like It Pty Ltd"}) + "\n",
                   encoding="utf-8")
    out = tmp_path / "out.jsonl"
    assert main(["--db", db, "resolve-file", str(src), str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["reference_id"] for r in rows] == ["a", "b"]
    assert rows[0]["decision"] == "resolved" and rows[0]["match_type"] == "EXACT_ABN"
    assert rows[0]["candidates"][0]["canonical_key"] == f"urn:abn:{CBA_ABN}" and rows[0]["latency_ms"] > 0
    assert rows[1]["decision"] == "abstained" and rows[1]["candidates"] == []


# --------------------------------------------------------------------------- v3: evaluation census cases


def _census_store() -> DuckDBStore:
    """Parties shaped like the wrong v2 GLEIF links in outputs/evaluation.md section 3."""
    s = DuckDBStore(":memory:")
    rows = [
        # key, party_type, name, entity_type, state, postcode, aliases
        ("juno_wa", "organisation", "The Trustee for The Juno Trust", "DTT", "WA", "6000", []),
        ("rio_ltd", "organisation", "RIO TINTO LIMITED", "PUB", "VIC", "3000", []),
        ("bhp_fin", "organisation", "BHP BILLITON FINANCE LIMITED", "PUB", "VIC", "3000", []),
        ("stanwell", "organisation", "STANWELL CORPORATION LIMITED", "PUB", "QLD", "4000", []),
        ("haven", "organisation", "HAVEN LICENSING PTY. LIMITED", "PRV", "NSW", "2021",
         [("TORO PTY. LIMITED", "former_name")]),
        ("ccb", "organisation", "China Construction Bank Corporation", "OIE", "NSW", "2000", []),
        ("browning_6023", "organisation", "THE BROWNING FAMILY SUPER FUND", "SMF", "WA", "6023", []),
        ("arkad_tas", "organisation", "The Trustee for ARKAD TRUST", "DTT", "TAS", "7005", []),
        ("solo", "person", "AFTABIGILVAN, VALI", "IND", "WA", "6000", []),
        ("pzm", "organisation", "PZM LTD", "PUB", "NSW", "2027", [("PRISM MARKETS", "business_name")]),
        ("wt_co", "organisation", "WT FINANCE CO PTY LTD", "PRV", "WA", "6000", []),
        ("wt", "organisation", "WT FINANCE PTY LTD", "PRV", "WA", "6000", []),
    ]
    for i, (key, ptype, name, etype, state, pc, aliases) in enumerate(rows):
        acn_ = acn(f"6{i:07d}")
        abn = abn_for(acn_)
        norm = NAMES.normalise_person(name) if ptype == "person" else NAMES.normalise(name)
        s.execute(
            """INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, abn, acn, state, postcode,
                                            entity_type, source, record_id, quarantined)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'abr', ?, false)""",
            [key, ptype, name, norm.norm, abn, acn_, state, pc, etype, key],
        )
        s.execute("INSERT INTO identifier VALUES (?, 'abn', ?)", [key, abn])
        for alias, kind in aliases:
            s.execute("INSERT INTO alias VALUES (?, ?, ?, ?, 'abr', ?)", [key, alias, NAMES.normalise(alias).norm, kind, key])
    return s


def _gleif(name: str, jurisdiction: str, *, state=None, postcode=None, ids=(), basis="gleif_entity_category",
           ptype=PartyType.ORGANISATION) -> Reference:
    payload = {"legal_jurisdiction": jurisdiction, "state": state, "party_type_basis": basis,
               "legal_address": {"country": jurisdiction[:2], "postalcode": postcode}}
    rec = SourceRecord("gleif_l1", name, date(2026, 11, 16), payload, name, party_type=ptype,
                       identifiers=tuple(ids))
    return Reference.from_record(rec)


@pytest.fixture()
def census() -> Matcher:
    return Matcher(_census_store())


def test_reused_former_name_prefers_current_holder_and_checks_full_asic_register():
    with _census_store() as store:
        store.execute("INSERT INTO alias VALUES ('haven', 'TORO', 'TORO', 'trading_name', 'abr', 'haven')")
        assert link_key(Matcher(store).resolve("Toro Pty Ltd")) == "haven"
        store.records.upsert([SourceRecord(
            "asic_company", "123", date(2026, 11, 16),
            {"former_names": ["Toro Proprietary Limited"]}, "Other Holdings Pty Ltd",
        )])
        assert Matcher(store).resolve("Toro Pty Ltd").reason is AbstainReason.AMBIGUOUS
        store.execute("""INSERT INTO party_canonical (canonical_key, party_type, name, name_norm)
                         VALUES ('toro', 'organisation', 'TORO PTY LTD', 'TORO')""")
        assert link_key(Matcher(store).resolve("Toro Pty Ltd")) == "toro"


def test_text_foreign_forms_trigger_jurisdiction_gate(census):
    decision = census.resolve("Rio Tinto plc")
    assert decision.reason is AbstainReason.JURISDICTION_MISMATCH
    assert ReferenceParser().parse("Rio Tinto GmbH Holdings").jurisdiction == "non-AU"
    assert ReferenceParser().parse("Rio Tinto SA").jurisdiction == "non-AU"
    assert ReferenceParser().parse("Rio Tinto AS").jurisdiction == "non-AU"
    domestic = ReferenceParser().parse("Brown Mining Pty. Ltd. . SA")
    assert domestic.jurisdiction is None and domestic.state == "SA"
    assert ReferenceParser().parse("Redgum Wines Pty Ltd t/as Redgum Cellars").jurisdiction is None


@pytest.mark.parametrize("text", [
    "Harbour Corp P/L, Mount Barker WA 6324",
    "Harbour Corp P / L Mount Barker, WA",
])
def test_text_legal_form_corp_and_town_address(text):
    parsed = ReferenceParser().parse(text)
    assert parsed.name_norm == NAMES.normalise("Harbour Corporation Pty Ltd").norm
    assert parsed.normalised.legal_form == "PTY LTD"
    assert parsed.state == "WA"


def test_person_links_only_through_unique_exact_registered_business_names():
    with _census_store() as store:
        for alias in ("Whinam Environmental Services", "John Smith"):
            store.execute("INSERT INTO alias VALUES ('solo', ?, ?, 'business_name', 'abr', 'solo')",
                          [alias, NAMES.normalise(alias).norm])
        matcher = Matcher(store)
        hit = matcher.resolve("Whinam Environmental Services")
        assert link_key(hit) == "solo" and hit.match_type is MatchType.NAME_NORMALISED_EXACT
        assert isinstance(matcher.resolve("John Smith"), Abstention)
        assert isinstance(matcher.resolve("Whinam Environmental Service"), Abstention)
        store.execute("""INSERT INTO alias VALUES ('pzm', 'Whinam Environmental Services',
                         'WHINAM ENVIRONMENTAL SERVICES', 'business_name', 'abr', 'pzm')""")
        decision = Matcher(store).resolve("Whinam Environmental Services")
        assert not next(c for c in decision.ranked if c.canonical_key == "solo").eligible


@pytest.mark.parametrize("name,jur", [
    ("THE JUNO TRUST", "NZ"),  # NZ trust vs WA trust of the same name
    ("RIO TINTO PLC", "GB"),  # UK plc vs the Australian company of the dual-listed group
    ("BHP BILLITON FINANCE PLC", "GB"),
    ("Stanwell Limited", "NZ"),
    ("THE TORO COMPANY", "US-DE"),  # matched through a former name of another company in v2
])
def test_foreign_entity_never_links_to_australian_company(census: Matcher, name: str, jur: str) -> None:
    d = census.match(_gleif(name, jur))
    assert link_key(d) is None, d.explanation


def test_jurisdiction_mismatch_reason_and_foreign_registration(census: Matcher) -> None:
    d = census.match(_gleif("THE JUNO TRUST", "NZ"))
    assert isinstance(d, Abstention) and d.reason is AbstainReason.JURISDICTION_MISMATCH
    juno = next(r for r in d.ranked if r.canonical_key == "juno_wa")
    assert juno.features["jurisdiction_conflict"] and juno.features["ref_jurisdiction"] == "NZ"
    # A foreign bank's Australian registration (ABR 'Other Incorporated Entity') is a legal target.
    d = census.match(_gleif("China Construction Bank Corporation", "CN"))
    assert link_key(d) == "ccb"


def test_trust_and_super_fund_need_postcode_and_state(census: Matcher) -> None:
    d = census.match(_gleif("THE BROWNING FAMILY SUPER FUND", "AU", state="WA", postcode="6210"))
    assert link_key(d) is None  # same name, other postcode: a different SMSF
    b = next(r for r in d.ranked if r.canonical_key == "browning_6023")
    assert b.features["postcode_match"] is False and "postcode" in b.veto
    d = census.match(_gleif("Jota Investments Pty Ltd ATF the Arkad Trust", "AU", state="SA", postcode="5081"))
    assert link_key(d) is None  # SA trust vs the TAS trust of the same name


def test_stated_abn_beats_a_gleif_type_hint(census: Matcher) -> None:
    solo_abn = census.store.query("SELECT abn FROM party_canonical WHERE canonical_key = 'solo'")[0]["abn"]
    d = census.match(_gleif("Vali Aftabigilvan", "AU", ids=[Identifier(IdScheme.ABN, solo_abn)]))
    assert isinstance(d, Link) and d.match_type is MatchType.EXACT_ABN and d.canonical_key == "solo"
    assert "type hint" in d.evidence.disagreement
    # A register fact (not a hint) still conflicts.
    r = dataclasses.replace(_gleif("Vali Aftabigilvan", "AU", ids=[Identifier(IdScheme.ABN, solo_abn)]),
                            party_type_basis="has_acn")
    d = census.match(r)
    assert isinstance(d, Abstention) and d.reason is AbstainReason.PARTY_TYPE_CONFLICT


def test_formal_name_never_matches_a_business_name_exactly(census: Matcher) -> None:
    d = census.match(_gleif("Prism Markets Limited", "AU"))
    assert link_key(d) is None
    pzm = next(r for r in d.ranked if r.canonical_key == "pzm")
    assert pzm.features["compared_name_kind"] == "business_name" and not pzm.eligible


def test_weak_legal_form_words_kept_when_the_name_would_collapse(census: Matcher) -> None:
    assert NAMES.normalise("WT FINANCE CO").norm == "WT FINANCE CO"
    assert NAMES.normalise("SIMPLY CORPORATION").norm == "SIMPLY CORPORATION"
    assert NAMES.normalise("WESTPAC BANKING CORPORATION").norm == "WESTPAC BANKING"
    assert link_key(census.resolve("WT Finance Pty Ltd")) == "wt"
    assert link_key(census.resolve("WT Finance Co Pty Ltd")) == "wt_co"


def test_register_names_have_no_typo_tolerance_and_keep_inner_corporation() -> None:
    # 'SUNRISE MEDICAL' from a register is not 'SUNRISE MEDIA' (JW 0.94 would call it a typo).
    s = DuckDBStore(":memory:")
    for key, name in (("media", "SUNRISE MEDIA PTY LTD"), ("garnet", "AUSTRALIAN GARNET PTY LTD")):
        s.execute("INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, source, record_id) "
                  "VALUES (?, 'organisation', ?, ?, 'abr', ?)", [key, name, NAMES.normalise(name).norm, key])
    m = Matcher(s)
    assert link_key(m.match(_gleif("Sunrise Medical Pty. Ltd", "AU"))) is None
    assert link_key(m.resolve("Sunrise Medai Pty Ltd")) == "media"  # free text keeps typo tolerance
    assert NAMES.normalise("Australian Garnet Corporation Pty Ltd").norm == "AUSTRALIAN GARNET CORPORATION"
    assert NAMES.normalise("JONES & CO PTY LTD").norm == "JONES AND CO"
    assert link_key(m.match(_gleif("Australian Garnet Corporation Pty Ltd", "AU"))) is None


def test_index_renormalises_stale_party_norms() -> None:
    # party_canonical.name_norm written by an older normaliser ('WT FINANCE' for WT FINANCE CO PTY LTD):
    # the index normalises names itself, so references and parties agree.
    s = DuckDBStore(":memory:")
    s.execute("INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, source, record_id) "
              "VALUES ('wt_co', 'organisation', 'WT FINANCE CO PTY LTD', 'WT FINANCE', 'abr', 'x')")
    m = Matcher(s)
    assert s.query("SELECT name_norm FROM res_name_index")[0]["name_norm"] == "WT FINANCE CO"
    assert link_key(m.resolve("WT Finance Co Pty Ltd")) == "wt_co"
    assert link_key(m.resolve("WT Finance Pty Ltd")) is None
