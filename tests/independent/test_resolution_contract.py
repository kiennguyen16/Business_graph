"""Independent contract tests for entity resolution (tester-written, adversarial).

Spec anchors:
- Requirement.md "The resolution" / "The lookup": a wrong link is worse than no link; exact and
  semantic are two named paths with a written arbitration rule; every link carries evidence;
  recalibration must not require re-matching. Named tests: Commonwealth Bank of Australia vs
  Commonwealth Superannuation Corporation; banned / disqualified (a wrong link publishes an accusation).
- ontology/NOTES.md match types and abstain reasons; ARCHITECTURE.md 2.2, 2.4, 2.5, 3.5.

Stores are small synthetic in-memory DuckDB stores (memory-limited machine). Embeddings are off
except for the semantic-path tests (BIZGRAPH_EMBEDDINGS / explicit Embedder.load()).

Run: .venv/Scripts/python -m pytest tests/independent/test_resolution_contract.py -q -s
"""

from __future__ import annotations

import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _res_harness import (  # noqa: E402
    P,
    abn_from_acn,
    bad_abn,
    bulk_parties,
    load_parties,
    make_acn,
    make_lei,
    new_store,
    norm_of,
    record,
    scenario_parties,
)

from bizgraph.domain.models import AbstainReason, Identifier, IdScheme, MatchType, PartyType  # noqa: E402
from bizgraph.resolution import (  # noqa: E402
    Abstention,
    Embedder,
    Link,
    Matcher,
    Reference,
    ThresholdPolicy,
)

os.environ.setdefault("BIZGRAPH_EMBEDDINGS", "0")

EXACT_ID_TYPES = {"EXACT_ABN", "EXACT_ACN", "EXACT_LEI", "EXACT_LICENCE_NO"}
NAME_TYPES = {"NAME_NORMALISED_EXACT", "NAME_FUZZY", "NAME_SEMANTIC"}


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def world():
    """Scenario traps + 3k bulk parties; one matcher without embeddings."""
    s = new_store()
    ps = scenario_parties()
    load_parties(s, ps + bulk_parties(3000))
    m = Matcher(s, embedder=None)
    yield s, m, {p.key: p for p in ps}
    s.close()


def _no_person_world():
    s = new_store()
    ps = [p for p in scenario_parties() if p.key != "person_js"]
    load_parties(s, ps)
    return s, Matcher(s, embedder=None), {p.key: p for p in ps}


def link_key(d):
    return d.canonical_key if isinstance(d, Link) else None


def check_evidence(d, store):
    """Every decision carries complete, re-runnable evidence."""
    if isinstance(d, Link):
        assert d.match_type in set(MatchType)
        assert 0.0 <= d.confidence <= 1.0
        ev = d.evidence
        assert ev is not None and ev.features and ev.path in ("exact", "semantic")
        assert ev.query_text, "link without query_text"
        for path, sql in ev.query_text.items():
            sql_part = sql.split("; then ", 1)[-1] if path == "block_embedding" else sql
            keys = {r[0] for r in store.con.execute(sql_part).fetchall()}
            assert d.canonical_key in keys, f"query_text for {path} does not return the linked party: {sql}"
        if str(d.match_type) in EXACT_ID_TYPES:
            assert ev.features["identifier_match"] is True
        else:
            assert ev.features["identifier_match"] is False
    else:
        assert isinstance(d, Abstention)
        assert d.reason in set(AbstainReason)
        if d.reason is not AbstainReason.NO_CANDIDATE:
            assert d.best_candidate is not None and d.evidence is not None


# --------------------------------------------------------------------------- named tests


