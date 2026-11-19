"""Render `outputs/evaluation.md` from a labels file and the store (read-only).

Everything numeric is recomputed on each run from the labels and the decisions stored for the version
being evaluated, so `bizgraph evaluate --version <v3>` scores a later matcher on the same labels.
Hand-written discussion lives in `labels/notes_<version>.md` and is appended verbatim if present.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import pandas as pd

from bizgraph.evaluation.metrics import (
    evaluate,
    fmt_ci,
    fmt_pct,
    identifier_truth_sweep,
    load_labels,
    summarise,
)
from bizgraph.evaluation.sampler import STALE_KEY_SQL, decisions_for


def _md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_(none)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(_cell(r[c]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def _cell(v: object) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = str(v).replace("|", "\\|").replace("\n", " ")
    return s


def _metric_table(s: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    rows = []
    for _, r in s.iterrows():
        row = {k: r[k] for k in keys}
        row.update({
            "labelled": int(r["labelled"]),
            "links": int(r["links"]),
            "correct": int(r["tp"]),
            "wrong": int(r["wrong_links"]),
            "precision (95% CI)": f"{fmt_pct(r['precision'])} ({fmt_ci(r['p_lo'], r['p_hi'], r['links'])})",
            "true target in graph": int(r["true_target_in_graph"]),
            "missed": int(r["fn"]),
            "recall (95% CI)": f"{fmt_pct(r['recall'])} ({fmt_ci(r['r_lo'], r['r_hi'], r['true_target_in_graph'])})",
            "weighted P / R": f"{fmt_pct(r['precision_w'])} / {fmt_pct(r['recall_w'])}",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _names(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.DataFrame:
    keys = set(df["target"].dropna()) | {k for k in df["true_canonical_key"] if str(k).startswith("urn:")}
    con.register("rk", pd.DataFrame({"canonical_key": sorted(keys) or [""]}))
    pn = dict(con.execute("SELECT canonical_key, name FROM party_canonical JOIN rk USING (canonical_key)").fetchall())
    con.register("rr", df[["source", "record_id"]].drop_duplicates())
    rn = {(s, r): n for s, r, n in con.execute(
        "SELECT s.source, s.record_id, any_value(s.name_raw) FROM source_record s JOIN rr USING (source, record_id) "
        "GROUP BY ALL").fetchall()}
    con.unregister("rk")
    con.unregister("rr")
    df = df.copy()
    df["reference"] = [rn.get((s, r), "") for s, r in zip(df["source"], df["record_id"])]
    df["target_name"] = [pn.get(t, "") if isinstance(t, str) else "" for t in df["target"]]
    df["true_name"] = [pn.get(t, t) for t in df["true_canonical_key"]]
    return df


def related_versions(con: duckdb.DuckDBPyConnection, version: str) -> dict[str, list[str]]:
    """Name-only run(s) of the same code hash, and the redecides built on them."""
    rows = con.execute("SELECT version, policy FROM matcher_version").fetchall()
    prefix = version.split("-")[1] if version.count("-") >= 2 else ""
    name_only, redecide = [], []
    for v, pol in rows:
        p = json.loads(pol) if pol else {}
        if p.get("config", {}).get("strip_identifiers") and not p.get("candidates_run_id") and prefix in v:
            name_only.append(v)
    for v, pol in rows:
        p = json.loads(pol) if pol else {}
        if p.get("candidates_run_id") in name_only:
            redecide.append(v)
    return {"name_only": sorted(name_only), "redecide": sorted(redecide)}


def blocking_check(con: duckdb.DuckDBPyConnection, df: pd.DataFrame, version: str) -> tuple[int, int, list[str]]:
    """Labelled records whose true key is in the graph: was it among the stored candidates?"""
    pol = con.execute("SELECT policy FROM matcher_version WHERE version = ?", [version]).fetchall()
    run = (json.loads(pol[0][0]).get("candidates_run_id") if pol and pol[0][0] else None) or version
    d = df[df["in_graph"] & ~df["unsure"]][["source", "record_id", "true_canonical_key", "sample_id"]]
    if d.empty:
        return 0, 0, []
    con.register("bc", d)
    hit = con.execute(
        "WITH c AS (SELECT c.source, c.record_id, coalesce(m.new_key, c.canonical_key) AS canonical_key "
        "FROM candidate c JOIN bc ON bc.source = c.source AND bc.record_id = c.record_id LEFT JOIN ("
        + STALE_KEY_SQL.format(col="canonical_key", rel="(SELECT canonical_key FROM candidate WHERE run_id = $run)")
        + ") m ON m.old_key = c.canonical_key WHERE c.run_id = $run) "
        "SELECT DISTINCT bc.sample_id FROM bc JOIN c ON c.source = bc.source AND c.record_id = bc.record_id "
        "AND c.canonical_key = bc.true_canonical_key", {"run": run}).fetchall()
    con.unregister("bc")
    got = {h for (h,) in hit}
    missed = sorted(set(d["sample_id"]) - got)
    return len(got), len(d), missed


def comparison_table(con: duckdb.DuckDBPyConnection, versions: list[str], labels: pd.DataFrame) -> pd.DataFrame:
    """The same labels scored against several versions (sample counts; UNSURE excluded)."""
    rows = []
    for v in versions:
        known = con.execute("SELECT count(*) FROM matcher_version WHERE version = ?", [v]).fetchall()[0][0]
        if not known:
            continue
        d = evaluate(con, v, labels)
        for grp, g in [("all", d), *(("name links" if k == "name" else k, g) for k, g in d.assign(
                pg=[("exact" if str(o).startswith("EXACT_") else "name") if dd == "link" else "abstain"
                    for dd, o in zip(d["decision"], d["outcome"])]).groupby("pg") if k != "abstain")]:
            s = summarise(g, None).iloc[0]
            rows.append({"version": v, "subset": grp, "labelled": int(s["labelled"]), "links": int(s["links"]),
                         "wrong": int(s["wrong_links"]),
                         "precision (95% CI)": f"{fmt_pct(s['precision'])} ({fmt_ci(s['p_lo'], s['p_hi'], s['links'])})",
                         "missed": int(s["fn"]),
                         "recall (95% CI)": f"{fmt_pct(s['recall'])} ({fmt_ci(s['r_lo'], s['r_hi'], s['true_target_in_graph'])})"})
    return pd.DataFrame(rows)


def build_report(con: duckdb.DuckDBPyConnection, version: str, labels_path: Path,
                 notes_path: Path | None = None, sweep: bool = True,
                 compare_versions: list[str] | None = None) -> str:
    labels = load_labels(labels_path)
    df = evaluate(con, version, labels)
    pop = decisions_for(con, version)
    lines: list[str] = []
    w = lines.append
    w(f"# Evaluation of matcher version `{version}`\n")

    # ---------------------------------------------------------------- composition
    w("## 1. Sample and labels\n")
    lab = labels.copy()
    lab["class"] = lab["true_canonical_key"].where(lab["true_canonical_key"].isin(["NONE", "NOT_IN_GRAPH", "UNSURE"]),
                                                   "party in graph")
    lab["blind"] = ~lab["labeller"].str.contains("NOT blind", na=False)
    comp = (lab.groupby(["source", "class"]).size().unstack(fill_value=0).reset_index())
    comp["total"] = comp.drop(columns="source").sum(axis=1)
    w(f"{len(lab)} labelled records: {int(lab['blind'].sum())} labelled blind (evidence file only, no score or "
      f"decision), {int((~lab['blind']).sum())} labelled in a census that was not blind (see notes, section N2). "
      f"UNSURE: {int((lab['class'] == 'UNSURE').sum())}, excluded from every metric.\n")
    w(_md(comp))
    w("")
    strata = df.groupby("stratum").agg(labelled=("record_id", "size")).reset_index()
    strata = strata.merge(pop.groupby("stratum").size().rename("population").reset_index(), on="stratum", how="left")
    strata = strata.sort_values("stratum")
    w(f"Strata of `{version}` that hold labelled records (stratum = source | decision | match type or abstain "
      "reason | score band | segment; segment: GLEIF `foreign` (legal jurisdiction not AU), `au-person-abn` (stated ABN is a sole trader) or `au`; AFSL / credit `ended` or `current` licence):\n")
    w(_md(strata[["stratum", "population", "labelled"]]))
    unl = pop.groupby("stratum").size().rename("population").reset_index()
    unl = unl[~unl["stratum"].isin(strata["stratum"])]
    if len(unl):
        w(f"\n{len(unl)} strata with {int(unl['population'].sum()):,} decisions have no labelled record (mostly "
          "exact-path strata and small bands); they do not enter the weighted estimates. Top by size:\n")
        w(_md(unl.sort_values("population", ascending=False).head(12)))

    # ---------------------------------------------------------------- metrics
    w("\n## 2. Precision and recall\n")
    w("Precision = links to the labelled true party / links. Recall = links to the true party / records whose "
      "true party is in the graph (NONE and NOT_IN_GRAPH records are not in the recall denominator; an abstention "
      "on them is correct). `sample` columns are raw counts in the labelled sample with Wilson 95% intervals. "
      "`weighted` re-weights each labelled record by population / labelled of its stratum (post-stratification), "
      "so oversampled strata (near-threshold abstentions, the foreign census) do not dominate; strata with no "
      "labelled record are missing from it.\n")
    w("### By source pair\n")
    w(_md(_metric_table(summarise(df, "source_pair"), ["source_pair"])))
    w("\n### By tier\n")
    w(_md(_metric_table(summarise(df, "tier"), ["tier"])))
    w("\n### By tier and path (exact vs name)\n")
    df["path_label"] = df["path"].map({"exact": "exact link", "name": "name link", "abstain": "abstained"})
    df["path_group"] = [("exact" if o.startswith("EXACT_") else "name") if d == "link" else "abstain"
                        for d, o in zip(df["decision"], df["outcome"].astype(str))]
    t = summarise(df, ["tier", "source", "path_group"])
    w(_md(_metric_table(t, ["tier", "source", "path_group"])))
    w("\n### By match type (links only)\n")
    w(_md(_metric_table(summarise(df[df["decision"] == "link"], ["source", "outcome"]), ["source", "outcome"])))
    w("\n### GLEIF name-path links by jurisdiction segment\n")
    g = df[(df["source"] == "gleif_l1") & (df["decision"] == "link") & (df["path_group"] == "name")].copy()
    g["segment"] = g["stratum"].str.split("|").str[-1]
    w(_md(_metric_table(summarise(g, "segment"), ["segment"])))
    allt = summarise(df, None).iloc[0]
    w(f"\nOverall (all labelled, sample counts): {int(allt['links'])} links, {int(allt['wrong_links'])} wrong, "
      f"precision {fmt_pct(allt['precision'])} ({fmt_ci(allt['p_lo'], allt['p_hi'], allt['links'])}); recall "
      f"{fmt_pct(allt['recall'])} over {int(allt['true_target_in_graph'])} in-graph records.\n")

    if compare_versions:
        w("\n### The same labels against other matcher versions\n")
        w("Sample counts on every labelled record each version decided. The label sample was drawn on v2's and "
          "then v3's strata, so these rows compare versions on the same records; they are not population estimates "
          "for the other versions.\n")
        w(_md(comparison_table(con, [version, *compare_versions], labels)))

    # ---------------------------------------------------------------- errors
    w("\n## 3. Every wrong link and every miss in the labelled set\n")
    named = _names(con, df)
    wrong = named[named["fp"]].sort_values(["source", "outcome"])
    ev = labels.set_index("sample_id")["evidence"].to_dict()
    blind = labels.set_index("sample_id")["labeller"].to_dict()
    wrong_t = pd.DataFrame({
        "sample_id": wrong["sample_id"], "source": wrong["source"], "record_id": wrong["record_id"],
        "reference": wrong["reference"], "match_type": wrong["outcome"], "score": wrong["score"].round(4),
        "linked to": wrong["target"] + " " + wrong["target_name"],
        "true target": wrong["true_name"],
        "blind": ["no" if "NOT blind" in str(blind.get(s, "")) else "yes" for s in wrong["sample_id"]],
        "evidence": [ev.get(s, "") for s in wrong["sample_id"]],
    })
    w(f"**Wrong links: {len(wrong_t)}.**\n")
    w(_md(wrong_t))
    miss = named[named["fn"] & (named["decision"] == "abstain")].sort_values(["source", "outcome"])
    miss_t = pd.DataFrame({
        "sample_id": miss["sample_id"], "source": miss["source"], "reference": miss["reference"],
        "abstain reason": miss["outcome"], "best candidate": miss["target"],
        "true target": miss["true_canonical_key"] + " " + miss["true_name"].where(miss["true_name"] != miss["true_canonical_key"], ""),
    })
    w(f"\n**Missed (abstained although the true party is in the graph): {len(miss_t)}.**\n")
    w(_md(miss_t))
    uns = named[named["unsure"]]
    uns_t = pd.DataFrame({"sample_id": uns["sample_id"], "source": uns["source"], "reference": uns["reference"],
                          "decision": uns["decision"], "outcome": uns["outcome"],
                          "target": uns["target"] + " " + uns["target_name"],
                          "why unsure": [ev.get(s, "") for s in uns["sample_id"]]})
    w(f"\n**UNSURE (excluded): {len(uns_t)}.** The decision is shown so a human can settle them.\n")
    w(_md(uns_t))

    # ---------------------------------------------------------------- blocking
    got, tot, missed_ids = blocking_check(con, df, version)
    w("\n## 4. Blocking recall, own check on labelled records\n")
    w(f"Of {tot} labelled records whose true party is in the graph, the true party was among the stored "
      f"candidates of `{version}` for {got} ({fmt_pct(got / tot if tot else float('nan'))}). "
      + (f"Not in the candidate set: {', '.join(missed_ids)}." if missed_ids else "") + "\n")
    rel = related_versions(con, version)
    if rel["name_only"]:
        for nv in rel["name_only"]:
            ndf = evaluate(con, nv, labels)
            g2, t2, m2 = blocking_check(con, ndf, nv)
            w(f"Identifier-stripped run `{nv}`: true party among stored candidates for {g2} of {t2} labelled in-graph "
              f"records ({fmt_pct(g2 / t2 if t2 else float('nan'))})" + (f"; missing: {', '.join(m2)}" if m2 else "") + ".\n")

    # ---------------------------------------------------------------- name-only + sweep
    if rel["name_only"] and sweep:
        w("\n## 5. Name path without identifiers, and the threshold sweep\n")
        w("AFSL and credit records re-matched with every identifier stripped. Truth is the ABN (else ACN) the "
          "register itself prints on the record, looked up in the canonical identifier table: independent of the "
          "matcher's decisions. `blocking recall` = the true party is among the run's stored candidates. Recall "
          "here is over records that have identifier truth.\n")
        sw = identifier_truth_sweep(con, rel["name_only"] + rel["redecide"])
        sw_t = pd.DataFrame({
            "version": sw["version"], "source": sw["source"], "threshold": sw["threshold"],
            "truth records": sw["truth_records"], "links": sw["links"], "correct": sw["correct"],
            "stale keys remapped": sw["stale_keys"],
            "wrong": sw["wrong"], "precision": sw["precision"].map(fmt_pct), "recall": sw["recall"].map(fmt_pct),
            "blocking recall": sw["blocking_recall"].map(lambda x: f"{100 * x:.2f}%"),
            "abstentions": sw["abstain_reasons"].map(lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items()))),
        }).sort_values(["source", "threshold", "version"])
        w(_md(sw_t))
        for nv in rel["name_only"]:
            ndf = evaluate(con, nv, labels)
            w(f"\nLabelled-sample view of `{nv}` (the same labels, this version's decisions):\n")
            w(_md(_metric_table(summarise(ndf, ["source", "decision"]), ["source", "decision"])))

    # ---------------------------------------------------------------- human check list
    w("\n## 6. Rows a human should check first\n")
    first = labels[(labels["source"].isin(["accc_notice", "asic_banned_org"]))]
    chk = df[df["sample_id"].isin(first["sample_id"]) & (df["decision"] == "link")]
    w("1. Every ACCC and banned-organisation **link** (a wrong one publishes an accusation): "
      + ", ".join(sorted(chk["sample_id"])) + ".")
    w("2. Every ACCC and banned-organisation abstention labelled with a party in the graph: "
      + (", ".join(sorted(df[df["sample_id"].isin(first["sample_id"]) & df["fn"]]["sample_id"])) or "none") + ".")
    w("3. Every wrong link in section 3 and every UNSURE row.")
    w("4. The non-blind census rows (labeller column says NOT blind), starting with the ones labelled as a "
      "party (foreign-company registrations, branches).")
    w("5. Ten random blind labels of each class (party / NONE / NOT_IN_GRAPH) to estimate the labeller's own "
      "error rate.\n")

    if notes_path and notes_path.exists():
        w("\n" + notes_path.read_text(encoding="utf-8"))
    return "\n".join(lines) + "\n"


def write_report(con: duckdb.DuckDBPyConnection, version: str, labels_path: Path, out_path: Path,
                 notes_path: Path | None = None, compare_versions: list[str] | None = None) -> Path:
    text = build_report(con, version, labels_path, notes_path, compare_versions=compare_versions)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path
