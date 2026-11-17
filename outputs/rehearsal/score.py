"""Score a resolve-file output against the rehearsal answer key.

    .venv/Scripts/python outputs/rehearsal/score.py [results.jsonl] [answer_key.jsonl] [--md out.md]

Defaults: outputs/resolve_results.jsonl and outputs/rehearsal/answer_key.jsonl.

Definitions (a row's decision is what `resolve-file` wrote; the resolved key is candidate 1):
  precision of resolved   correct resolved / all resolved
  recall over in-graph    correct resolved / references whose truth is in the graph
  correct abstention      abstained / references whose truth is NOT_IN_GRAPH (and: with an empty list)
  wrong link              resolved to a key that is not the expected one (in-graph or absent truth)
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.1f}%)" if b else f"{a}/0 (n/a)"


def nearest_rank(vals: list[float], q: float) -> float | None:
    vals = sorted(vals)
    return vals[max(0, min(len(vals) - 1, math.ceil(q * len(vals)) - 1))] if vals else None


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def resolved_key(r: dict) -> str | None:
    if r["decision"] != "resolved":
        return None
    return r.get("canonical_key") or (r["candidates"][0]["canonical_key"] if r["candidates"] else None)


def score(results: list[dict], key: list[dict]) -> dict:
    truth = {k["reference_id"]: k for k in key}
    order_ok = [r["reference_id"] for r in results] == [k["reference_id"] for k in key]
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    wrong, missed, lat = [], [], []
    tot = defaultdict(int)
    for r in results:
        k = truth[r["reference_id"]]
        exp, got, cat = k["expected"], resolved_key(r), k["category"]
        absent = exp == "NOT_IN_GRAPH"
        c = by_cat[cat]
        c["n"] += 1
        tot["n"] += 1
        if not r.get("error"):
            lat.append(r["latency_ms"])
        if got is not None:
            c["resolved"] += 1
            tot["resolved"] += 1
            if got == exp:
                c["correct"] += 1
                tot["correct"] += 1
            else:
                c["wrong"] += 1
                tot["wrong"] += 1
                wrong.append((r, k))
        if absent:
            tot["absent"] += 1
            c["absent"] += 1
            if r["decision"] == "abstained":
                tot["absent_abstained"] += 1
                c["absent_abstained"] += 1
                if not r["candidates"]:
                    tot["absent_empty"] += 1
                    c["absent_empty"] += 1
        else:
            tot["in_graph"] += 1
            c["in_graph"] += 1
            if got is None:
                top = r["candidates"][0]["canonical_key"] if r["candidates"] else None
                c["abstained_in_graph"] += 1
                missed.append((r, k, top == exp, any(x["canonical_key"] == exp for x in r["candidates"])))
        if r.get("error"):
            tot["errors"] += 1
    return {"order_ok": order_ok, "tot": tot, "by_cat": by_cat, "wrong": wrong, "missed": missed,
            "p50": nearest_rank(lat, 0.5), "p95": nearest_rank(lat, 0.95), "max": max(lat) if lat else None}


def report(s: dict) -> str:
    t = s["tot"]
    lines = [
        f"- rows: {t['n']}, order matches the input: {s['order_ok']}, rows with an error: {t['errors']}",
        f"- precision of resolved: {pct(t['correct'], t['resolved'])}",
        f"- recall over in-graph references: {pct(t['correct'], t['in_graph'])}",
        f"- correct abstention on NOT_IN_GRAPH: {pct(t['absent_abstained'], t['absent'])}; "
        f"of those with an empty candidate list: {pct(t['absent_empty'], t['absent'])}",
        f"- wrong links: {t['wrong']}",
        f"- latency per reference (ms, measured): p50 {s['p50']}, p95 {s['p95']}, max {s['max']}",
        "",
        "| category | n | resolved | correct | wrong | in-graph abstained | absent abstained (empty list) |",
        "|---|---|---|---|---|---|---|",
    ]
    for cat in sorted(s["by_cat"]):
        c = s["by_cat"][cat]
        ab = f"{c['absent_abstained']}/{c['absent']} ({c['absent_empty']})" if c["absent"] else ""
        lines.append(f"| {cat} | {c['n']} | {c['resolved']} | {c['correct']} | {c['wrong']} | "
                     f"{c['abstained_in_graph']} | {ab} |")
    lines += ["", "### Wrong links", ""]
    if not s["wrong"]:
        lines.append("None.")
    for r, k in s["wrong"]:
        c0 = r["candidates"][0] if r["candidates"] else {}
        ev = c0.get("evidence", {})
        lines.append(
            f"- {r['reference_id']} [{k['category']}] `{r['reference']}` expected `{k['expected']}` "
            f"({k['true_name']}); got `{resolved_key(r)}` ({c0.get('name')}) {r.get('match_type')} "
            f"confidence {r.get('confidence')}; compared_name `{ev.get('compared_name')}` "
            f"({ev.get('compared_name_kind')}), ids {ev.get('identifier_match_schemes')}, "
            f"jw {ev.get('jaro_winkler')}, tsr {ev.get('token_set_ratio')}, state_match {ev.get('state_match')}, "
            f"corruptions {k['corruptions']}")
    lines += ["", "### In-graph references abstained on", "",
              "| id | category | reference | reason | expected is candidate 1 | expected in list |", "|---|---|---|---|---|---|"]
    for r, k, top, inlist in s["missed"]:
        ref = r["reference"].replace("|", "/")
        lines.append(f"| {r['reference_id']} | {k['category']} | {ref} | {r.get('abstain_reason')} | {top} | {inlist} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", default=str(ROOT / "outputs" / "resolve_results.jsonl"))
    ap.add_argument("key", nargs="?", default=str(HERE / "answer_key.jsonl"))
    ap.add_argument("--md", help="also write the report to this file")
    args = ap.parse_args()
    s = score(load(Path(args.results)), load(Path(args.key)))
    text = report(s)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