class TestNamedSpecCases:
    def test_cba_vs_csc(self, world):
        s, m, _ = world
        for text in ["Commonwealth Bank of Australia", "Commonwealth Bank", "COMMONWEALTH BANK OF AUST"]:
            d = m.resolve(text)
            assert link_key(d) == "cba", (text, d.explanation)
        for text in ["Commonwealth Superannuation Corporation", "Commonwealth Superannuation Corp"]:
            assert link_key(m.resolve(text)) == "csc"
        d = m.resolve("Commonwealth Bank")
        assert all(r.canonical_key != "csc" or not r.eligible for r in d.ranked)

    def test_bare_generic_prefix_abstains(self, world):
        _, m, _ = world
        for text in ["Commonwealth", "Westpac", "Commonwealth Corporation"]:
            d = m.resolve(text)
            assert not isinstance(d, Link) or d.canonical_key not in ("csc",), text

    @pytest.mark.parametrize("src", ["asic_banned_org", "accc_notice"])
    def test_strict_sources_are_stricter(self, world, src):
        _, m, _ = world
        # A pair that links under the default threshold but not under the strict one.
        name = "Quorva"
        default = m.match(Reference.from_record(record("adhoc", "r", name)))
        strict = m.match(Reference.from_record(record(src, "r", name)))
        assert not isinstance(strict, Link), strict.explanation
        if isinstance(default, Link):
            assert strict.reason in (AbstainReason.BELOW_THRESHOLD, AbstainReason.AMBIGUOUS)


# --------------------------------------------------------------------------- near-name traps (wrong links)


class TestNearNameTraps:
    @pytest.mark.parametrize(
        "text,forbidden",
        [
            ("Westpac Securities", "wbc"),
            ("Westpac Banking Corporation", "wsec"),
            ("AMP Capital", "amp"),  # AMP Capital is not AMP Limited
            ("AMP Capital Investors", "amp"),
            ("Bluegum Trust", "bluegum_pty"),  # a trust is not its namesake company
            ("The Trustee for Bluegum Family Trust", "bluegum_pty"),
            ("Bluegum Pty Ltd", "bluegum_trust"),
            ("Commonwealth Securities", "cba"),
            ("Jones Hire", "jones_co"),
            ("Smith Roofing Pty Ltd", "smith_pty"),
        ],
    )
    def test_never_links_to_the_neighbour(self, world, text, forbidden):
        _, m, _ = world
        d = m.resolve(text)
        assert link_key(d) != forbidden, f"{text!r} wrongly linked to {forbidden}: {d.explanation}"

    # "Jones" / "Smith" are the exact normalised names of JONES & CO PTY LTD / SMITH PTY LTD, so
    # NAME_NORMALISED_EXACT is the written rule there (judgement call, not asserted).
    @pytest.mark.parametrize("text", ["Quorva", "Acme", "Ironbark Constructions Pty Ltd"])
    def test_underspecified_names_abstain(self, world, text):
        """A bare token that several parties share must not pick one of them."""
        _, m, _ = world
        d = m.resolve(text)
        assert not isinstance(d, Link), f"{text!r} linked to {d.canonical_key} ({d.match_type}): {d.explanation}"

    def test_same_name_two_states(self, world):
        _, m, _ = world
        assert isinstance(m.resolve("Ironbark Constructions Pty Ltd"), Abstention)
        assert link_key(m.resolve("Ironbark Constructions Pty Ltd QLD")) == "ironbark_qld"
        assert link_key(m.resolve("Ironbark Constructions Pty Ltd, NSW 2000")) == "ironbark_nsw"

    def test_legal_form_only_difference(self, world):
        _, m, _ = world
        assert link_key(m.resolve("ACME PTY LTD")) != "acme_ltd"
        assert link_key(m.resolve("ACME LIMITED")) != "acme_pty"

    def test_acronyms_do_not_guess(self, world):
        _, m, _ = world
        d = m.resolve("CBA")
        assert not isinstance(d, Link)
        # ANZ is a registered trading-name alias, so a link is legitimate; nothing else is.
        assert link_key(m.resolve("ANZ")) in (None, "anz")

    @pytest.mark.parametrize("text", ["Comonwealth Bank of Australia", "Commonwealth Bnak of Australia",
                                      "Commonweatlh Bank"])
    def test_typo_in_distinctive_token_links_or_abstains_never_elsewhere(self, world, text):
        _, m, _ = world
        assert link_key(m.resolve(text)) in (None, "cba")

    def test_and_co(self, world):
        _, m, _ = world
        assert link_key(m.resolve("Jones & Co Pty Ltd")) == "jones_co"
        assert link_key(m.resolve("Jones and Co")) in (None, "jones_co")


