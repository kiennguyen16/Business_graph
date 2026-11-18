"""Input / output handling for `bizgraph resolve-file`, robust to an unknown input schema.

This module lives outside `bizgraph.resolution` on purpose: the matcher version string embeds a
hash of every file in that package (`resolution.matcher.code_hash`), so changing how a file is
read must not change which matcher version the results report. Nothing here touches matching:
each row ends in one `Matcher.resolve(text)` call, exactly as `bizgraph resolve` makes it.

Input (detected, not declared):

* JSONL: one JSON value per line (object, or a bare string = the reference text);
* a JSON array (of objects or strings), or an object wrapping one such array;
* CSV / TSV with a header row (delimiter sniffed);
* plain text, one reference per line (a .txt file, or a delimited file without a known header).

A UTF-8 byte order mark is ignored; a file that is not UTF-8 is read as cp1252. Blank lines are
skipped (they are not references). A row that cannot be parsed is not dropped: it is written as an
abstained row with an `error` field, so the output has one row per input row, in input order.

Field mapping (case-insensitive; spaces and hyphens read as underscores; one level of nesting is
flattened):

* id: the first of id, reference_id, ref_id, rid, key; else the 1-based row number;
* text: the first of reference, text, query, raw, input (a full free-text reference), else name,
  company, entity_name (a bare name). When structured fields are present (abn, acn, lei, arbn,
  afsl, state, postcode, address), identifiers not already in the text are appended as labelled
  numbers ("ABN 48 ..."), and a state (from `state`, else from the tail of `address`) is appended
  when the text names none. A street address is never appended: the reference parser would read it
  as part of the name.

Output: one JSON object per input row, the brief's fields first (reference_id, candidates with
canonical_key / name / score / match_type / evidence / path, decision resolved|abstained,
latency_ms), then extras (the text that was resolved, the decision detail, matcher version, the
input row echo, and `error` when there was one).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def matcher_read_only(store, policy, embedder="auto", version_label="m"):
    """Construct Matcher without writing derived indexes to a read-only DuckDB file."""
    import types
    from bizgraph.resolution import Matcher
    from bizgraph.resolution.candidates import NameIndex
    import bizgraph.resolution.matcher as mm
    fp = NameIndex(store.con)._fingerprint()
    try:
        row = store.con.execute("SELECT fingerprint FROM res_index_meta").fetchone()
    except Exception:
        row = None
    if row and row[0] == fp:
        class ReadOnlyIndex(NameIndex):
            def ensure(self, force=False):
                return {"built": False, "fingerprint": fp, "current": True, "read_only": True}
        old = mm.NameIndex
        mm.NameIndex = ReadOnlyIndex
        try:
            return Matcher(store, policy=policy, embedder=embedder, version_label=version_label)
        finally:
            mm.NameIndex = old
    import duckdb
    con = duckdb.connect()
    con.execute(f"ATTACH '{Path(str(store.path)).as_posix()}' AS snap (READ_ONLY)")
    for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name='snap'").fetchall():
        if not t.startswith('res_'):
            con.execute(f'CREATE VIEW main."{t}" AS SELECT * FROM snap.main."{t}"')
    con.execute("CREATE TABLE res_index_meta (fingerprint VARCHAR, built_at TIMESTAMP, build_s DOUBLE)")
    ov = types.SimpleNamespace(con=con)
    return Matcher(ov, policy=policy, embedder=embedder, version_label=version_label)

ID_KEYS = ("id", "reference_id", "ref_id", "rid", "key")
TEXT_KEYS = ("reference", "text", "query", "raw", "input")
NAME_KEYS = ("name", "company", "entity_name")
IDENT_KEYS = ("abn", "acn", "arbn", "arsn", "lei", "afsl", "acl")
STATE_KEYS = ("state",)
POSTCODE_KEYS = ("postcode", "post_code", "zip")
ADDRESS_KEYS = ("address",)
_KNOWN = set(ID_KEYS + TEXT_KEYS + NAME_KEYS + IDENT_KEYS + STATE_KEYS + POSTCODE_KEYS + ADDRESS_KEYS)

_AU_STATES = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")
_STATE_WORDS = {
    "NEW SOUTH WALES": "NSW", "VICTORIA": "VIC", "QUEENSLAND": "QLD", "WESTERN AUSTRALIA": "WA",
    "SOUTH AUSTRALIA": "SA", "TASMANIA": "TAS", "AUSTRALIAN CAPITAL TERRITORY": "ACT",
    "NORTHERN TERRITORY": "NT",
}
_STATE_AT_END = re.compile(r"\b(" + "|".join(_AU_STATES) + r")\b[)\]]?\s*\d{0,4}\s*$", re.IGNORECASE)
_ADDR_STATE = re.compile(r"\b(" + "|".join(_AU_STATES) + r")\b\.?,?\s*(\d{4})?\s*(?:,?\s*AUSTRALIA)?\s*$",
                         re.IGNORECASE)


# --------------------------------------------------------------------------- reading


def _norm_key(k: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(k).strip().lower())


def _flatten(obj: dict[str, Any]) -> dict[str, Any]:
    """Normalised keys; one level of nested objects flattened (inner keys win only if unset)."""
    flat: dict[str, Any] = {}
    nested: dict[str, Any] = {}
    for k, v in obj.items():
        nk = _norm_key(k)
        if isinstance(v, dict):
            for k2, v2 in v.items():
                nested.setdefault(_norm_key(k2), v2)
        else:
            flat.setdefault(nk, v)
    for k, v in nested.items():
        flat.setdefault(k, v)
    return flat


def _decode(data: bytes) -> str:
    """UTF-8 (a byte order mark is dropped), UTF-16 when it has a BOM, else cp1252."""
    encodings = ("utf-16", "utf-8-sig") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",)
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("cp1252", errors="replace")


def _unwrap(value: Any) -> list[Any] | None:
    """A JSON array, or an object holding exactly one array (e.g. {"references": [...]})."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        lists = [v for v in value.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return None


