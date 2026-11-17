"""Resolution sub-commands for the `bizgraph` CLI (registered by `bizgraph.cli.build_parser`).

    bizgraph match <source_id> [--policy default|strict] [--version-label X]
    bizgraph match-all [--policy ...] [--version-label X]
    bizgraph redecide <run_id> --threshold T [--scorer-config file.json] [--source S]
    bizgraph resolve "<text>" [--json] [-k 5]
    bizgraph resolve-file <in.jsonl> <out.jsonl> [-k 5]
    bizgraph licence-events

DuckDB settings for every command: BIZGRAPH_DUCKDB_MEMORY (default 5GB) and
BIZGRAPH_DUCKDB_THREADS (default 4). Embeddings are used when sentence-transformers is
installed, unless BIZGRAPH_EMBEDDINGS=0.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Sources the batch matcher runs over (Tier 2 registers, GLEIF entities, ACCC notices).
MATCH_SOURCES = ("asic_afsl", "asic_credit", "asic_banned_org", "asic_liquidator", "gleif_l1", "accc_notice")


def _policy(name: str):
    from bizgraph.resolution import ThresholdPolicy

    if name == "strict":
        # Every source treated like the accusation-risk sources.
        return ThresholdPolicy(default=0.97, min_margin=0.10, unknown_type_threshold=0.97)
    return ThresholdPolicy()


def _open(args: argparse.Namespace, read_only: bool = False):
    from bizgraph.config import get_settings
    from bizgraph.store.duckdb_store import DuckDBStore

    store = DuckDBStore(args.db or get_settings().db_path, read_only=read_only)
    store.con.execute(f"SET memory_limit='{os.environ.get('BIZGRAPH_DUCKDB_MEMORY', '5GB')}'")
    store.con.execute(f"SET threads={int(os.environ.get('BIZGRAPH_DUCKDB_THREADS', '4'))}")
    return store


def _matcher(store, args: argparse.Namespace, policy_name: str = "default"):
    from bizgraph.resolution import Matcher

    return Matcher(store, policy=_policy(policy_name), embedder="auto",
                   version_label=getattr(args, "version_label", None) or "m")


def cmd_match(args: argparse.Namespace) -> int:
    with _open(args) as store:
        m = _matcher(store, args, args.policy)
        sources = [args.source_id] if args.source_id else [
            s for s in MATCH_SOURCES if store.records.count(s)
        ]
        for src in sources:
            s = m.match_batch(src)
            print(json.dumps(s.as_dict(), default=str))
    return 0


def cmd_redecide(args: argparse.Namespace) -> int:
    from bizgraph.resolution import ScorerConfig, ThresholdPolicy

    with _open(args) as store:
        base = store.matcher_versions.get(args.run_id)
        if base is None:
            print(f"unknown run {args.run_id}", file=sys.stderr)
            return 2
        pol = base["policy"] if isinstance(base["policy"], dict) else json.loads(base["policy"])
        policy = ThresholdPolicy.from_dict(pol.get("policy", {}))
        if args.threshold is not None:
            policy = dataclasses.replace(policy, default=args.threshold)
        scorer = None
        if args.scorer_config:
            scorer = ScorerConfig.from_dict(json.loads(Path(args.scorer_config).read_text(encoding="utf-8")))
        m = _matcher(store, args)
        s = m.redecide(args.run_id, policy, source_id=args.source, scorer_config=scorer)
        print(json.dumps(s.as_dict(), default=str))
    return 0


def candidate_rows(decision, k: int) -> list[dict[str, Any]]:
    """The candidates a caller should see: identifier matches and name candidates that passed
    the gates (rules R1 to R7), best first. Vetoed and gate-failing candidates are counted in
    the evidence of the decision, not listed (a reference that is not in the graph gets [])."""
    keep = [r for r in decision.ranked if r.eligible or r.features.get("identifier_match")]
    out = []
    for r in keep[:k]:
        f = r.features
        out.append({
            "canonical_key": r.canonical_key,
            "score": r.score,
            "match_type": r.match_type,
            "path": {"named_path": r.path, "found_by": r.found_by, "query_text": r.query_text},
            "evidence": {
                "compared_name": f.get("compared_name"),
                "compared_name_kind": f.get("compared_name_kind"),
                "identifier_match_schemes": f.get("identifier_match_schemes"),
                "jaro_winkler": f.get("jaro_winkler"),
                "token_set_ratio": f.get("token_set_ratio"),
                "token_overlap": f.get("token_overlap"),
                "candidate_extra_tokens": f.get("candidate_extra_tokens"),
                "state_match": f.get("state_match"),
                "embedding_cosine": f.get("embedding_cosine"),
                "scores": r.scores,
                "veto": r.veto,
            },
        })
    return out


def resolve_row(matcher, ref_id: Any, text: str, k: int) -> dict[str, Any]:
    from bizgraph.resolution import Link

    t0 = time.perf_counter()
    d = matcher.resolve(text or "")
    ms = (time.perf_counter() - t0) * 1000
    resolved = isinstance(d, Link)
    return {
        "reference_id": ref_id,
        "reference": text,
        "decision": "resolved" if resolved else "abstained",
        "canonical_key": d.canonical_key if resolved else None,
        "match_type": str(d.match_type) if resolved else None,
        "confidence": d.confidence if resolved else None,
        "abstain_reason": None if resolved else str(d.reason),
        "explanation": d.explanation,
        "disagreement": d.evidence.disagreement if resolved and d.evidence else None,
        "candidates": candidate_rows(d, k),
        "candidates_considered": len(d.ranked),
        "latency_ms": round(ms, 1),
        "matcher_version": matcher.version.version,
    }


def cmd_resolve(args: argparse.Namespace) -> int:
    with _open(args, read_only=True) as store:
        m = _matcher(store, args)
        row = resolve_row(m, None, args.text, args.k)
    if args.json:
        print(json.dumps(row, indent=2, default=str, ensure_ascii=False))
        return 0
    print(f"{row['decision'].upper()}: {row['canonical_key'] or row['abstain_reason']} "
          f"({row['match_type'] or ''} {row['confidence'] or ''}) in {row['latency_ms']} ms")
    print(f"  {row['explanation']}")
    for i, c in enumerate(row["candidates"], 1):
        print(f"  {i}. {c['canonical_key']} {c['match_type']} {c['score']} "
              f"[{c['evidence']['compared_name']}] via {','.join(c['path']['found_by'])}")
    return 0


def cmd_resolve_file(args: argparse.Namespace) -> int:
    rows_in = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with _open(args, read_only=True) as store:
        m = _matcher(store, args)
        m.resolve("warm up")  # first call loads caches; not part of any latency
        lat = []
        with out_path.open("w", encoding="utf-8") as fh:
            for i, r in enumerate(rows_in):
                ref_id = r.get("reference_id", r.get("id", i))
                text = r.get("reference", r.get("text", ""))
                row = resolve_row(m, ref_id, text, args.k)
                lat.append(row["latency_ms"])
                fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
    lat.sort()
    if lat:
        print(f"wrote {len(lat)} rows to {out_path}; latency p50 {lat[len(lat) // 2]} ms, "
              f"p95 {lat[min(len(lat) - 1, int(len(lat) * 0.95))]} ms")
    return 0


def cmd_licence_events(args: argparse.Namespace) -> int:
    from bizgraph.pipeline.licence_history import events_from_store, summarise, write_events

    with _open(args) as store:
        events = events_from_store(store.con)
        n = write_events(store.con, events)
    counts: dict[str, int] = {}
    for (src, et, _d), c in summarise(events).items():
        counts[f"{src}:{et}"] = counts.get(f"{src}:{et}", 0) + c
    print(json.dumps({"licence_events": n, "by_type": counts}))
    return 0


def add_resolution_commands(sub) -> None:
    m = sub.add_parser("match", help="batch-resolve one source (candidates, links, abstentions)")
    m.add_argument("source_id")
    m.add_argument("--policy", choices=("default", "strict"), default="default")
    m.add_argument("--version-label", help="prefix of the matcher version string (default m)")
    m.set_defaults(func=cmd_match)

    ma = sub.add_parser("match-all", help="batch-resolve every loaded matchable source")
    ma.add_argument("--policy", choices=("default", "strict"), default="default")
    ma.add_argument("--version-label")
    ma.set_defaults(func=cmd_match, source_id=None)

    rd = sub.add_parser("redecide", help="re-apply a threshold / scorer config to a stored run (no re-match)")
    rd.add_argument("run_id")
    rd.add_argument("--threshold", type=float, help="new default threshold")
    rd.add_argument("--scorer-config", help="JSON file with ScorerConfig fields; rescores stored features")
    rd.add_argument("--source", help="only this source")
    rd.set_defaults(func=cmd_redecide)

    rs = sub.add_parser("resolve", help="resolve one messy reference")
    rs.add_argument("text")
    rs.add_argument("--json", action="store_true")
    rs.add_argument("-k", type=int, default=5, help="candidates to show")
    rs.set_defaults(func=cmd_resolve)

    rf = sub.add_parser("resolve-file", help="resolve a JSONL of references (id/text or reference_id/reference)")
    rf.add_argument("input")
    rf.add_argument("output")
    rf.add_argument("-k", type=int, default=5)
    rf.set_defaults(func=cmd_resolve_file)

    sub.add_parser("licence-events", help="recompute licence_event from the AFSL / credit snapshots"
                   ).set_defaults(func=cmd_licence_events)