# --------------------------------------------------------------------------- identifiers


class TestIdentifierTraps:
    def test_abn_with_conflicting_name_keeps_disagreement(self, world):
        _, m, ps = world
        d = m.resolve(f"Westpac Banking Corporation ABN {ps['cba'].abn}")
        # The written rule: identifier wins, disagreement recorded.
        if isinstance(d, Link):
            assert d.canonical_key == "cba" and d.match_type is MatchType.EXACT_ABN
            assert d.evidence.disagreement, "identifier/name disagreement not recorded"

    def test_abn_and_acn_of_different_parties_abstain(self, world):
        _, m, ps = world
        d = m.resolve(f"ABN {ps['cba'].abn} ACN {ps['wbc'].acn}")
        assert isinstance(d, Abstention) and d.reason is AbstainReason.IDENTIFIER_CONFLICT

    def test_valid_abn_absent_party_does_not_fall_through_to_wrong_name(self, world):
        _, m, _ = world
        unknown_abn = abn_from_acn(make_acn(99_999_001))
        d = m.resolve(f"Commonwealth Superannuation Corporation ABN {unknown_abn}")
        # csc carries a different ABN: a name link would override an identifier.
        assert link_key(d) != "csc", d.explanation

    def test_arsn_and_arbn_labels_are_kept(self, world):
        _, m, _ = world
        d = m.resolve(f"ARSN {make_acn(777_001)}")
        assert link_key(d) == "scheme", f"ARSN lookup failed: {d.explanation}"
        d = m.resolve(f"ARBN {make_acn(777_002)}")
        assert link_key(d) == "foreign", f"ARBN lookup failed: {d.explanation}"

    def test_acn_label_on_an_arsn_does_not_link(self, world):
        _, m, _ = world
        assert link_key(m.resolve(f"ACN {make_acn(777_001)}")) is None

    def test_all_zero_numbers(self, world):
        _, m, _ = world
        for t in ["ABN 00000000000", "ACN 000 000 000", "ABN 00 000 000 000 Commonwealth Bank"]:
            d = m.resolve(t)
            assert link_key(d) in (None, "cba")
            if isinstance(d, Link):
                assert str(d.match_type) not in EXACT_ID_TYPES

    def test_unlabelled_nine_digits_not_an_acn(self, world):
        _, m, ps = world
        d = m.resolve(f"Westpac Banking Corporation {ps['cba'].acn}")
        assert link_key(d) != "cba"

    def test_unlabelled_nine_digits_do_not_block_obvious_name(self, world):
        """Over-abstention probe: a stray number should not become a distinctive token."""
        _, m, ps = world
        d = m.resolve(f"Commonwealth Bank of Australia {ps['cba'].acn}")
        assert link_key(d) == "cba", d.explanation

    def test_abn_with_spaces_and_bad_checksum(self, world):
        _, m, ps = world
        assert link_key(m.resolve("ABN " + " ".join([ps["cba"].abn[:2], ps["cba"].abn[2:5],
                                                      ps["cba"].abn[5:8], ps["cba"].abn[8:]]))) == "cba"
        bad = bad_abn(100_000)  # one digit off cba's ABN
        d = m.resolve(f"ABN {bad[:2]} {bad[2:5]} {bad[5:8]} {bad[8:]}")
        assert not isinstance(d, Link) or str(d.match_type) not in EXACT_ID_TYPES

    def test_licence_moved_holder_name_disagrees(self, world):
        """AFSL 234567 still sits on the old holder; the text names the (unique) new holder.
        Licence numbers transfer, so the licence must not override the name to the old holder."""
        _, m, _ = world
        d = m.resolve("Banksia Wealth Pty Ltd AFSL 234567")
        assert link_key(d) != "afsl_old", f"licence number overrode the name: {d.explanation}"

    def test_lei_duplicate_vs_annulled(self):
        s = new_store()
        lei_a, lei_b = make_lei(2), make_lei(3)
        load_parties(s, [P("ent", "GREVILLEA RESOURCES LIMITED", abn=abn_from_acn(make_acn(5)), acn=make_acn(5),
                           lei=lei_a)])
        m = Matcher(s, embedder=None)
        # DUPLICATE: the record's LEI is a second LEI for the same entity; ABN agrees -> link.
        r = record("gleif", "1", "GREVILLEA RESOURCES LIMITED",
                   ids=(Identifier(IdScheme.LEI, lei_b), Identifier(IdScheme.ABN, abn_from_acn(make_acn(5)))),
                   lei_status="DUPLICATE")
        assert link_key(m.match(Reference.from_record(r))) == "ent"
        # Not duplicate: a different LEI is a conflict.
        r2 = record("gleif", "2", "GREVILLEA RESOURCES LIMITED",
                    ids=(Identifier(IdScheme.LEI, lei_b), Identifier(IdScheme.ABN, abn_from_acn(make_acn(5)))),
                    lei_status="ISSUED")
        d2 = m.match(Reference.from_record(r2))
        assert isinstance(d2, Abstention) and d2.reason is AbstainReason.IDENTIFIER_CONFLICT
        # ANNULLED: the LEI is ignored entirely (no join, no veto).
        r3 = record("gleif", "3", "SOMETHING ELSE ENTIRELY LTD", ids=(Identifier(IdScheme.LEI, lei_a),),
                    lei_status="ANNULLED")
        d3 = m.match(Reference.from_record(r3))
        assert link_key(d3) != "ent"
        s.close()