def _looks_like_header(fields: list[str]) -> bool:
    return any(_norm_key(f) in _KNOWN for f in fields if f is not None)


def read_input(path: str | Path) -> list[tuple[Any, str | None]]:
    """Raw rows in file order: (parsed value, parse error). A value is a dict, a str or None."""
    text = _decode(Path(path).read_bytes())
    stripped = text.strip()
    suffix = Path(path).suffix.lower()
    if not stripped:
        return []
    # A whole-file JSON document: an array, or one object (a one-line JSONL file, or an object
    # wrapping the array, e.g. {"references": [...]}).
    if stripped[0] in "[{":
        try:
            doc = json.loads(stripped)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, list):
            return [(r, None) for r in doc]
        if isinstance(doc, dict):
            flat = _flatten(doc)
            wrapped = _unwrap(doc)
            if wrapped is not None and _first(flat, TEXT_KEYS + NAME_KEYS)[0] is None:
                return [(r, None) for r in wrapped]
            return [(doc, None)]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if stripped[0] == "{" or suffix in (".jsonl", ".ndjson", ".json"):
        out: list[tuple[Any, str | None]] = []
        for ln in lines:
            try:
                out.append((json.loads(ln), None))
            except json.JSONDecodeError as e:
                out.append((None, f"invalid JSON on this line: {e.msg} (line text: {ln.strip()[:200]!r})"))
        return out
    if suffix == ".txt":
        return [(ln.strip(), None) for ln in lines]
    # Delimited text with a header row; otherwise one reference per line.
    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO("\n".join(lines)), dialect)
    rows_raw = list(reader)
    if rows_raw and _looks_like_header(rows_raw[0]):
        header = rows_raw[0]
        out = []
        for cells in rows_raw[1:]:
            rec = {h: (cells[i] if i < len(cells) else None) for i, h in enumerate(header)}
            if len(cells) > len(header):
                rec["_extra_cells"] = cells[len(header):]
            out.append((rec, None))
        return out
    return [(ln.strip(), None) for ln in lines]


