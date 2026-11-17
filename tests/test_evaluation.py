"""Evaluation package: sampler determinism, Wilson interval, metrics on a toy set, blind file contents."""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from bizgraph.evaluation.metrics import classify, identifier_truth_sweep, summarise, wilson_interval
from bizgraph.evaluation.sampler import (
    BLIND_COLUMNS,
    DECISION_COLUMNS,
    Quota,
    decisions_for,
    gather_evidence,
    stratified_sample,
    write_sample,
)
from bizgraph.store.duckdb_store import DuckDBStore

V = "m-test-0001"
POLICY = {"policy": {"default": 0.9, "per_source": {"accc_notice": 0.97}}, "config": {}}


@pytest.fixture()
def con():
    store = DuckDBStore(":memory:")
    store.init_schema()
    c = store.con
    c.execute("INSERT INTO matcher_version VALUES (?, 'h', ?, current_timestamp)", [V, json.dumps(POLICY)])
    parties, records, links, abst = [], [], [], []
    for i in range(60):
        key = f"urn:abn:{10_000_000_000 + i}"
        parties.append((key, "organisation", f"ACME {i} PTY LTD", f"ACME {i}", key[8:], None, None, None, None,
                        "WA", None, None, None, None, "abr", key[8:]))
        rid = f"R{i:03d}"
        src = "accc_notice" if i < 5 else "asic_afsl"
        records.append((src, rid, "h", "2026-11-01", "2026-11-01", "2026-11-01", json.dumps({"name": f"Acme {i}"}),
                        f"Acme {i} Pty Ltd", f"ACME {i}", "organisation", key[8:] if i % 2 else None, None, None,
                        None, "WA", json.dumps([["abn", key[8:]]] if i % 2 else []), "t", None, i))
        if i % 3 == 0:
            abst.append((V, src, rid, key, 0.88 if i % 2 else 0.5, "BELOW_THRESHOLD", None, None))
        else:
            mt = "EXACT_ABN" if i % 2 else "NAME_FUZZY"
            links.append((f"L{i}", V, src, rid, key, mt, 0.93 if mt == "NAME_FUZZY" else 1.0, "{}", None))
    c.executemany("INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, abn, acn, lei, "
                  "entity_type, status, state, postcode, anzsic, valid_from, valid_to, source, record_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", parties)
    c.executemany("INSERT INTO identifier VALUES (?, 'abn', ?)", [(p[0], p[4]) for p in parties])
    c.executemany("INSERT INTO source_record (source, record_id, content_hash, snapshot_date, first_seen_snapshot, "
                  "last_seen_snapshot, payload, name_raw, name_norm, party_type, abn, acn, lei, licence_no, state, "
                  "identifiers, adapter_version, ingested_at, load_seq) VALUES "
                  "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", records)
    c.executemany("INSERT INTO link (link_id, matcher_version, source, record_id, canonical_key, match_type, "
                  "confidence, evidence, created_at) VALUES (?,?,?,?,?,?,?,?,coalesce(?, current_timestamp))", links)
    c.executemany("INSERT INTO abstention (matcher_version, source, record_id, best_candidate, best_score, reason, "
                  "created_at, evidence) VALUES (?,?,?,?,?,?,coalesce(?, current_timestamp),?)", abst)
    yield c
    c.close()


PLAN = (
    Quota("accc_notice", "*", "*", None),
    Quota("asic_afsl", "link", "EXACT_*", 4),
    Quota("asic_afsl", "link", "NAME_*", 4),
    Quota("asic_afsl", "abstain", "*", 5),
)


def test_sampler_is_deterministic_and_follows_the_plan(con):
    a = stratified_sample(con, V, seed=7, plan=PLAN)
    b = stratified_sample(con, V, seed=7, plan=PLAN)
    pd.testing.assert_frame_equal(a, b)
    assert (a["source"] == "accc_notice").sum() == 5  # take-all quota
    afsl = a[a["source"] == "asic_afsl"]
    assert (afsl["outcome"].str.startswith("EXACT_")).sum() == 4
    assert (afsl["outcome"].str.startswith("NAME_")).sum() == 4
    abst = afsl[afsl["decision"] == "abstain"]
    assert len(abst) == 5
    assert set(abst["band"]) == {"near0.05", "far"}  # both bands represented, near band first
    c = stratified_sample(con, V, seed=8, plan=PLAN)
    assert set(c["record_id"]) != set(a["record_id"])  # the seed matters
    assert a["sample_id"].is_unique


def test_sample_ids_do_not_depend_on_version_or_seed(con):
    a = stratified_sample(con, V, seed=1, plan=PLAN).set_index("record_id")["sample_id"]
    b = stratified_sample(con, V, seed=2, plan=PLAN).set_index("record_id")["sample_id"]
    common = a.index.intersection(b.index)
    assert len(common) > 0 and (a[common] == b[common]).all()