# --------------------------------------------------------------------------- persons, quarantine, margins


class TestPersonQuarantineMargin:
    def test_liquidator_style_person_never_links_to_company(self, world):
        _, m, _ = world
        d = m.match(Reference.from_record(record("asic_liquidator", "1", "SMITH, JOHN", PartyType.PERSON)))
        assert link_key(d) != "johnsmith_pty"
        assert not isinstance(d, Link), "person linked on name alone"

    def test_given_last_person_name_never_links_to_company(self):
        s, m, _ = _no_person_world()
        for text in ["John Smith", "JOHN SMITH"]:
            d = m.resolve(text)
            assert link_key(d) != "johnsmith_pty", f"{text!r} -> JOHN SMITH PTY LTD: {d.explanation}"
        d = m.match(Reference.from_record(record("asic_liquidator", "1", "JOHN SMITH", PartyType.UNKNOWN)))
        assert link_key(d) != "johnsmith_pty", d.explanation
        s.close()

    def test_person_name_links_off(self, world):
        _, m, _ = world
        d = m.match(Reference.from_record(record("asic_banned_person", "1", "SMITH, JOHN", PartyType.PERSON)))
        assert not isinstance(d, Link)

    def test_quarantined_never_linked(self, world):
        _, m, ps = world
        for t in ["Zentrix Analytics Pty Ltd", f"ABN {ps['quar'].abn}", f"Zentrix Analytics ACN {ps['quar'].acn}"]:
            d = m.resolve(t)
            assert link_key(d) != "quar"
            assert isinstance(d, Abstention) and d.reason is AbstainReason.QUARANTINED_TARGET, (t, d.explanation)

    def test_quarantined_via_quarantine_table(self):
        s = new_store()
        load_parties(s, [P("q2", "SILVERGULL MARINE PTY LTD", abn=abn_from_acn(make_acn(9)), acn=make_acn(9))])
        s.con.execute("INSERT INTO quarantine (source, record_id, invariant, canonical_key) VALUES "
                      "('abr','x','test','q2')")
        m = Matcher(s, embedder=None)
        assert link_key(m.resolve("Silvergull Marine Pty Ltd")) is None
        s.close()

    def test_two_equal_candidates_abstain(self, world):
        _, m, _ = world
        d = m.resolve("Ironbark Constructions")
        assert isinstance(d, Abstention) and d.reason is AbstainReason.AMBIGUOUS


# --------------------------------------------------------------------------- evidence + labelling


EVIDENCE_INPUTS = [
    "Commonwealth Bank of Australia", "Commonwealth Bank", "Comonwealth Bank of Australia", "AMP Ltd",
    "Westpac Securities", "Smith Plumbing Pty Ltd", "Redgum Cellars", "Acme", "CBA", "", "SMITH, JOHN",
    "Zentrix Analytics", "Ironbark Constructions", "Quorva Traders",
]