def _first(flat: dict[str, Any], keys: Iterable[str]) -> tuple[str | None, Any]:
    for k in keys:
        v = flat.get(k)
        if v is not None and str(v).strip() != "":
            return k, v
    return None, None


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _state_from(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().upper()
    if v in _AU_STATES:
        return v
    return _STATE_WORDS.get(v)


def build_text(value: Any) -> tuple[str, dict[str, Any]]:
    """The free-text reference for one input row, and how it was built."""
    if isinstance(value, str):
        return value.strip(), {"text_from": "line"}
    if not isinstance(value, dict):
        return (str(value).strip() if value is not None else ""), {"text_from": "scalar"}
    flat = _flatten(value)
    tkey, text = _first(flat, TEXT_KEYS)
    how: dict[str, Any] = {}
    if text is None:
        tkey, text = _first(flat, NAME_KEYS)
    text = str(text).strip() if text is not None else ""
    how["text_from"] = tkey
    added: list[str] = []
    have_digits = _digits(text)
    for k in IDENT_KEYS:
        v = flat.get(k)
        if v is None or str(v).strip() == "":
            continue
        v = str(v).strip()
        d = _digits(v) if k != "lei" else v.upper()
        if (k == "lei" and d in text.upper()) or (k != "lei" and d and d in have_digits):
            continue
        added.append(f"{k.upper()} {v}")
    state = _state_from(_first(flat, STATE_KEYS)[1])
    postcode = _first(flat, POSTCODE_KEYS)[1]
    addr = _first(flat, ADDRESS_KEYS)[1]
    if addr is not None and (state is None or postcode is None):
        m = _ADDR_STATE.search(str(addr))
        if m:
            state = state or m.group(1).upper()
            postcode = postcode or m.group(2)
    parts = [text] if text else []
    parts += added
    if state and not _STATE_AT_END.search(text):
        parts.append(f"{state} {postcode}".strip() if postcode else state)
    if added or len(parts) > (1 if text else 0):
        how["appended"] = parts[1:] if text else parts
    return ", ".join(parts), how


def load_references(path: str | Path, limit: int | None = None) -> list[dict[str, Any]]:
    """One dict per input row: row (1-based), reference_id, reference (text), input echo, error."""
    out = []
    for i, (value, err) in enumerate(read_input(path), 1):
        if limit is not None and len(out) >= limit:
            break
        ref_id: Any = i
        echo: Any = value
        text = ""
        how: dict[str, Any] = {}
        if err is None:
            try:
                if isinstance(value, dict):
                    _, rid = _first(_flatten(value), ID_KEYS)
                    if rid is not None:
                        ref_id = rid
                text, how = build_text(value)
                if not text:
                    err = "no reference text in this row"
            except Exception as e:  # never let one row stop the file
                err = f"could not read this row: {type(e).__name__}: {e}"
        out.append({"row": i, "reference_id": ref_id, "reference": text, "how": how,
                    "input": echo, "error": err})
    return out


# --------------------------------------------------------------------------- resolving


def _names(store, keys: list[str]) -> dict[str, str]:
    if not keys or store is None:
        return {}
    try:
        rows = store.con.execute(
            "SELECT canonical_key, name FROM party_canonical WHERE canonical_key IN (SELECT unnest(?))", [keys]
        ).fetchall()
        return dict(rows)
    except Exception:
        return {}


def _candidates(decision, k: int, names: dict[str, str]) -> list[dict[str, Any]]:
    from bizgraph.resolution.cli_commands import candidate_rows

    out = []
    for c in candidate_rows(decision, k):
        out.append({
            "canonical_key": c["canonical_key"],
            "name": names.get(c["canonical_key"]),
            "score": c["score"],
            "match_type": c["match_type"],
            "evidence": c["evidence"],
            "path": c["path"],
        })
    return out


def resolve_reference(matcher, ref: dict[str, Any], k: int, store=None) -> dict[str, Any]:
    """One output row. Never raises: a failure becomes an abstained row with `error`."""
    from bizgraph.resolution import Link

    row: dict[str, Any] = {"reference_id": ref["reference_id"], "candidates": [], "decision": "abstained",
                           "latency_ms": 0.0}
    extra: dict[str, Any] = {"reference": ref["reference"], "row": ref["row"]}
    err = ref.get("error")
    if err is None:
        t0 = time.perf_counter()
        try:
            d = matcher.resolve(ref["reference"])
        except Exception as e:
            d = None
            err = f"resolve failed: {type(e).__name__}: {e}"
        row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if d is not None:
            try:
                resolved = isinstance(d, Link)
                keys = [r.canonical_key for r in d.ranked[: max(k, 1) * 3]]
                row["candidates"] = _candidates(d, k, _names(store, keys))
                row["decision"] = "resolved" if resolved else "abstained"
                extra.update({
                    "canonical_key": d.canonical_key if resolved else None,
                    "match_type": str(d.match_type) if resolved else None,
                    "confidence": d.confidence if resolved else None,
                    "abstain_reason": None if resolved else str(d.reason),
                    "explanation": d.explanation,
                    "disagreement": d.evidence.disagreement if resolved and d.evidence else None,
                    "candidates_considered": len(d.ranked),
                })
            except Exception as e:
                row["candidates"], row["decision"] = [], "abstained"
                err = f"could not format the decision: {type(e).__name__}: {e}"
    version = getattr(getattr(matcher, "version", None), "version", None)
    extra["matcher_version"] = version
    if ref.get("how"):
        extra["text_built"] = ref["how"]
    extra["input"] = ref.get("input")
    if err is not None:
        extra["abstain_reason"] = "ERROR"
        extra["error"] = err
    row.update(extra)
    return row


def percentile(sorted_vals: list[float], q: float) -> float | None:
    """Nearest-rank percentile of an ascending list."""
    if not sorted_vals:
        return None
    import math

    return sorted_vals[max(0, min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1))]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lat = sorted(r["latency_ms"] for r in rows if not r.get("error"))
    return {
        "rows": len(rows),
        "by_decision": dict(Counter(r["decision"] for r in rows)),
        "errors": sum(1 for r in rows if r.get("error")),
        "abstained_with_no_candidates": sum(1 for r in rows if r["decision"] == "abstained" and not r["candidates"]),
        "latency_ms": {"p50": percentile(lat, 0.50), "p95": percentile(lat, 0.95),
                       "max": lat[-1] if lat else None, "n": len(lat)},
    }


