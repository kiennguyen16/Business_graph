"""`bizgraph evaluate` and `bizgraph eval-sample` (registered from bizgraph.cli).

Both open the store read-only, so they can run against a snapshot while another process writes the live
store: `bizgraph --db data/eval_snapshot_20261118.duckdb evaluate --version m-1465a4ba-e5444596`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bizgraph.config import REPO_ROOT, get_settings


def _connect(args: argparse.Namespace):
    import duckdb

    path = args.db or get_settings().db_path
    return duckdb.connect(str(path), read_only=True, config={"memory_limit": args.memory_limit})


def _labels_for(version: str, explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    own = REPO_ROOT / "labels" / f"labels_{version}.csv"
    if own.exists():
        return own
    # Labels are keyed by (source, record_id), so the newest labels file scores any version.
    found = sorted((REPO_ROOT / "labels").glob("labels_*.csv"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def cmd_evaluate(args: argparse.Namespace) -> int:
    from bizgraph.evaluation.report import write_report

    labels = _labels_for(args.version, args.labels)
    if labels is None or not labels.exists():
        print("no labels file found (labels/labels_<version>.csv); run eval-sample and label it first",
              file=sys.stderr)
        return 2
    notes = Path(args.notes) if args.notes else None
    if notes is None:
        for cand in (REPO_ROOT / "labels" / f"notes_{args.version}.md",
                     *sorted((REPO_ROOT / "labels").glob("notes_*.md"))):
            if cand.exists():
                notes = cand
                break
    con = _connect(args)
    try:
        known = con.execute("SELECT count(*) FROM matcher_version WHERE version = ?", [args.version]).fetchall()[0][0]
        if not known:
            print(f"unknown matcher version {args.version}", file=sys.stderr)
            return 2
        out = write_report(con, args.version, labels, Path(args.out), notes, compare_versions=args.compare)
    finally:
        con.close()
    print(f"wrote {out} (labels {labels}, notes {notes})")
    return 0


def cmd_eval_sample(args: argparse.Namespace) -> int:
    import pandas as pd

    from bizgraph.evaluation.sampler import PLANS, write_sample

    exclude = None
    if args.exclude_labelled:
        frames = [pd.read_csv(p, dtype=str) for p in (REPO_ROOT / "labels").glob("labels_*.csv")]
        if frames:
            lab = pd.concat(frames)
            exclude = set(zip(lab["source"], lab["record_id"]))
    con = _connect(args)
    try:
        blind, dec, sample = write_sample(con, args.version, Path(args.out_dir), args.name_only_version,
                                          args.seed, plan=PLANS[args.plan], exclude=exclude)
    finally:
        con.close()
    print(f"{len(sample)} records drawn; blind file {blind}; decisions (do not open before labelling) {dec}")
    return 0


def add_evaluation_commands(sub) -> None:
    ev = sub.add_parser("evaluate", help="precision / recall of a matcher version against the hand labels")
    ev.add_argument("--version", required=True, help="matcher version id (any version in the store)")
    ev.add_argument("--labels", help="labels CSV (default labels/labels_<version>.csv, else the newest)")
    ev.add_argument("--notes", help="hand-written discussion appended to the report (default labels/notes_*.md)")
    ev.add_argument("--out", default=str(REPO_ROOT / "outputs" / "evaluation.md"))
    ev.add_argument("--compare", action="append", metavar="VERSION",
                    help="also score these versions on the same labels (repeatable)")
    ev.add_argument("--memory-limit", default="3GB")
    ev.set_defaults(func=cmd_evaluate)

    sp = sub.add_parser("eval-sample", help="draw the stratified blind label sample for a matcher version")
    sp.add_argument("--version", required=True)
    sp.add_argument("--name-only-version", help="identifier-stripped run to sample name-path links from")
    sp.add_argument("--seed", type=int, default=20261118)
    sp.add_argument("--plan", choices=["default", "topup"], default="default",
                    help="quota plan (sampler.PLANS); 'topup' with --exclude-labelled adds records for a new version")
    sp.add_argument("--out-dir", default=str(REPO_ROOT / "labels"))
    sp.add_argument("--exclude-labelled", action="store_true",
                    help="skip records already in a labels file (top up a sample for a new version)")
    sp.add_argument("--memory-limit", default="3GB")
    sp.set_defaults(func=cmd_eval_sample)