class TestEvidenceAndLabels:
    @pytest.mark.parametrize("text", EVIDENCE_INPUTS)
    def test_resolve_evidence_complete(self, world, text):
        s, m, _ = world
        check_evidence(m.resolve(text), s)

    def test_identifier_link_evidence(self, world):
        s, m, ps = world
        for t in [f"ABN {ps['cba'].abn}", f"ACN {ps['wbc'].acn}", f"LEI {ps['cba'].lei}", "AFSL 234567"]:
            d = m.resolve(t)
            assert isinstance(d, Link), t
            check_evidence(d, s)

    def test_labels_and_paths_consistent_over_ranked(self, world):
        _, m, ps = world
        for t in EVIDENCE_INPUTS + [f"Westpac ABN {ps['cba'].abn}"]:
            for r in m.resolve(t).ranked:
                if r.match_type in EXACT_ID_TYPES:
                    assert r.features["identifier_match"], (t, r)
                    assert r.path == "exact"
                if r.match_type == "NAME_NORMALISED_EXACT":
                    assert r.path == "exact" and not r.features["identifier_match"]
                if r.match_type in ("NAME_FUZZY", "NAME_SEMANTIC"):
                    assert r.path == "semantic" and not r.features["identifier_match"]
                if r.eligible and r.match_type in NAME_TYPES:
                    assert r.features["distinctive_coverage"] >= 1.0, ("token gate bypassed", t, r)


# --------------------------------------------------------------------------- messy input


class TestMessyResolve:
    @pytest.mark.parametrize("text", [
        "  commonwealth   bank of australia  ", "COMMONWEALTH BANK OF AUSTRALIA LTD.",
        "Commonwealth Bank of Australia, NSW", "Commonwealth Bank of Australia (NSW)",
        "The Commonwealth Bank of Australia", "commonwealth bank of australia limited",
        "Commonwealth Bank of Australia; ABN 48 123 123 125",  # invalid ABN: ignored
    ])
    def test_messy_cba(self, world, text):
        _, m, _ = world
        assert link_key(m.resolve(text)) == "cba", text

    @pytest.mark.parametrize("text", ["Smith Plumbing Pty. Ltd.", "SMITH PLUMBING PROPRIETARY LIMITED",
                                      "smith plumbing p/l", "Smith Plumbing Pty Limited"])
    def test_legal_form_spellings(self, world, text):
        _, m, _ = world
        assert link_key(m.resolve(text)) in ("smith_0", None)
        if text != "smith plumbing p/l":
            assert link_key(m.resolve(text)) == "smith_0", text

    def test_trading_as_via_alias(self, world):
        _, m, _ = world
        assert link_key(m.resolve("Redgum Cellars")) == "redgum"
        # REDGUM WINES HOLDINGS PTY LTD exists in the bulk set; abstaining is acceptable, a wrong link is not.
        assert link_key(m.resolve("Redgum Wines Pty Ltd t/as Redgum Cellars")) in ("redgum", None)

    @pytest.mark.parametrize("text", ["", "   ", ",,,", "x" * 5000, "Pty Ltd", "Limited", "The",
                                      "商业银行", "\U0001F600 bank"])
    def test_degenerate_inputs_never_link(self, world, text):
        _, m, _ = world
        d = m.resolve(text)
        assert not isinstance(d, Link), (text, d.explanation)

    def test_unicode_accents_fold(self):
        s = new_store()
        load_parties(s, [P("cafe", "CAFE SOCIETE PTY LTD", abn=abn_from_acn(make_acn(11)), acn=make_acn(11))])
        m = Matcher(s, embedder=None)
        assert link_key(m.resolve("Café Société Pty Ltd")) == "cafe"
        s.close()


# --------------------------------------------------------------------------- batch + recalibration


