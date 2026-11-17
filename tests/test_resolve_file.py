"""`bizgraph resolve-file` input / output handling (bizgraph.resolve_io) on odd input schemas.

Matching runs on the synthetic store from test_resolution (no dependency on data/bizgraph.duckdb)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bizgraph.resolution import Matcher
from bizgraph.resolve_io import build_text, load_references, read_input, run_file

from test_resolution import CBA_ABN, make_store  # noqa: E402  (sibling test module; tests/ is on sys.path)

BRIEF_FIELDS = ["reference_id", "candidates", "decision", "latency_ms"]
CANDIDATE_FIELDS = ["canonical_key", "name", "score", "match_type", "evidence", "path"]


@pytest.fixture()
def store():
    return make_store()


@pytest.fixture()
def matcher(store):
    return Matcher(store)


def _write(tmp_path: Path, name: str, content: str | bytes) -> Path:
    p = tmp_path / name
    if isinstance(content, str):
        content = content.encode("utf-8")
    p.write_bytes(content)
    return p


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_jsonl_with_bom_blank_lines_and_malformed_row(tmp_path, matcher, store) -> None:
    src = _write(tmp_path, "in.jsonl", b"\xef\xbb\xbf" + (
        '{"ref_id": "r-1", "query": "Commonwealth Bank of Australia"}\n'
        "\n   \n"
        '{"ref_id": "r-2", "query": "acme plumbing pty. ltd."\n'  # malformed: missing brace
        '{"ref_id": "r-3", "query": "Nowhere Widgets Pty Ltd"}\n'
    ).encode("utf-8"))
    out = tmp_path / "out.jsonl"
    s = run_file(matcher, src, out, k=3, store=store)
    rows = _rows(out)
    assert [r["reference_id"] for r in rows] == ["r-1", 2, "r-3"]  # order kept; bad row gets its row number
    assert s["rows"] == 3 and s["errors"] == 1
    for r in rows:
        assert list(r)[:4] == BRIEF_FIELDS
        assert r["decision"] in ("resolved", "abstained")
        for c in r["candidates"]:
            assert list(c) == CANDIDATE_FIELDS
    assert rows[0]["decision"] == "resolved"
    assert rows[0]["candidates"][0]["canonical_key"] == f"urn:abn:{CBA_ABN}"
    assert rows[0]["candidates"][0]["name"] == "COMMONWEALTH BANK OF AUSTRALIA"
    assert rows[1]["decision"] == "abstained" and rows[1]["candidates"] == [] and "invalid JSON" in rows[1]["error"]
    assert rows[2]["decision"] == "abstained" and rows[2]["candidates"] == []
    assert "error" not in rows[2]
    assert s["latency_ms"]["p50"] is not None and s["latency_ms"]["p95"] is not None


def test_json_array_and_wrapped_array(tmp_path) -> None:
    arr = _write(tmp_path, "a.json", json.dumps([{"id": 7, "text": "x one"}, "bare string ref", {"rid": "z"}]))
    refs = load_references(arr)
    assert [r["reference_id"] for r in refs] == [7, 2, "z"]
    assert refs[1]["reference"] == "bare string ref"
    assert refs[2]["error"] == "no reference text in this row"
    wrapped = _write(tmp_path, "w.json", json.dumps({"meta": "x", "references": [{"key": "k1", "raw": "Foo Pty Ltd"}]},
                                                    indent=2))
    refs = load_references(wrapped)
    assert len(refs) == 1 and refs[0]["reference_id"] == "k1" and refs[0]["reference"] == "Foo Pty Ltd"


def test_csv_with_structured_fields_and_unknown_columns(tmp_path) -> None:
    src = _write(tmp_path, "refs.csv",
                 "Reference ID,Entity Name,ABN,Address,Notes\n"
                 f'1,"Commonwealth Bank, of Australia",{CBA_ABN},"201 Sussex St, Sydney NSW 2000",x\n'
                 "2,Acme Plumbing,,,\n")
    refs = load_references(src)
    assert refs[0]["reference_id"] == "1"
    assert refs[0]["reference"] == f"Commonwealth Bank, of Australia, ABN {CBA_ABN}, NSW 2000"
    assert refs[0]["input"]["Notes"] == "x"  # unknown fields are echoed
    assert refs[1]["reference"] == "Acme Plumbing"


def test_tsv_and_plain_lines(tmp_path) -> None:
    tsv = _write(tmp_path, "r.tsv", "id\tname\tstate\na1\tKoala Holdings\tWA\n")
    assert load_references(tsv)[0]["reference"] == "Koala Holdings, WA"
    txt = _write(tmp_path, "r.txt", "Acme Plumbing Pty Ltd\n\nWestpac, Banking Corp\n")
    refs = load_references(txt)
    assert [r["reference"] for r in refs] == ["Acme Plumbing Pty Ltd", "Westpac, Banking Corp"]
    assert [r["reference_id"] for r in refs] == [1, 2]
    headerless = _write(tmp_path, "r.csv", "Acme Plumbing, WA\nOcean Pearl Trading\n")
    assert [r["reference"] for r in load_references(headerless)] == ["Acme Plumbing, WA", "Ocean Pearl Trading"]


def test_text_assembly_rules() -> None:
    # A full reference is kept; an identifier already in it is not appended twice.
    t, _ = build_text({"reference": f"CBA ABN {CBA_ABN[:2]} {CBA_ABN[2:5]} {CBA_ABN[5:8]} {CBA_ABN[8:]}",
                       "abn": CBA_ABN})
    assert t.count("ABN") == 1
    # A state already at the end of the text is not appended again; nested objects are read.
    t, _ = build_text({"entity": {"name": "Acme Plumbing WA", "state": "Western Australia"}})
    assert t == "Acme Plumbing WA"
    t, _ = build_text({"Company": "Acme", "ACN": "123 456 789", "LEI": "529900T8BM49AURSDO55", "State": "tas"})
    assert t == "Acme, ACN 123 456 789, LEI 529900T8BM49AURSDO55, TAS"


def test_unicode_and_limit(tmp_path, matcher, store) -> None:
    src = _write(tmp_path, "u.jsonl", "\n".join(json.dumps({"id": i, "reference": r}, ensure_ascii=False) for i, r in
                                                enumerate(["Café Société Pty Ltd", "ＡＣＭＥ Plumbing", "株式会社 テスト",
                                                           "Acme Plumbing"])))
    out = tmp_path / "o.jsonl"
    s = run_file(matcher, src, out, k=2, limit=3, store=store)
    rows = _rows(out)
    assert s["rows"] == 3 and len(rows) == 3
    assert rows[0]["reference"] == "Café Société Pty Ltd"  # written as UTF-8, not escaped away
    assert all(r["decision"] in ("resolved", "abstained") for r in rows)


def test_resolver_exception_becomes_abstained_row(tmp_path, store) -> None:
    class Boom:
        version = None

        def resolve(self, text):
            if "boom" in text:
                raise RuntimeError("kaboom")
            return Matcher(store).resolve(text)

    src = _write(tmp_path, "b.jsonl", '{"id": "ok", "text": "Acme Plumbing"}\n{"id": "bad", "text": "boom"}\n')
    out = tmp_path / "o.jsonl"
    run_file(Boom(), src, out, store=store, warm_up=False)
    rows = _rows(out)
    assert rows[1]["reference_id"] == "bad" and rows[1]["decision"] == "abstained"
    assert rows[1]["candidates"] == [] and "kaboom" in rows[1]["error"]


def test_cp1252_and_empty_file(tmp_path) -> None:
    p = _write(tmp_path, "c.txt", "Caf\xe9 Pty Ltd\n".encode("cp1252"))
    assert load_references(p)[0]["reference"] == "Café Pty Ltd"
    assert read_input(_write(tmp_path, "e.jsonl", "\n\n")) == []
