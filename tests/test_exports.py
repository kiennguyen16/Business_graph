import json

from bizgraph.exports import export_decisions
from bizgraph.store.duckdb_store import DuckDBStore


def test_export_decisions_jsonl(tmp_path):
    store = DuckDBStore(":memory:")
    store.execute("INSERT INTO party_canonical (canonical_key, source, record_id) VALUES ('urn:abn:1','abr','1')")
    store.execute("INSERT INTO link (link_id, matcher_version, source, record_id, canonical_key, match_type, confidence, evidence) VALUES ('l','m-v','x','2','urn:abn:1','EXACT_ABN',1.0,'{\"id\":\"abn\"}')")
    store.execute("INSERT INTO abstention (matcher_version, source, record_id, best_candidate, best_score, reason, evidence) VALUES ('m-v','x','3','urn:abn:1',0.4,'BELOW_THRESHOLD','{\"margin\":0.1}')")
    assert export_decisions(store, "m-v", tmp_path) == (1, 1)
    link = json.loads((tmp_path / "links.jsonl").read_text())
    abst = json.loads((tmp_path / "abstentions.jsonl").read_text())
    assert link["right"]["source"] == "abr" and link["evidence"]["id"] == "abn"
    assert abst["score"] == 0.4 and abst["evidence"]["margin"] == 0.1
    store.con.close()
