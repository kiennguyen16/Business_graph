"""Business graph demo (Streamlit). Run: streamlit run demo/app.py

Pages: Resolve, Entity, Traversals, Abstentions, Projection. Plain tables on purpose: the
point is that the graph and the resolver's reasoning are legible, not the styling.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHAIN_EXAMPLES, Backend, today  # noqa: E402

st.set_page_config(page_title="AU/NZ business graph", layout="wide")
PAGES = ["Resolve", "Entity", "Traversals", "Abstentions", "Projection"]
# (button label, text sent to resolve)
EXAMPLES = [
    ("CBA", "Commonwealth Bank of Australia"),
    ("CSC (near-name trap)", "Commonwealth Superannuation Corporation"),
    ("CBA + ABN", "Commonwealth Bank of Aust ABN 48 123 123 124"),
    ("Rio Tinto plc (foreign)", "Rio Tinto plc"),
    ("AMP Capital", "AMP Capital"),
    ("Bluegum Trust", "Bluegum Trust"),
    ("eDreams (not in graph)", "Vacaciones eDreams"),
]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        /* Palette after firmable.ai (navy ink, orange accent, purple secondary, Inter). --teal is the accent
           variable name used throughout; it now holds the darker orange for readable text on white. */
        :root { --ink:#112337; --muted:#585E6A; --teal:#C14905; --accent:#F15B06; --purple:#9C72DC;
                --navy:#112337; --line:#E4E7EC; --soft:#F2F3F5; }
        div[data-testid="stButtonGroup"] button[kind="segmented_controlActive"] { border-bottom-color: var(--accent) !important; }
        div[data-testid="stHorizontalBlock"] button[kind="secondary"] { border-radius: 999px; }
        a { color: var(--teal); }
        /* legibility: darker body, caption and label text */
        p, li, label, [data-testid="stMarkdownContainer"] { color: var(--ink); }
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
        /* page tabs (segmented control styled as tabs) */
        div[data-testid="stButtonGroup"] { border-bottom: 2px solid var(--line); margin-bottom: .6rem; }
        div[data-testid="stButtonGroup"] button { border: none !important; border-radius: 0 !important; background: transparent !important;
            color: var(--muted) !important; font-weight: 600; font-size: 1rem; padding: .7rem 1.1rem; margin-bottom: -2px;
            border-bottom: 3px solid transparent !important; box-shadow: none !important; }
        div[data-testid="stButtonGroup"] button:hover { color: var(--teal) !important; }
        div[data-testid="stButtonGroup"] button[kind="segmented_controlActive"] { color: var(--teal) !important; border-bottom-color: var(--teal) !important; }
        /* sidebar table of contents */
        [data-testid="stSidebar"] .toc-title { font-size: .8rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 .4rem; }
        [data-testid="stSidebar"] .toc-current { font-weight: 700; color: var(--teal); padding: .35rem 0; border-left: 3px solid var(--teal); padding-left: .6rem; }
        [data-testid="stSidebar"] button[kind="tertiary"] { justify-content: flex-start; padding: .35rem 0 .35rem .75rem; color: var(--ink); font-weight: 500; }
        [data-testid="stSidebar"] button[kind="tertiary"]:hover { color: var(--teal); }
        html, body, [class*="css"] { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
        .block-container { max-width: 1440px; padding-top: 2.2rem; padding-bottom: 3rem; }
        h1, h2, h3 { color: var(--ink); letter-spacing: -0.025em; }
        h1 { font-weight: 700; }
        [data-testid="stSidebar"] { border-right: 1px solid var(--line); }
        [data-testid="stSidebar"] > div:first-child { padding-top: 2rem; }
        div[data-testid="stHorizontalBlock"] button { min-height: 2.8rem; border-radius: 999px; font-weight: 600; }
        div[data-testid="stHorizontalBlock"] button[kind="secondary"] { border-color: var(--line); background: #fff; color: var(--navy); }
        div[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover { border-color: var(--teal); color: var(--teal); }
        div[data-testid="stRadio"] > div { gap: .45rem; }
        div[data-testid="stRadio"] label { border: 1px solid var(--line); border-radius: 999px; padding: .45rem .9rem; background: #fff; }
        div[data-testid="stRadio"] label:has(input:checked) { border-color: var(--teal); background: #E6FFFA; color: var(--navy); }
        div[data-testid="stRadio"] label p { font-weight: 600; }
        [data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 12px; background: #fff; }
        [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
        .status-badge { display:inline-flex; align-items:center; gap:.45rem; padding:.5rem .85rem; border-radius:999px; font-weight:700; font-size:.88rem; margin:.35rem 0 1rem; }
        .status-resolved { color:#146C43; background:#D1FAE5; border:1px solid #A7F3D0; }
        .status-abstained { color:#92400E; background:#FEF3C7; border:1px solid #FCD34D; }
        .eyebrow { color:var(--teal); font-size:.78rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
        @media (prefers-color-scheme: dark) { .status-resolved { color:#A7F3D0; background:#064E3B; } .status-abstained { color:#FDE68A; background:#78350F; } }
        </style>
        """, unsafe_allow_html=True,
    )


