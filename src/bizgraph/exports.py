"""Deterministic JSONL exports of matcher decisions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return value


def _compact(value: Any) -> Any:
    """Drop empty / null / False values and round floats, recursively. Keeps every decision-relevant
    fact (non-default features, gate inputs, scores, path, query) while keeping links.jsonl under
    GitHub's 100 MB file limit. The full evidence stays in the store (and the full export)."""
    if isinstance(value, dict):
        out = {k: _compact(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, False, "", [], {})}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def export_decisions(store, version: str, out: str | Path, compact: bool = True) -> tuple[int, int]:
    """Write links.jsonl and abstentions.jsonl for one matcher version (compact evidence by default)."""
    shrink = _compact if compact else (lambda v: v)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    links = store.query(
        """SELECT l.source, l.record_id, p.source AS right_source,
                  p.record_id AS right_record_id, l.canonical_key, l.match_type,
                  l.confidence, l.evidence
           FROM link l LEFT JOIN party_canonical p USING (canonical_key)
           WHERE l.matcher_version = ?
           ORDER BY l.source, l.record_id, l.canonical_key""", [version])
    abst = store.query(
        """SELECT source, record_id, best_candidate, best_score, reason, evidence
           FROM abstention WHERE matcher_version = ?
           ORDER BY source, record_id""", [version])
    with (out / "links.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in links:
            f.write(json.dumps({"left": {"source": r["source"], "record_id": r["record_id"]},
                                "right": {"source": r["right_source"], "record_id": r["right_record_id"]},
                                "canonical_key": r["canonical_key"], "match_type": r["match_type"],
                                "confidence": r["confidence"], "evidence": shrink(_json_value(r["evidence"]))},
                               sort_keys=True, ensure_ascii=False) + "\n")
    with (out / "abstentions.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in abst:
            f.write(json.dumps({"source": r["source"], "record_id": r["record_id"],
                                "best_candidate": r["best_candidate"], "score": r["best_score"],
                                "reason": r["reason"], "evidence": shrink(_json_value(r["evidence"]))},
                               sort_keys=True, ensure_ascii=False) + "\n")
    return len(links), len(abst)