def _batch_world(n_bulk=3000):
    s = new_store()
    ps = scenario_parties()
    bulk = bulk_parties(n_bulk)
    load_parties(s, ps + bulk)
    recs = []
    names = ["Commonwealth Bank", "Commonwealth Superannuation Corp", "AMP Ltd", "Westpac Securities",
             "Quorva", "Acme", "Ironbark Constructions", "Smith Plumbing", "Comonwealth Bank of Australia",
             "Redgum Cellars", "Bluegum Family Trust", "Jones Hire Pty Ltd", "Totally Unknown Widgets"]
    for i, nm in enumerate(names):
        recs.append(record("asic_banned_org", f"b{i}", nm))
        recs.append(record("adhoc", f"a{i}", nm))
    recs.append(record("adhoc", "id1", "Wrong Name", ids=(Identifier(IdScheme.ABN, ps[0].abn),)))
    rng = random.Random(3)
    for j, p in enumerate(rng.sample(bulk, 200)):
        recs.append(record("adhoc", f"k{j}", p.name.replace(" PTY LTD", ""), state=p.state))
    s.records.upsert(recs)
    return s


class TestBatchAndRecalibration:
    def test_batch_equals_resolve(self):
        s = _batch_world()
        m = Matcher(s, embedder=None)
        m.match_batch("adhoc")
        m.match_batch("asic_banned_org")
        v = m.version.version
        rows = s.con.execute("SELECT source, record_id, canonical_key FROM link WHERE matcher_version = ?",
                             [v]).fetchall()
        batch = {(a, b): c for a, b, c in rows}
        mismatches = []
        for src in ("adhoc", "asic_banned_org"):
            for rec in s.records.by_source(src):
                single = link_key(m.match(Reference.from_record(rec)))
                if batch.get((src, rec.record_id)) != single:
                    mismatches.append((src, rec.record_id, rec.name_raw, batch.get((src, rec.record_id)), single))
        assert not mismatches, mismatches[:10]
        s.close()

    def test_batch_evidence_and_query_text(self):
        s = _batch_world()
        m = Matcher(s, embedder=None)
        m.match_batch("adhoc")
        v = m.version.version
        import json as _j
        for rid, key, mt, conf, ev in s.con.execute(
            "SELECT record_id, canonical_key, match_type, confidence, evidence FROM link WHERE matcher_version = ?",
            [v],
        ).fetchall():
            ev = _j.loads(ev) if isinstance(ev, str) else ev
            assert mt in set(MatchType) and 0 <= conf <= 1
            assert ev["features"] and ev["query_text"]
            for path, sql in ev["query_text"].items():
                keys = {r[0] for r in s.con.execute(sql).fetchall()}
                assert key in keys, (rid, path, sql)
            assert (mt in EXACT_ID_TYPES) == bool(ev["features"]["identifier_match"])
        for (reason, best) in s.con.execute(
            "SELECT reason, best_candidate FROM abstention WHERE matcher_version = ?", [v]
        ).fetchall():
            assert reason in set(AbstainReason)
            if reason != "NO_CANDIDATE":
                assert best is not None
        # candidate rows: query_text re-runs and returns the candidate
        for key, path, f in s.con.execute(
            "SELECT canonical_key, path, features FROM candidate WHERE run_id = ? USING SAMPLE 200 ROWS", [v]
        ).fetchall():
            f = _j.loads(f) if isinstance(f, str) else f
            keys = {r[0] for r in s.con.execute(f["query_text"]).fetchall()}
            assert key in keys, (path, f["query_text"])
        s.close()

    def test_rerun_idempotent(self):
        s = _batch_world()
        m = Matcher(s, embedder=None)
        m.match_batch("adhoc")
        c1 = s.table_counts()
        m.match_batch("adhoc")
        c2 = s.table_counts()
        assert c1["candidate"] == c2["candidate"] and c1["link"] == c2["link"]
        assert c1["abstention"] == c2["abstention"] and c1["matcher_version"] == c2["matcher_version"]
        s.close()

    def test_redecide_no_regeneration_and_policy_monotone(self):
        s = _batch_world()
        m = Matcher(s, embedder=None)
        t0 = time.perf_counter()
        base = m.match_batch("adhoc")
        t_batch = time.perf_counter() - t0
        run = base.run_id
        n_cand = s.con.execute("SELECT count(*) FROM candidate").fetchall()[0][0]
        n_cand_run = s.con.execute("SELECT count(*) FROM candidate WHERE run_id = ?", [run]).fetchall()[0][0]

        strict = ThresholdPolicy(default=0.99, min_margin=0.2)
        loose = ThresholdPolicy(default=0.80, min_margin=0.02, unknown_type_threshold=0.85)
        t0 = time.perf_counter()
        rs = m.redecide(run, strict, "adhoc")
        t_re = time.perf_counter() - t0
        rl = m.redecide(run, loose, "adhoc")
        assert s.con.execute("SELECT count(*) FROM candidate").fetchall()[0][0] == n_cand
        assert rs.candidates == n_cand_run
        assert rs.matcher_version != rl.matcher_version != run
        print(f"\nrecalibration: batch {t_batch:.2f}s, redecide {t_re:.2f}s, base links {base.links}, "
              f"strict {rs.links} diff {rs.diff}, loose {rl.links} diff {rl.diff}")

        def links(v):
            return dict(((r, k) for r, k in s.con.execute(
                "SELECT record_id, canonical_key FROM link WHERE matcher_version = ?", [v]).fetchall()))

        lb, ls_, ll = links(run), links(rs.matcher_version), links(rl.matcher_version)
        # strict links are a subset of base links; base links (identifier ones at least) survive loose
        assert all(lb.get(r) == k for r, k in ls_.items()), "strict policy produced a link base did not"
        assert rs.links <= base.links <= rl.links + 0  # loose cannot have fewer links unless margin flips
        # redecide with the base policy reproduces the base decisions
        same = m.redecide(run, m.policy, "adhoc")
        assert links(same.matcher_version) == lb
        # versions immutable
        with pytest.raises(ValueError):
            s.matcher_versions.save(rs.matcher_version, "other", {"x": 1})
        assert t_re < t_batch, (t_re, t_batch)
        s.close()