def test_blind_file_excludes_decision_columns(con, tmp_path):
    blind_path, dec_path, sample = write_sample(con, V, tmp_path, seed=3, plan=PLAN)
    blind = pd.read_csv(blind_path, dtype=str).fillna("")
    assert list(blind.columns) == BLIND_COLUMNS
    for forbidden in ("score", "decision", "outcome", "target", "match_type", "stratum", "confidence", "reason",
                      "band", "quota", "best_candidate"):
        assert forbidden not in blind.columns
    text = blind.to_csv(index=False)
    for leak in ("EXACT_ABN", "NAME_FUZZY", "BELOW_THRESHOLD", "0.93", "0.88"):
        assert leak not in text
    dec = pd.read_csv(dec_path, dtype=str)
    assert set(DECISION_COLUMNS) <= set(dec.columns)
    assert set(dec["sample_id"]) == set(blind["sample_id"])
    # every decided link target is offered to the labeller, unmarked
    for _, r in dec[dec["decision"] == "link"].iterrows():
        cands = blind.loc[blind["sample_id"] == r["sample_id"], "candidates"].iloc[0]
        assert r["target"] in cands


def test_gather_evidence_is_reproducible(con):
    s = stratified_sample(con, V, seed=5, plan=PLAN)
    pd.testing.assert_frame_equal(gather_evidence(con, s), gather_evidence(con, s))


def test_wilson_interval_known_values():
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-4)
    lo, hi = wilson_interval(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-4) and hi == 1.0
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo, hi = wilson_interval(95, 100)
    assert lo < 0.95 < hi and hi - lo < 0.1


def test_metrics_on_a_toy_set():
    dec = pd.DataFrame([
        # source, record, decision, outcome, target
        ("s", "1", "link", "EXACT_ABN", "A"),     # right
        ("s", "2", "link", "NAME_FUZZY", "B"),    # wrong party
        ("s", "3", "link", "NAME_FUZZY", "C"),    # truth NONE: wrong link
        ("s", "4", "abstain", "AMBIGUOUS", "D"),  # truth D: miss
        ("s", "5", "abstain", "BELOW_THRESHOLD", None),  # truth NOT_IN_GRAPH: right abstention
        ("s", "6", "link", "NAME_FUZZY", "F"),    # UNSURE: excluded
    ], columns=["source", "record_id", "decision", "outcome", "target"])
    dec["stratum"] = "x"
    lab = pd.DataFrame({"source": "s", "record_id": list("123456"),
                        "true_canonical_key": ["A", "X", "NONE", "D", "NOT_IN_GRAPH", "UNSURE"]})
    df = classify(dec, lab)
    assert df["tp"].tolist() == [True, False, False, False, False, False]
    assert df["fp"].tolist() == [False, True, True, False, False, False]
    assert df["fn"].tolist() == [False, True, False, True, False, False]
    assert df["tn"].tolist() == [False, False, False, False, True, False]
    s = summarise(df, None).iloc[0]
    assert s["labelled"] == 5 and s["links"] == 3 and s["tp"] == 1 and s["wrong_links"] == 2
    assert s["precision"] == pytest.approx(1 / 3)
    assert s["true_target_in_graph"] == 3  # A, X, D
    assert s["recall"] == pytest.approx(1 / 3)
    assert not math.isnan(s["p_lo"]) and s["p_lo"] < 1 / 3 < s["p_hi"]


def test_weights_follow_the_version_strata(con):
    from bizgraph.evaluation.metrics import evaluate

    pop = decisions_for(con, V)
    lab = pop.head(6)[["source", "record_id"]].copy()
    lab["true_canonical_key"] = pop.head(6)["target"].fillna("NONE").tolist()
    df = evaluate(con, V, lab)
    for stratum, g in df.groupby("stratum"):
        assert g["weight"].iloc[0] == pytest.approx((pop["stratum"] == stratum).sum() / len(g))


def test_identifier_truth_sweep_counts_links_against_printed_abn(con):
    sw = identifier_truth_sweep(con, [V], sources=("asic_afsl",))
    row = sw.iloc[0]
    assert row["wrong"] == 0 and row["links"] == row["correct"]
    assert row["truth_records"] == sum(1 for i in range(5, 60) if i % 2)


def test_stale_keys_from_before_a_canonical_rebuild_are_remapped(con):
    # A party re-minted from urn:acn:... to urn:abn:... after its ABN arrived: old decisions still say urn:acn.
    con.execute("INSERT INTO identifier VALUES ('urn:abn:10000000007', 'acn', '000000007')")
    con.execute("INSERT INTO link (link_id, matcher_version, source, record_id, canonical_key, match_type, confidence, "
                "evidence) VALUES ('Lx', ?, 'asic_afsl', 'R007', 'urn:acn:000000007', 'NAME_FUZZY', 0.95, '{}')", [V])
    d = decisions_for(con, V)
    row = d[(d["record_id"] == "R007") & (d["decision"] == "link") & (d["outcome"] == "NAME_FUZZY")
            & d["stale_target"].notna()]
    assert len(row) == 1
    assert row["target"].iloc[0] == "urn:abn:10000000007"
    assert row["stale_target"].iloc[0] == "urn:acn:000000007"


def test_licence_segment_marks_ended_records(con):
    con.execute("UPDATE source_record SET last_seen_snapshot = DATE '2026-10-01' WHERE record_id = 'R010'")
    d = decisions_for(con, V)
    seg = d.set_index("record_id")["segment"]
    assert seg["R010"] == "ended" and seg["R011"] == "current"
    assert d["stratum"].str.endswith("|ended").any()
