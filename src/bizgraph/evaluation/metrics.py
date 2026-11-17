"""Precision and recall of one matcher version against blind labels.

Label values in `true_canonical_key`:
* a canonical key: the party this record refers to, present in the graph;
* `NOT_IN_GRAPH`: the record refers to a real business that is not a party in this graph (outside the
  WA/TAS + Tier 2 slice), so the correct decision is to abstain;
* `NONE`: no business in any register we can see matches (or the record is a person / foreign entity);
* `UNSURE`: the labeller could not decide; excluded from every metric and counted.

Per labelled record: a link to the true key is a true positive; a link anywhere else is a false
positive (a wrong link); an abstention on a record whose true key is in the graph is a false negative.
Precision = TP / links. Recall = TP / records whose true target is in the graph.

Two estimates are given: `sample` (raw counts in the labelled sample, Wilson 95% interval) and
`weighted` (post-stratified: each labelled record weighs population(stratum) / labelled(stratum) under
the version being evaluated, so oversampled strata such as near-threshold abstentions do not dominate).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import duckdb
import pandas as pd

from bizgraph.evaluation.sampler import decisions_for, tier_of

SPECIAL = ("NONE", "NOT_IN_GRAPH", "UNSURE")


def wilson_interval(successes: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; (0, 1) when n == 0."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_labels(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    df["true_canonical_key"] = df["true_canonical_key"].str.strip()
    return df


def classify(decisions: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Join labels to one version's decisions and mark tp / fp / fn / tn per record."""
    cols = [c for c in ("sample_id", "source", "record_id", "true_canonical_key") if c in labels.columns]
    lab = labels[cols].drop_duplicates(["source", "record_id"])
    df = decisions.merge(lab, on=["source", "record_id"], how="inner")
    truth = df["true_canonical_key"]
    df["unsure"] = truth == "UNSURE"
    df["in_graph"] = ~truth.isin(SPECIAL) & (truth != "")
    is_link = df["decision"] == "link"
    df["tp"] = is_link & df["in_graph"] & (df["target"] == truth)
    df["fp"] = is_link & ~df["unsure"] & ~df["tp"]
    df["fn"] = ~df["unsure"] & df["in_graph"] & ~df["tp"]
    df["tn"] = ~is_link & ~df["unsure"] & ~df["in_graph"]
    return df