# --------------------------------------------------------------------------- semantic path


@pytest.fixture(scope="module")
def sem_world():
    os.environ["BIZGRAPH_EMBEDDINGS"] = "1"
    try:
        emb = Embedder.load()
    finally:
        os.environ["BIZGRAPH_EMBEDDINGS"] = "0"
    if emb is None:
        pytest.skip("sentence-transformers / model not available")
    s = new_store()
    ps = scenario_parties()
    load_parties(s, ps + bulk_parties(1500))
    m = Matcher(s, embedder=emb, use_embedding_blocker=True)
    yield s, m
    s.close()


class TestSemanticPath:
    @pytest.mark.parametrize("text,forbidden", [
        ("Commonwealth Bank", "csc"), ("Commonwealth Superannuation", "cba"), ("Westpac Securities", "wbc"),
        ("AMP Capital", "amp"), ("Bluegum Trust", "bluegum_pty"), ("CBA", "cba"), ("Commonwealth Banking", "csc"),
        ("Commonwealth Financial", "cba"), ("Westpac", "wbc"),
    ])
    def test_semantic_never_crosses_token_gate(self, sem_world, text, forbidden):
        s, m = sem_world
        d = m.resolve(text)
        assert link_key(d) != forbidden, (text, d.explanation)
        for r in d.ranked:
            if r.match_type == "NAME_SEMANTIC" and r.eligible:
                assert r.features["distinctive_coverage"] >= 1.0
                assert r.features["distinctive_coverage_rev"] >= 1.0
        check_evidence(d, s)

    def test_semantic_label_only_with_embedding(self, sem_world):
        s, m = sem_world
        for t in ["Comonwealth Bank of Australia", "Westpac Banking Corp", "Smith Plumbing Services"]:
            d = m.resolve(t)
            if isinstance(d, Link) and d.match_type is MatchType.NAME_SEMANTIC:
                assert d.evidence.scores["semantic"] is not None
                assert d.evidence.scores["semantic"] > d.evidence.scores["fuzzy"]
            check_evidence(d, s)


# --------------------------------------------------------------------------- recall sanity


_TYPOS = {"SERVICES": "SERVCES", "GROUP": "GRUOP", "HOLDINGS": "HOLDNGS", "SOLUTIONS": "SOLUTONS"}