@st.cache_resource(show_spinner="Loading store, matcher and graph (first load only)...")
def backend() -> Backend:
    return Backend()


def jsonable(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


def df(rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    d = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    for c in d.columns:  # dicts / lists / dates as text so Arrow never chokes
        if d[c].dtype == object:
            d[c] = d[c].map(lambda x: json.dumps(x, default=str) if isinstance(x, (dict, list, tuple, set)) else x)
    return d


def goto(page: str, **params: str) -> None:
    st.session_state["nav_to"] = page  # applied before the page radio is drawn on the next run
    st.query_params.clear()
    st.query_params["page"] = page
    for k, v in params.items():
        st.query_params[k] = v
    if "key" in params:
        st.session_state["entity_key"] = st.session_state["entity_target"] = params["key"]
    st.rerun()


def entity_link_col(label: str = "open") -> Any:
    return st.column_config.LinkColumn(label, display_text="open entity")


def entity_url(key: str | None) -> str | None:
    return f"./?page=Entity&key={key}" if key else None


# --------------------------------------------------------------------------- header

def header(b: Backend) -> None:
    st.title("AU/NZ Business Graph")
    mode = "trimmed demo bundle" if b.is_bundle else "full eval snapshot"
    sem = "on (local MiniLM)" if b.matcher.embedder else "off"
    st.markdown(
        f"Entity resolution over ABR, ASIC, GLEIF and ACCC registers. Matcher `{b.matcher_version}` · "
        f"semantic path {sem} · precision first: it abstains rather than guess."
    )
    with st.expander("What is real and what is reduced in this demo"):
        st.markdown(
        f"**Real:** {mode} `{b.db_path.name}` (read-only DuckDB), matcher decisions of `{b.matcher_version}`, "
        f"graph queries over {b.endpoint_desc}, live `resolve` with the stored threshold policy. "
        f"**Stubbed or reduced:** semantic (embedding) path "
        f"{'ON' if b.matcher.embedder else 'OFF (no model in this process; name paths are exact + fuzzy)'}; "
        + ("bundle holds a subset of parties (Tier 2/3 linked, GLEIF ownership slice, licence-event holders, "
           "example-query candidates, a random sample), so blocking finds fewer candidates than the full store "
           "for names outside it; " if b.is_bundle else "")
        + ("no Fuseki on this host: graph traversals for the example inputs are precomputed at bundle build "
           "time against the same graphs, others run slowly on rdflib; " if not b.fuseki_url else "")
        + "ACCC notices are the 20-row register extract; licence end dates are bounds from register snapshot diffs, "
          "not true dates; no person-level director data."
        )
        if b.live_version != b.matcher_version:
            st.caption(f"Live resolve runs code version `{b.live_version}`; stored links and abstentions are from "
                   f"`{b.matcher_version}` (set BIZGRAPH_MATCHER_VERSION to pick another stored version).")


# --------------------------------------------------------------------------- evidence

REASONS = {
    "NO_CANDIDATE": "no generator found anything",
    "BELOW_THRESHOLD": "best eligible score under the threshold, or no candidate passed the name gate",
    "AMBIGUOUS": "top two parties too close (margin rule)",
    "IDENTIFIER_CONFLICT": "identifiers point at different parties, or a name match is vetoed by an identifier",
    "PARTY_TYPE_CONFLICT": "person vs organisation",
    "JURISDICTION_MISMATCH": "a foreign entity whose only name match is an Australian-incorporated party, not "
                             "the foreign body's Australian registration (ARBN, ABR OIE, ASIC FNOS / RACN)",
    "QUARANTINED_TARGET": "the target party is quarantined",
}


def _v(x: Any) -> str:
    if x is None or x == [] or x == "":
        return ""
    return ", ".join(map(str, x)) if isinstance(x, (list, tuple)) else str(x)


def gates_table(f: dict[str, Any]) -> pd.DataFrame:
    """The arbiter's gates for one candidate, one row each, in rule order, from its feature vector."""
    g = f.get
    rows = []

    def add(rule: str, gate: str, ok: bool | None, ref: Any = "", cand: Any = "") -> None:
        rows.append({"rule": rule, "gate": gate, "result": "n/a" if ok is None else ("pass" if ok else "FAIL"),
                     "reference": _v(ref), "candidate": _v(cand)})

    add("R1", "identifier equal", True if g("identifier_match") else None, g("identifier_match_schemes"))
    add("R1b/R2", "no identifier disagrees", not g("identifier_conflict"), g("identifier_conflict_schemes"))
    add("R3", "person vs organisation compatible", g("type_compatible", True), g("party_type_basis"),
        g("candidate_party_type"))
    if "jurisdiction_conflict" in f:
        add("R3b", "jurisdiction (foreign entity needs a foreign-body registration)",
            not g("jurisdiction_conflict"), g("ref_jurisdiction"),
            f"{g('candidate_entity_type') or ''} foreign_registration={g('candidate_foreign_registration')}")
    if not g("identifier_match"):
        add("R5a", "every reference token in the candidate", not g("ref_tokens_missing_in_candidate"),
            g("ref_tokens_missing_in_candidate"), g("compared_name"))
        add("R5b", "all distinctive tokens present", (g("distinctive_coverage") or 0) >= 1.0,
            g("distinctive_missing"), f"coverage {g('distinctive_coverage')}")
        add("R5c", "legal forms compatible", g("legal_form_compatible", True), g("ref_legal_form"),
            g("candidate_legal_form"))
        add("R5d", "no trust / fund vs company conflict", not g("entity_kind_conflict"))
        add("R5e", "no AUSTRALIA-named subsidiary for a formal foreign name", not g("geo_conflict"))
        add("R5f", "formal name matches a legal name, not a business name", not g("weak_alias"), "",
            g("compared_name_kind"))
        add("R5g", "formal name: no extra candidate tokens",
            not (g("ref_formal") and g("candidate_extra_tokens")), f"formal={g('ref_formal')}",
            g("candidate_extra_tokens"))
        add("R6", "normalised name equal and unique", (g("name_exact") and g("name_exact_unique")) or None,
            f"exact={g('name_exact')}", f"unique={g('name_exact_unique')}")
    add("adj", "state agrees (penalty if not)", g("state_match"), g("state_basis"), "")
    if "postcode_match" in f:
        add("adj", "postcode agrees", g("postcode_match"), g("ref_postcode"), g("candidate_postcode"))
    add("R9", "candidate not quarantined", not g("candidate_quarantined"))
    return pd.DataFrame(rows)


def show_gates(features: dict[str, Any]) -> None:
    t = gates_table(features)
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={"result": st.column_config.TextColumn("result", help="FAIL = this gate blocked it")})


def show_stored_evidence(ev: dict[str, Any]) -> None:
    st.markdown(f"**Explanation:** {ev.get('explanation')}")
    if ev.get("disagreement"):
        st.warning(f"Disagreement recorded (other evidence pointed elsewhere): {ev['disagreement']}")
    if ev.get("runner_up"):
        st.markdown(f"**Runner-up:** {ev['runner_up']}")
    st.markdown(f"Threshold {ev.get('threshold')}, path `{ev.get('path')}`, found by {_v(ev.get('found_by'))}, "
                f"scores {ev.get('scores')}")
    if ev.get("features"):
        st.markdown("**Gates** (from the stored feature vector)")
        show_gates(ev["features"])
    for path, q in (ev.get("query_text") or {}).items():
        st.caption(path)
        st.code(q, language="sql")


# --------------------------------------------------------------------------- page 1: resolve

def party_names(b: Backend, keys: list[str]) -> dict[str, tuple[str, str]]:
    if not keys:
        return {}
    d = b.q("SELECT canonical_key, name, party_type FROM party_canonical WHERE canonical_key IN (SELECT unnest(?))",
            [keys])
    return {r.canonical_key: (r.name, r.party_type) for r in d.itertuples()}


def page_resolve(b: Backend) -> None:
    st.header("Resolve")
    st.caption("Search a business name or identifier, then inspect the evidence behind the decision.")
    cols = st.columns(len(EXAMPLES), gap="small")
    for c, (label, ex) in zip(cols, EXAMPLES):
        if c.button(label, width="stretch", help=ex):
            st.session_state["resolve_text"] = ex
    text = st.text_input("Name, optionally with ABN / ACN / LEI / licence number", key="resolve_text")
    if not text.strip():
        st.info("Type a business name or press an example.")
        return
    t0 = time.perf_counter()
    ref = b.matcher.prepare(b.matcher.parser.parse(text))
    decision = b.matcher.match(ref)
    ms = (time.perf_counter() - t0) * 1000
    info = ref.as_dict()
    thr = b.policy.threshold(info.get("source") or "", info.get("party_type_hint"))

    if decision.resolved:
        st.markdown('<span class="status-badge status-resolved">● RESOLVED</span>', unsafe_allow_html=True)
        st.success(f"`{decision.canonical_key}` as **{decision.match_type}** "
                   f"(confidence {decision.confidence}). {decision.explanation}")
        if st.button(f"Open entity {decision.canonical_key}"):
            goto("Entity", key=decision.canonical_key)
    else:
        st.markdown(f'<span class="status-badge status-abstained">● ABSTAINED · {decision.reason}</span>', unsafe_allow_html=True)
        st.warning(decision.explanation)
    st.caption(f"{len(decision.ranked)} candidates, {ms:.0f} ms. Threshold for this reference {thr} "
               f"(type hint {info.get('party_type_hint')}), margin {b.policy.margin(info.get('source') or '')}.")
    with st.expander("How the text was parsed (the reference)"):
        st.json(jsonable(info))

    if not decision.ranked:
        st.write("No candidate from any generator: nothing in the graph shares an identifier, the normalised name, "
                 "the block token or a distinctive token.")
        return
    names = party_names(b, [r.canonical_key for r in decision.ranked])
    rows = []
    for i, r in enumerate(decision.ranked, 1):
        nm, pt = names.get(r.canonical_key, ("(not in this store)", None))
        rows.append({"rank": i, "name": nm, "party_type": pt, "canonical_key": r.canonical_key,
                     "match_type": r.match_type, "score": r.score, "path": r.path, "eligible": r.eligible,
                     "why_not": r.veto, "found_by": ", ".join(r.found_by), "entity": entity_url(r.canonical_key)})
    st.dataframe(df(rows), hide_index=True, width="stretch",
                 column_config={"entity": entity_link_col(), "score": st.column_config.NumberColumn(format="%.4f")})

    st.subheader("Evidence per candidate")
    for i, r in enumerate(decision.ranked[:15], 1):
        nm = names.get(r.canonical_key, ("?", None))[0]
        label = f"#{i} {nm} [{r.canonical_key}] {r.match_type} {r.score:.4f}" + ("" if r.eligible else f" (not eligible)")
        with st.expander(label, expanded=(i == 1)):
            ev = getattr(decision, "evidence", None)
            chosen = getattr(decision, "canonical_key", None) or getattr(decision, "best_candidate", None)
            if ev is not None and chosen == r.canonical_key:
                st.markdown(f"**Decision explanation:** {ev.explanation}")
                if ev.disagreement:
                    st.warning(f"Disagreement recorded (other evidence pointed elsewhere): {ev.disagreement}")
                if ev.runner_up:
                    st.markdown(f"**Runner-up:** {ev.runner_up}")
            st.markdown(f"**Why not eligible:** {r.veto}" if r.veto else "**Eligible** (no veto, passes the name gate or matched on an identifier).")
            st.markdown("**Gates**")
            show_gates(r.features)
            c1, c2 = st.columns([1, 1])
            c1.markdown("**Scores**")
            c1.json(jsonable(r.scores))
            c2.markdown("**Features**")
            c2.json(jsonable(r.features), expanded=False)
            st.markdown("**Query text that produced this candidate** (exact, literals inlined)")
            for path, q in r.query_text.items():
                st.caption(path)
                st.code(q, language="sql")
            if st.button("Open entity", key=f"open_{i}_{r.canonical_key}"):
                goto("Entity", key=r.canonical_key)
    if len(decision.ranked) > 15:
        st.caption(f"{len(decision.ranked) - 15} more candidates are in the table above (evidence panels capped at 15).")


# --------------------------------------------------------------------------- page 2: entity

def facts_table(items: list[Any]) -> pd.DataFrame:
    rows = []
    for f in items:
        d = asdict(f)
        detail = d.pop("detail", {}) or {}
        rows.append({**{k: d[k] for k in ("type", "active", "valid_from", "valid_to", "status", "other_name",
                                          "other", "attribution", "about_record", "source_graph", "fact")},
                     "detail": detail})
    return df(rows)


def page_entity(b: Backend) -> None:
    st.header("Entity")
    if "entity_key" not in st.session_state:  # widget state is dropped while another page is shown
        st.session_state["entity_key"] = st.session_state.get("entity_target", "urn:abn:48123123124")
    key = st.text_input("Canonical key (e.g. urn:abn:48123123124), ABN, ACN or LEI",
                        key="entity_key")
    key = key.strip()
    if not key:
        return
    st.session_state["entity_target"] = key
    if key.isdigit() and len(key) in (9, 11):
        col = "abn" if len(key) == 11 else "acn"
        hit = b.q(f"SELECT canonical_key FROM party_canonical WHERE {col} = ? LIMIT 1", [key])
        key = hit.canonical_key[0] if len(hit) else key
    t0 = time.perf_counter()
    party = b.q("SELECT * FROM party_canonical WHERE canonical_key = ?", [key])
    if party.empty:
        st.warning(f"`{key}` is not a canonical party in this store. Graph lookup only (LEI or record IRI):")
        node_view(b, key)
        return
    p = party.iloc[0]
    st.subheader(f"{p['name']}  ({p['party_type']})")
    quarantined = bool(p.get("quarantined"))
    qrows = b.q("SELECT invariant, detail, source, record_id, detected_at FROM quarantine WHERE canonical_key = ?", [key])
    if quarantined or not qrows.empty:
        st.error("QUARANTINED: the resolver will not link to this party. Reason(s):")
        st.dataframe(df(qrows), hide_index=True, width="stretch")
    else:
        st.caption("Not quarantined.")
    attrs = {k: p[k] for k in ("canonical_key", "abn", "acn", "lei", "entity_type", "entity_type_text", "status",
                               "abn_status", "asic_status", "state", "postcode", "valid_from", "valid_to", "source",
                               "record_id") if k in p.index}
    if b.is_bundle:
        why = b.q("SELECT why FROM demo_bundle_reason WHERE canonical_key = ?", [key])
        if len(why):
            attrs["in_demo_bundle_because"] = why.why[0]
    st.dataframe(df([jsonable(attrs)]), hide_index=True, width="stretch")

    iri = b.party_iri(key)
    view = cached_entity_view(b, iri, today()) if (b.fuseki_url or ("entity", iri) in b.precomputed) else None

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Identifiers** (store)")
        st.dataframe(df(b.q("SELECT scheme, value FROM identifier WHERE canonical_key = ? ORDER BY 1, 2", [key])),
                     hide_index=True, width="stretch")
        if view and view.identifiers:
            st.markdown("**Identifiers seen in the graph** (with the sources that carry them)")
            st.dataframe(df(view.identifiers), hide_index=True, width="stretch")
    with c2:
        st.markdown("**Aliases**")
        st.dataframe(df(b.q("SELECT alias, alias_type, source, record_id FROM alias WHERE canonical_key = ? "
                            "ORDER BY alias_type, alias", [key])), hide_index=True, width="stretch")

    st.markdown("**Source records behind it** (store: what the party was built from, its aliases' records, "
                "and every record a link attributes to it)")
    recs = b.q(f"""
        WITH r AS (
            SELECT source, record_id, 'built from' AS role FROM party_canonical WHERE canonical_key = $k
            UNION ALL SELECT 'asic_company', asic_record_id, 'built from (ASIC company)' FROM party_canonical
                      WHERE canonical_key = $k AND asic_record_id IS NOT NULL
            UNION ALL SELECT DISTINCT source, record_id, 'alias source' FROM alias WHERE canonical_key = $k AND record_id IS NOT NULL
            UNION ALL SELECT source, record_id, 'linked: ' || match_type FROM link
                      WHERE canonical_key = $k AND matcher_version = $mv)
        SELECT r.role, r.source, r.record_id, s.name_raw, s.first_seen_snapshot, s.last_seen_snapshot,
               'urn:graph:source:' || r.source || ':' || CAST(s.last_seen_snapshot AS VARCHAR) AS source_graph
        FROM r LEFT JOIN source_record s USING (source, record_id)
        QUALIFY row_number() OVER (PARTITION BY r.role, r.source, r.record_id ORDER BY s.last_seen_snapshot DESC NULLS LAST) = 1
        ORDER BY r.role, r.source, r.record_id""", {"k": key, "mv": b.matcher_version})
    st.dataframe(df(recs), hide_index=True, width="stretch")

    st.markdown(f"**Inbound links** (records the matcher `{b.matcher_version}` linked here, with match type and why)")
    inbound = b.q("""SELECT l.source, l.record_id, s.name_raw, l.match_type, l.confidence,
                            json_extract_string(l.evidence, '$.explanation') AS explanation,
                            json_extract_string(l.evidence, '$.disagreement') AS disagreement
                     FROM link l LEFT JOIN source_record s USING (source, record_id)
                     WHERE l.canonical_key = ? AND l.matcher_version = ?
                     QUALIFY row_number() OVER (PARTITION BY l.source, l.record_id ORDER BY s.last_seen_snapshot DESC) = 1
                     ORDER BY l.source, l.record_id""",
                  [key, b.matcher_version])
    st.dataframe(df(inbound), hide_index=True, width="stretch")
    near = b.q("""SELECT source, record_id, reason, best_score, json_extract_string(evidence, '$.explanation') AS explanation
                  FROM abstention WHERE best_candidate = ? AND matcher_version = ?""", [key, b.matcher_version])
    if len(near):
        st.markdown("**Abstentions that named this party as best candidate** (the resolver refused to link)")
        st.dataframe(df(near), hide_index=True, width="stretch")

    if view is None:
        view = entity_graph_view(b, iri)
    if isinstance(view, str):  # deferred (rdflib host, not requested yet)
        view = None
    elif view is None:
        st.warning("The party is not in the graph's canonical graph.")
    if view is not None:
        render_graph_facts(view)
    licence_history(b, p, inbound)
    st.caption(f"Entity page assembled in {(time.perf_counter() - t0) * 1000:.0f} ms.")


def render_graph_facts(view: Any) -> None:
    st.markdown(f"**Graph view** (`entity_view`, links graph `{view.links_graph}`, {view.elapsed_ms:.0f} ms). "
                f"Truncation: {view.truncation_note()}")
    for cat, title in (("licences", "Licences"), ("bans", "Bans"), ("notices", "ACCC / regulator notices"),
                       ("parents", "Parents (direct)"), ("ultimate_parents", "Ultimate parent (GLEIF's own edge)"),
                       ("subsidiaries", "Subsidiaries"), ("trusteeships", "Trusteeships"),
                       ("affiliations", "Affiliations"), ("products", "Products"), ("other", "Other")):
        items = view.facts_by_type.get(cat, [])
        more = view.truncated_counts.get(cat, 0)
        if not items and cat not in ("licences", "bans", "notices", "parents", "subsidiaries"):
            continue
        st.markdown(f"**{title}**: {view.totals.get(cat, 0)}" + (f" ({more} more not shown)" if more else ""))
        if items:
            st.dataframe(facts_table(items), hide_index=True, width="stretch")


def licence_history(b: Backend, p: Any, inbound: pd.DataFrame) -> None:
    abn = p["abn"] if isinstance(p["abn"], str) else None
    acn = p["acn"] if isinstance(p["acn"], str) else None
    lic_nos = inbound[inbound.source.isin(["asic_afsl", "asic_credit"])].record_id.tolist() if len(inbound) else []
    ev = b.q("""SELECT licence_kind, licence_no, event_type, observed_after AS gone_after_exclusive,
                       event_date AS gone_by, holder_name_before, holder_name_after, match_basis
                FROM licence_event
                WHERE ltrim(licence_no, '0') IN (SELECT ltrim(unnest(?), '0'))
                   OR holder_abn_before = ? OR holder_acn_before = ? OR holder_abn_after = ? OR holder_acn_after = ?
                ORDER BY event_date DESC""", [lic_nos or [""], abn, acn, abn, acn])
    st.markdown("**Licence history** (from diffs of archived register snapshots; a CANCELLED_OR_LAPSED licence "
                "ended after `gone_after_exclusive` and on or before `gone_by`, the true date is unknown)")
    st.dataframe(df(ev), hide_index=True, width="stretch")


def node_view(b: Backend, key: str) -> None:
    view = cached_entity_view(b, key, today())
    if view is None:
        st.info("Nothing in the graph either.")
        return
    st.write(f"Graph node `{view.party.key}` ({view.party.kind}, {view.party.name}), attribution {view.party.attribution}")
    st.dataframe(df(view.identifiers), hide_index=True)
    st.dataframe(df(view.source_records), hide_index=True)
    for cat, items in view.facts_by_type.items():
        st.markdown(f"**{cat}**: {view.totals.get(cat)}")
        st.dataframe(facts_table(items), hide_index=True, width="stretch")


# --------------------------------------------------------------------------- page 3: traversals

# Graph calls are cached per argument: with Fuseki they take well under a second, with the
# in-process rdflib endpoint (hosted without Java) each SPARQL query costs seconds.
# Without Fuseki, results precomputed at bundle build time (same graphs, served by Fuseki) are
# used for the example inputs; anything else is computed live on rdflib.
def precomputed(b: Backend, *key: Any) -> Any:
    hit = b.precomputed.get(key)
    if hit is not None:
        st.caption(f"Precomputed when the bundle was built ({b.precomputed.get(('built_at',), '?')}) against "
                   "the same graphs served by Fuseki; this host has no Fuseki and rdflib needs minutes for it.")
    return hit


@st.cache_data(show_spinner="Walking every ownership chain...", ttl=3600)
def cached_group_exposure(_b: Backend, as_of: date) -> dict[str, Any]:
    return precomputed(_b, "group_exposure") or _b.traversal.group_exposure(as_of=as_of)


@st.cache_data(show_spinner="Walking the ownership chain...", ttl=3600)
def cached_chain(_b: Backend, start: str, max_depth: int) -> Any:
    return precomputed(_b, "chain", start, max_depth) or _b.traversal.ultimate_parent(start, max_depth=max_depth)


@st.cache_data(show_spinner="Querying the graph for this entity...", ttl=3600)
def cached_entity_view(_b: Backend, iri: str, as_of: date, same_identifier: bool = True) -> Any:
    return precomputed(_b, "entity", iri) or _b.traversal.entity_view(iri, as_of=as_of,
                                                                       same_identifier=same_identifier)


def entity_graph_view(b: Backend, iri: str) -> Any:
    """With Fuseki: always live. Without (rdflib): precomputed examples at once, anything else
    only on request, without the same-identifier widening (rdflib needs minutes for that)."""
    if b.fuseki_url or ("entity", iri) in b.precomputed:
        return cached_entity_view(b, iri, today())
    st.info("This host has no Fuseki: the graph half of this page (licences, bans, notices, parents, "
            "subsidiaries) runs on in-process rdflib and takes about a minute. The store half above is complete.")
    if st.button("Load the graph view (about a minute)", key=f"ev_{iri}") or st.session_state.get(f"ev_done_{iri}"):
        st.session_state[f"ev_done_{iri}"] = True
        return cached_entity_view(b, iri, today(), same_identifier=False)
    return "deferred"


@st.cache_data(show_spinner="Expanding the neighbourhood...", ttl=3600)
def cached_hops(_b: Backend, key: str, hops: int) -> Any:
    return precomputed(_b, "hops", key, hops) or _b.traversal.within_hops(key, hops)


@st.cache_data(show_spinner="Running the projection...", ttl=3600)
def cached_projection(_b: Backend, spec_json: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = _b.projection.project(json.loads(spec_json))
    return out, jsonable(_b.projection.last_run)


def page_traversals(b: Backend) -> None:
    st.header("Traversals")
    st.subheader("Ultimate parent")
    choice = st.selectbox("Example", list(CHAIN_EXAMPLES))
    start = st.text_input("Start (LEI, ABN, ACN, party IRI)", value=CHAIN_EXAMPLES[choice])
    max_depth = st.slider("max_depth", 1, 12, 10)
    chain = cached_chain(b, start.strip(), max_depth)
    st.markdown(f"**Status `{chain.status}`**, depth {chain.depth}, cycle detected: {chain.cycle_detected}, "
                f"truncated: {chain.truncated}, ambiguous parents: {len(chain.ambiguous_parents)}. "
                f"GLEIF's own ultimate-parent edge: {', '.join(n.short() for n in chain.gleif_ultimate) or 'none'} "
                f"(check: {chain.gleif_check}). {chain.queries} SPARQL queries, {chain.elapsed_ms:.0f} ms.")
    st.code(chain.summary())
    nodes = [{"step": i, "name": n.name, "node": n.key, "kind": n.kind, "lei": n.lei, "attribution": n.attribution,
              "entity": entity_url(b.key_for_iri(n.key)) if n.kind == "party" else None}
             for i, n in enumerate(chain.nodes)]
    st.dataframe(df(nodes), hide_index=True, width="stretch", column_config={"entity": entity_link_col()})
    edges = [{"child": e.child, "parent": e.parent, "kind": (e.kind or "").split("#")[-1], "percentage": e.percentage,
              "valid_from": e.valid_from, "valid_to": e.valid_to, "status": e.status, "rule": e.rule,
              "level": e.level, "source_graph": e.source_graph, "fact": e.fact} for e in chain.edges]
    st.markdown("**Edges taken** (each with the rule that chose it: single, majority or plurality)")
    st.dataframe(df(edges), hide_index=True, width="stretch")
    if chain.status == "CYCLE":
        st.error(f"Cycle: {' -> '.join(chain.cycle_path)}; no ultimate parent is claimed.")
    if chain.gleif_check and chain.gleif_check.startswith("disagree"):
        st.caption("The walked top differs from GLEIF's own IS_ULTIMATELY_CONSOLIDATED_BY edge: "
                   "`disagree_on_chain` means GLEIF's ultimate is on the path but the walk went higher, "
                   "`disagree_off_chain` that the slice lacks the edges up to it.")
    st.caption("Cycle behaviour: a visited set stops the walk with status CYCLE and the loop path; no top is "
               "picked. Several parents without a majority stop with AMBIGUOUS. The group scan below reports how "
               "many chains in this data end that way (they are left out of every group).")

    st.subheader("Within N hops")
    k = st.text_input("Start node for the neighbourhood", value="urn:abn:94122169279")
    hops = st.slider("hops", 1, 3, 2)
    if st.button("Run within_hops"):
        hood = cached_hops(b, k.strip(), hops)
        st.caption(f"{len(hood.neighbours)} neighbours, {hood.queries} queries, {hood.elapsed_ms:.0f} ms, "
                   f"truncated: {hood.truncated_counts or 'nothing'}")
        st.dataframe(df([{"distance": n.distance, "name": n.node.name, "node": n.node.key, "kind": n.node.kind,
                          "path": " | ".join(f"{h['relation']}:{h.get('kind') or ''}" for h in n.via)}
                         for n in hood.neighbours]), hide_index=True, width="stretch")

    st.subheader("Graph-only question: who controls the licensees, and who shares a group with a flag")
    st.caption("Walks every DIRECT consolidation chain (bounded, cycle-safe), groups members by their top, joins "
               "licences, bans, ACCC notices, suspended licences and recent cancellations on other members, and the "
               "top's country. Three registers that share no key except through resolved identity.")
    if st.button("Run group_exposure") or st.session_state.get("ge_done"):
        st.session_state["ge_done"] = True
        res = cached_group_exposure(b, today())
        st.markdown(f"{res['members_scanned']:,} group members, {len(res['groups']):,} groups, "
                    f"{res['queries']} queries, {res['elapsed_ms']:.0f} ms (first run; cached afterwards). "
                    f"Chains left out as CYCLE / TRUNCATED / AMBIGUOUS: {res['unresolved_tops']}.")
        st.markdown(f"**Foreign-controlled licensees: {len(res['foreign_controlled'])}**")
        st.dataframe(df(res["foreign_controlled"]), hide_index=True, width="stretch")
        st.markdown(f"**Licensed entities in the same group as a flagged entity: {len(res['exposures'])}**")
        if res["exposures"]:
            st.dataframe(df(res["exposures"]), hide_index=True, width="stretch")
        else:
            st.write("None in this data: no flagged entity (ban, ACCC notice, suspended or recently cancelled "
                     "licence) is a GLEIF group member. The synthetic test covers the positive case.")
        st.markdown("**Licence concentration by group** (top 25)")
        st.dataframe(df(res["groups"][:25]), hide_index=True, width="stretch")


# --------------------------------------------------------------------------- page 4: abstentions

def page_abstentions(b: Backend) -> None:
    st.header("Abstentions")
    st.caption("Records the resolver believed were businesses and refused to link, with the best candidate, its "
               "score and the reason. These are the half of the system that matters most.")
    counts = b.q("SELECT source, reason, count(*) AS n FROM abstention WHERE matcher_version = ? GROUP BY ALL "
                 "ORDER BY source, reason", [b.matcher_version])
    if b.is_bundle:
        full = b.q("SELECT source, label AS reason, n AS n_full_store FROM demo_full_counts WHERE kind = 'abstention'")
        counts = counts.merge(full, on=["source", "reason"], how="outer").fillna(0)
        st.caption("`n` is what this bundle holds; `n_full_store` the full eval snapshot. Tier 2/3 abstentions are "
                   "all present; GLEIF ones only for the ownership slice.")
    st.dataframe(df(counts), hide_index=True)
    with st.expander("What each reason means"):
        st.dataframe(pd.DataFrame([{"reason": k, "meaning": v} for k, v in REASONS.items()]), hide_index=True)
    sources = sorted(counts.source.unique().tolist())
    c1, c2 = st.columns(2)
    src = c1.selectbox("Source", sources, index=sources.index("accc_notice") if "accc_notice" in sources else 0)
    reasons = sorted(counts[counts.source == src].reason.unique().tolist())
    rs = c2.multiselect("Reason", reasons, default=reasons)
    rows = b.q("""
        SELECT a.record_id, s.name_raw AS record_name, a.reason, a.best_candidate, p.name AS best_candidate_name,
               a.best_score, json_extract_string(a.evidence, '$.explanation') AS explanation
        FROM abstention a
        LEFT JOIN source_record s USING (source, record_id)
        LEFT JOIN party_canonical p ON p.canonical_key = a.best_candidate
        WHERE a.matcher_version = ? AND a.source = ? AND a.reason IN (SELECT unnest(?))
        QUALIFY row_number() OVER (PARTITION BY a.record_id ORDER BY s.last_seen_snapshot DESC) = 1
        ORDER BY a.best_score DESC NULLS LAST, a.record_id LIMIT 2000""", [b.matcher_version, src, rs or [""]])
    rows["entity"] = rows.best_candidate.map(entity_url)
    st.dataframe(df(rows), hide_index=True, width="stretch", column_config={"entity": entity_link_col()})
    st.caption(f"{len(rows)} rows (capped at 2,000).")
    sel = st.selectbox("Show the full stored evidence for record", [""] + rows.record_id.tolist())
    if sel:
        ev = b.q("SELECT evidence FROM abstention WHERE matcher_version = ? AND source = ? AND record_id = ?",
                 [b.matcher_version, src, sel])
        blob = json.loads(ev.evidence[0]) if len(ev) and ev.evidence[0] else {}
        show_stored_evidence(blob)
        with st.expander("Raw stored evidence JSON"):
            st.json(blob)
        st.caption("To see every candidate re-scored live, paste the record name on the Resolve page.")


# --------------------------------------------------------------------------- page 5: projection

def page_projection(b: Backend) -> None:
    from bizgraph.services.projection import NAMED_SPECS, CriteriaSpec

    st.header("Projection (selection criteria to dataset)")
    name = st.selectbox("Named spec", list(NAMED_SPECS))
    spec_d = NAMED_SPECS[name]
    st.write(spec_d.get("description", ""))
    st.json(spec_d, expanded=False)
    st.code(b.projection.plan(CriteriaSpec.from_dict(spec_d)).explain())
    t0 = time.perf_counter()
    out, run = cached_projection(b, json.dumps(spec_d))
    st.markdown(f"**Result: {len(out)} rows** ({(time.perf_counter() - t0) * 1000:.0f} ms, links graph "
                f"`{run.get('links_graph')}`, as_of {run.get('as_of')})")
    st.dataframe(df(out), hide_index=True, width="stretch")

    st.subheader("Each half on its own")
    halves = {}
    for child in spec_d["match"].get("all", spec_d["match"].get("any", [])):
        if "id" not in child:
            continue
        sub = {**spec_d, "name": f"{name}:{child['id']}", "match": {"all": [child]}}
        part, sub_run = cached_projection(b, json.dumps(sub))
        halves[child["id"]] = part
        st.markdown(f"**{child['id']}** ({child.get('fact')}): {len(part)} parties")
        st.dataframe(df(part), hide_index=True, width="stretch")
        with st.expander(f"Query text for {child['id']}"):
            for q in sub_run.get("queries", []):
                st.code(q["text"], language="sparql" if q["engine"] == "sparql" else "sql")
    if len(halves) == 2 and len(out) == 0:
        a, c = (set(v.party.dropna()) if "party" in v else set() for v in halves.values())
        st.info(f"0 rows is the honest answer: the two halves have {len(a)} and {len(c)} parties and "
                f"{len(a & c)} in common. Infringement notices in the extract go to consumer-facing businesses, "
                f"AFSL cancellations in the last 3 months to financial-services holders; nothing in this data is both.")


# --------------------------------------------------------------------------- main

def main() -> None:
    t0 = time.perf_counter()
    b = backend()
    inject_styles()
    header(b)
    ss = st.session_state
    if "page_radio" not in ss:  # first run of a session: honour ?page=...&key=... links
        qp = st.query_params.get("page", "Resolve")
        ss["page_radio"] = qp if qp in PAGES else "Resolve"
        ss["entity_key"] = ss["entity_target"] = st.query_params.get("key", "urn:abn:48123123124")
    if "nav_to" in ss:
        ss["page_radio"] = ss.pop("nav_to")
    # Main navigation: tabs (a segmented control styled as tabs, so only the active page runs).
    page = st.segmented_control("Navigate", PAGES, key="page_radio", label_visibility="collapsed")
    if page is None:  # clicking the active tab deselects it; stay on the last page
        page = ss.get("last_page", "Resolve")
    ss["last_page"] = page
    # Sidebar: table of contents only.
    st.sidebar.markdown('<div class="toc-title">Contents</div>', unsafe_allow_html=True)
    for p in PAGES:
        if p == page:
            st.sidebar.markdown(f'<div class="toc-current">{p}</div>', unsafe_allow_html=True)
        else:
            st.sidebar.button(p, key=f"toc_{p}", type="tertiary", on_click=lambda p=p: ss.update(nav_to=p))
    {"Resolve": page_resolve, "Entity": page_entity, "Traversals": page_traversals,
     "Abstentions": page_abstentions, "Projection": page_projection}[page](b)


main()