def attach_weights(df: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    pop = population.groupby("stratum").size().rename("pop")
    lab = df[~df["unsure"]].groupby("stratum").size().rename("labelled")
    out = df.merge(pop, left_on="stratum", right_index=True, how="left")
    out = out.merge(lab, left_on="stratum", right_index=True, how="left")
    out["weight"] = (out["pop"] / out["labelled"]).where(~out["unsure"], 0.0).fillna(0.0)
    return out


def _party_source(con: duckdb.DuckDBPyConnection, keys: set[str]) -> dict[str, str]:
    if not keys:
        return {}
    con.register("ps_keys", pd.DataFrame({"canonical_key": sorted(keys)}))
    rows = con.execute(
        "SELECT canonical_key, source FROM party_canonical JOIN ps_keys USING (canonical_key)"
    ).fetchall()
    con.unregister("ps_keys")
    return dict(rows)


def add_dimensions(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.DataFrame:
    keys = set(df.loc[df["in_graph"], "true_canonical_key"]) | set(df.loc[df["decision"] == "link", "target"])
    psrc = _party_source(con, {k for k in keys if isinstance(k, str)})

    def pair(row: pd.Series) -> str:
        k = row["true_canonical_key"] if row["in_graph"] else (row["target"] if row["decision"] == "link" else None)
        return f"{row['source']}->{psrc.get(k, 'none') if k else 'none'}"

    df = df.copy()
    df["source_pair"] = df.apply(pair, axis=1) if len(df) else []
    df["tier"] = [f"tier {tier_of(s)}" for s in df["source"]]
    return df


def summarise(df: pd.DataFrame, by: str | list[str] | None) -> pd.DataFrame:
    """Counts, sample precision / recall with Wilson intervals, and weighted estimates per group."""
    d = df[~df["unsure"]]
    groups = [((), d)] if by is None else list(d.groupby(by))
    rows = []
    for key, g in groups:
        links = int((g["decision"] == "link").sum())
        tp, fp = int(g["tp"].sum()), int(g["fp"].sum())
        in_graph = int(g["in_graph"].sum())
        w = g["weight"] if "weight" in g else pd.Series(1.0, index=g.index)
        wl = float((w * (g["decision"] == "link")).sum())
        wtp = float((w * g["tp"]).sum())
        wig = float((w * g["in_graph"]).sum())
        plo, phi = wilson_interval(tp, links)
        rlo, rhi = wilson_interval(tp, in_graph)
        row = {
            "labelled": len(g), "links": links, "tp": tp, "wrong_links": fp,
            "abstain": int((g["decision"] == "abstain").sum()), "fn": int(g["fn"].sum()),
            "tn": int(g["tn"].sum()), "true_target_in_graph": in_graph,
            "precision": tp / links if links else math.nan, "p_lo": plo, "p_hi": phi,
            "recall": tp / in_graph if in_graph else math.nan, "r_lo": rlo, "r_hi": rhi,
            "precision_w": wtp / wl if wl else math.nan, "recall_w": wtp / wig if wig else math.nan,
        }
        if by is not None:
            names = [by] if isinstance(by, str) else by
            vals = key if isinstance(key, tuple) else (key,)
            row = {**dict(zip(names, vals)), **row}
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate(con: duckdb.DuckDBPyConnection, version: str, labels: pd.DataFrame) -> pd.DataFrame:
    """Per-record classification of `version` against the labels, with weights and dimensions."""
    population = decisions_for(con, version)
    df = classify(population, labels)
    df = attach_weights(df, population)
    return add_dimensions(con, df)


# --------------------------------------------------------------------------------------------------
# Identifier-truth checks over the whole population (no labels needed)


def identifier_truth(con: duckdb.DuckDBPyConnection, sources: tuple[str, ...] = ("asic_afsl", "asic_credit")
                     ) -> pd.DataFrame:
    """True key per record from the identifier the source register itself prints (ABN first, else ACN).

    Independent of the matcher: it reads `source_record` and the canonical identifier table only.
    """
    con.register("it_src", pd.DataFrame({"source": list(sources)}))
    df = con.execute(
        """
        SELECT r.source, r.record_id,
               coalesce(ia.canonical_key, ic.canonical_key) AS truth,
               CASE WHEN ia.canonical_key IS NOT NULL THEN 'abn' WHEN ic.canonical_key IS NOT NULL THEN 'acn' END AS via
        FROM source_record r
        LEFT JOIN identifier ia ON ia.scheme = 'abn' AND ia.value = r.abn
        LEFT JOIN identifier ic ON ic.scheme = 'acn' AND ic.value = r.acn
        WHERE r.source IN (SELECT source FROM it_src)
        QUALIFY row_number() OVER (PARTITION BY r.source, r.record_id ORDER BY r.snapshot_date DESC) = 1
        """
    ).df()
    con.unregister("it_src")
    return df


def identifier_truth_sweep(con: duckdb.DuckDBPyConnection, versions: list[str],
                           sources: tuple[str, ...] = ("asic_afsl", "asic_credit")) -> pd.DataFrame:
    truth = identifier_truth(con, sources)
    truth = truth[truth["truth"].notna()]
    rows = []
    for v in versions:
        dec = decisions_for(con, v)
        dec = dec[dec["source"].isin(sources)]
        policy = con.execute("SELECT policy FROM matcher_version WHERE version = ?", [v]).fetchall()[0][0]
        import json

        pol = json.loads(policy)
        thr = pol.get("policy", {}).get("default")
        run = pol.get("candidates_run_id") or v
        for s in sources:
            t = truth[truth["source"] == s]
            d = dec[dec["source"] == s].merge(t, on=["source", "record_id"], how="inner")
            links = d[d["decision"] == "link"]
            correct = int((links["target"] == links["truth"]).sum())
            blocked = con.execute(
                "SELECT count(DISTINCT c.record_id) FROM candidate c JOIN ("
                "SELECT * FROM t_view) t ON t.source = c.source AND t.record_id = c.record_id "
                "AND t.truth = c.canonical_key WHERE c.run_id = ?", [run]
            ).fetchall()[0][0] if _register(con, "t_view", t) else 0
            con.unregister("t_view")
            rows.append({
                "version": v, "source": s, "threshold": thr, "truth_records": len(t),
                "decided": len(d), "links": len(links), "correct": correct,
                "wrong": len(links) - correct,
                "precision": correct / len(links) if len(links) else math.nan,
                "recall": correct / len(d) if len(d) else math.nan,
                "blocking_recall": blocked / len(d) if len(d) else math.nan,
                "abstain_reasons": d.loc[d["decision"] == "abstain", "outcome"].value_counts().to_dict(),
            })
    return pd.DataFrame(rows)


def _register(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> bool:
    con.register(name, df)
    return True


def fmt_pct(x: float) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f}%"


def fmt_ci(lo: float, hi: float, n: int) -> str:
    return "n/a" if not n else f"{100 * lo:.1f} to {100 * hi:.1f}"


Formatter = Callable[[float], str]