def perturb(name: str, rng: random.Random) -> tuple[str, str]:
    ops = []
    n = name
    if rng.random() < 0.5:
        n = re.sub(r"\s+(PTY\.? LTD\.?|PROPRIETARY LIMITED|LIMITED)$", "", n)
        ops.append("drop_form")
    elif "PTY LTD" in n:
        n = n.replace("PTY LTD", rng.choice(["PROPRIETARY LIMITED", "PTY LIMITED", "Pty. Ltd."]))
        ops.append("form_spelling")
    elif "PROPRIETARY LIMITED" in n:
        n = n.replace("PROPRIETARY LIMITED", "PTY LTD")
        ops.append("abbrev_form")
    if rng.random() < 0.2:
        n = "THE " + n
        ops.append("add_the")
    if " & " in n:
        n = n.replace(" & ", " AND ")
        ops.append("amp_and")
    elif " AND " in n:
        n = n.replace(" AND ", " & ")
        ops.append("and_amp")
    for g, t in _TYPOS.items():
        if g in n.split() and rng.random() < 0.5:
            n = n.replace(g, t)
            ops.append("generic_typo")
            break
    if rng.random() < 0.3:
        n = n.lower()
        ops.append("lower")
    if rng.random() < 0.2:
        n = n.replace(" ", "  ") + " ."
        ops.append("spacing")
    return n, "+".join(ops) or "none"


def test_recall_sanity():
    s = new_store()
    bulk = bulk_parties(20_000, seed=11)
    # sprinkle AND / & names
    extra = [P(f"x{i}", f"{a} & {b} {w} PTY LTD", abn=abn_from_acn(make_acn(3_000_000 + i)),
               acn=make_acn(3_000_000 + i), state="NSW")
             for i, (a, b, w) in enumerate(zip(["SMITH", "JONES", "LEE", "KING"] * 10,
                                              ["BROWN", "WHITE", "RYAN", "KELLY"] * 10, ["SERVICES", "GROUP"] * 20))]
    load_parties(s, bulk + extra)
    m = Matcher(s, embedder=None)
    norm_count = Counter(norm_of(p.name, "organisation") for p in bulk + extra)
    rng = random.Random(5)
    sample = rng.sample(bulk + extra, 500)
    stats = Counter()
    reasons = Counter()
    by_op = Counter()
    wrong = []
    missed = []
    for p in sample:
        text, op = perturb(p.name, rng)
        with_state = rng.random() < 0.5
        if with_state:
            text = f"{text} {p.state}"
        d = m.resolve(text)
        unique = norm_count[norm_of(p.name, "organisation")] == 1
        stats["total"] += 1
        stats["unique_truth"] += unique
        resolvable = unique or with_state
        stats["resolvable"] += resolvable
        if isinstance(d, Link):
            stats["linked"] += 1
            stats["resolvable_linked"] += resolvable
            if d.canonical_key == p.key:
                stats["correct"] += 1
            else:
                # a link to a same-name party in another state is still wrong
                wrong.append((text, p.key, p.name, d.canonical_key, str(d.match_type), d.confidence))
        else:
            reasons[str(d.reason)] += 1
            if resolvable:
                by_op[op] += 1
                stats["resolvable_missed_truth_top"] += d.best_candidate == p.key
                missed.append((text, p.name, str(d.reason), d.best_candidate == p.key, d.explanation[:100]))
    expected = sum(1 for _ in sample)
    precision = stats["correct"] / stats["linked"] if stats["linked"] else 1.0
    print(f"\nrecall sanity: {dict(stats)} precision={precision:.4f} link_rate={stats['linked'] / expected:.3f}")
    print(f"resolvable recall={stats['resolvable_linked'] / max(1, stats['resolvable']):.3f}")
    print("abstention reasons:", dict(reasons))
    print("missed (unique or stated truth) by perturbation:", dict(by_op))
    for w in wrong[:15]:
        print("WRONG", w)
    for mm in missed[:25]:
        print("MISSED", mm)
    s.close()
    assert not wrong, f"{len(wrong)} wrong links"
    assert stats["resolvable_linked"] / stats["resolvable"] >= 0.90, "over-abstention on resolvable perturbations"