def run_file(matcher, input_path: str | Path, output_path: str | Path, k: int = 5, limit: int | None = None,
             store=None, warm_up: bool = True) -> dict[str, Any]:
    refs = load_references(input_path, limit)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if warm_up:
        try:
            matcher.resolve("warm up")  # first call loads caches; not part of any latency
        except Exception:
            pass
    rows = []
    t0 = time.perf_counter()
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for ref in refs:
            row = resolve_reference(matcher, ref, k, store)
            rows.append(row)
            fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
            fh.flush()
    s = summarise(rows)
    s["wall_s"] = round(time.perf_counter() - t0, 2)
    s["output"] = str(out)
    s["matcher_version"] = getattr(getattr(matcher, "version", None), "version", None)
    return s


def cmd_resolve_file(args) -> int:
    from bizgraph.resolution.cli_commands import _matcher, _open

    with _open(args, read_only=True) as store:
        m = _matcher(store, args)
        s = run_file(m, args.input, args.output, k=args.k, limit=args.limit, store=store)
    lat = s["latency_ms"]
    print(f"wrote {s['rows']} rows to {s['output']} (matcher {s['matcher_version']}); "
          + ", ".join(f"{k} {v}" for k, v in sorted(s["by_decision"].items()))
          + f"; errors {s['errors']}; latency p50 {lat['p50']} ms, p95 {lat['p95']} ms, max {lat['max']} ms; "
          f"wall {s['wall_s']} s")
    print(json.dumps(s), file=sys.stderr)
    return 0


def configure_parser(rf) -> None:
    """Upgrade the `resolve-file` sub-parser registered by bizgraph.resolution.cli_commands."""
    import argparse

    rf.description = __doc__
    rf.formatter_class = argparse.RawDescriptionHelpFormatter
    rf.add_argument("--k", dest="k", type=int, help="candidates per row (same as -k; default 5)")
    rf.add_argument("--limit", type=int, default=None, help="resolve only the first N rows")
    rf.add_argument("--db", default=argparse.SUPPRESS, help="DuckDB file (may also be given before the command)")
    rf.set_defaults(func=cmd_resolve_file)
