"""`Matcher` facade: one entry point for `resolve` (single reference) and the batch run.

Both use the same generators, features, scorers, arbiter and `ThresholdPolicy`, so a
resolve answer and a batch link can never disagree for the same input.

Batch (`match_batch`) is set-based where volume matters: identifier joins, name
equality and both SQL blockers run as one statement each over a registered table
of all references; feature extraction is per pair in Python (rapidfuzz). Every
candidate is persisted to `candidate` with its features, scores, path and query
text, then the decisions go to `link` / `abstention` under the matcher version.

`redecide(run_id, policy)` re-applies a different policy to the stored candidates of
a run without regenerating or rescoring them, and writes a new matcher version.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from bizgraph.normalise.names import NameNormaliser
from bizgraph.resolution.candidates import (
    JOINABLE_SCHEMES,
    BlockingGenerator,
    EmbeddingBlocker,
    ExactIdentifierGenerator,
    FtsBlocker,
    GeneratedCandidate,
    NameIndex,
    TokenStateBlocker,
)
from bizgraph.resolution.decision import (
    PATH_EXACT_ID,
    PATH_NAME_EXACT,
    Abstention,
    Decision,
    Link,
    ScorerConfig,
    StoredCandidate,
    ThresholdPolicy,
    arbitrate,
    score_all,
)
from bizgraph.resolution.features import Embedder, FeatureExtractor, FeatureVector, PartyView
from bizgraph.domain.models import PartyType
from bizgraph.resolution.reference import (
    COMMON_GIVEN_NAMES,
    COMMON_SURNAMES,
    Reference,
    ReferenceParser,
    person_shaped,
)
from bizgraph.store.duckdb_store import DuckDBStore

_PACKAGE_DIR = Path(__file__).resolve().parent


def code_hash() -> str:
    """SHA-256 over the resolution package source (sorted file names + contents)."""
    h = hashlib.sha256()
    for p in sorted(_PACKAGE_DIR.glob("*.py")):
        h.update(p.name.encode() + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


@dataclass(frozen=True)
class MatcherVersion:
    """What produced a decision: code, policy, feature config, and (for a redecide) the
    candidate run it re-decided. Immutable once saved (`matcher_versions.save` refuses
    different content under the same version string)."""

    version: str
    code_hash: str
    policy: ThresholdPolicy
    config: dict[str, Any] = field(default_factory=dict)
    candidates_run_id: str | None = None

    @classmethod
    def create(
        cls,
        policy: ThresholdPolicy,
        config: dict[str, Any] | None = None,
        candidates_run_id: str | None = None,
        prefix: str = "m",
    ) -> MatcherVersion:
        ch = code_hash()
        config = dict(config or {})
        body = json.dumps(
            {"policy": policy.to_dict(), "config": config, "candidates_run_id": candidates_run_id}, sort_keys=True
        )
        digest = hashlib.sha256(body.encode()).hexdigest()
        tag = "r" if candidates_run_id else ""
        return cls(f"{prefix}{tag}-{ch[:8]}-{digest[:8]}", ch, policy, config, candidates_run_id)

    def policy_json(self) -> dict[str, Any]:
        return {"policy": self.policy.to_dict(), "config": self.config, "candidates_run_id": self.candidates_run_id}

    def save(self, store: DuckDBStore) -> None:
        store.matcher_versions.save(self.version, self.code_hash, self.policy_json())


@dataclass
class RunSummary:
    run_id: str
    matcher_version: str
    source: str
    records: int = 0
    candidates: int = 0
    links: int = 0
    abstentions: int = 0
    by_match_type: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, int] = field(default_factory=dict)
    timings_s: dict[str, float] = field(default_factory=dict)
    diff: dict[str, int] | None = None

    @property
    def records_per_s(self) -> float:
        total = self.timings_s.get("total", 0.0)
        return round(self.records / total, 1) if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["records_per_s"] = self.records_per_s
        return d


def _link_id(version: str, source: str, record_id: str) -> str:
    return hashlib.sha256(f"{version}|{source}|{record_id}".encode()).hexdigest()[:24]


def _jdump(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


class Matcher:
    BLOCK_CHUNK = 1000  # name-only references per set-based blocking statement
    SCORE_CHUNK = 5000  # references generated, scored and persisted together in match_batch
    ALT = "\x1falt"  # key suffix of a reference's trading-as alternative in the batch tables

    def __init__(
        self,
        store: DuckDBStore,
        policy: ThresholdPolicy | None = None,
        embedder: Embedder | None | str = None,
        k: int = 20,
        use_embedding_blocker: bool = False,
        scorer_config: ScorerConfig | None = None,
        normaliser: NameNormaliser | None = None,
        version_label: str = "m",
    ) -> None:
        """embedder: an `Embedder`, None (no semantic path), or "auto" (load if installed)."""
        self.store = store
        self.con = store.con
        self.policy = policy or ThresholdPolicy()
        self.names = normaliser or NameNormaliser()
        self.embedder = Embedder.load() if embedder == "auto" else embedder
        self.index_stats = NameIndex(self.con).ensure()
        # Embeddings are filled in afterwards, in one batch, and only where the semantic path
        # can apply (see _embed), so the extractor itself runs without the model.
        self.extractor = FeatureExtractor(self.names, None)
        self.scorer_config = scorer_config or ScorerConfig()
        self.scorers = self.scorer_config.scorers()
        self.exact = ExactIdentifierGenerator()
        blockers = [TokenStateBlocker(k), FtsBlocker(k)]
        if use_embedding_blocker and self.embedder is not None:
            blockers.append(EmbeddingBlocker(self.embedder, self.con, k))
        self.blocking = BlockingGenerator(blockers)
        self.parser = ReferenceParser(self.names)
        self.given_names, self.surnames = self._person_vocab()
        config = {
            "blockers": self.blocking.describe(),
            "scorers": [s.name for s in self.scorers],
            "scorer_config": self.scorer_config.to_dict(),
            "embedding_model": self.embedder.model_name if self.embedder else None,
        }
        self.version = MatcherVersion.create(self.policy, config, prefix=version_label)

    # ------------------------------------------------------------------ references

    def _person_vocab(self) -> tuple[frozenset[str], frozenset[str]]:
        """Static seed lists plus the frequent first / last tokens of person parties."""
        rows = self.con.execute("SELECT role, token FROM res_person_vocab").fetchall()
        given = set(COMMON_GIVEN_NAMES) | {t for r, t in rows if r == "given"}
        surnames = set(COMMON_SURNAMES) | {t for r, t in rows if r == "surname"}
        return frozenset(given), frozenset(surnames)

    def prepare(self, ref: Reference) -> Reference:
        """Rule R4 input: an UNKNOWN reference shaped like an individual's name is a PERSON
        for the name paths ('John Smith' never links to JOHN SMITH PTY LTD on name alone)."""
        if ref.party_type_hint is PartyType.UNKNOWN and person_shaped(ref, self.given_names, self.surnames):
            return dataclasses.replace(ref, party_type_hint=PartyType.PERSON,
                                       notes=(*ref.notes, "person_shaped_name"))
        return ref

    # ------------------------------------------------------------------ party views

    def _party_views(self, keys: set[str]) -> dict[str, PartyView]:
        if not keys:
            return {}
        con = self.con
        con.register("_res_keys", pa.table({"canonical_key": pa.array(sorted(keys), pa.string())}))
        try:
            parties = con.execute(
                """SELECT p.canonical_key, p.party_type, p.name, p.name_norm, upper(p.state),
                          coalesce(p.quarantined, false), p.postcode, coalesce(p.entity_type, p.asic_type),
                          f.canonical_key IS NOT NULL
                   FROM party_canonical p JOIN _res_keys k USING (canonical_key)
                   LEFT JOIN res_foreign_reg f USING (canonical_key)"""
            ).fetchall()
            ids = con.execute(
                """SELECT i.canonical_key, i.scheme, i.value FROM res_party_identifier i
                   JOIN _res_keys k USING (canonical_key)"""
            ).fetchall()
            names = con.execute(
                """SELECT n.canonical_key, n.name_norm, n.kind, n.name_raw FROM res_name_index n
                   JOIN _res_keys k USING (canonical_key) ORDER BY n.kind <> 'name', n.name_norm"""
            ).fetchall()
            quarantined = {
                r[0]
                for r in con.execute(
                    """SELECT DISTINCT q.canonical_key FROM quarantine q JOIN _res_keys k USING (canonical_key)"""
                ).fetchall()
            }
        finally:
            con.unregister("_res_keys")
        id_map: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for key, scheme, value in ids:
            id_map[key][scheme].add(value)
        name_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
        raw_map: dict[str, dict[str, str]] = defaultdict(dict)
        for key, norm, kind, raw in names:
            name_map[key].append((norm, kind))
            raw_map[key].setdefault(norm, raw)
        out = {}
        for key, ptype, name, norm, state, q, postcode, etype, foreign in parties:
            out[key] = PartyView(
                canonical_key=key,
                party_type=ptype,
                name=name,
                name_norm=norm,
                state=state,
                quarantined=bool(q) or key in quarantined,
                identifiers={s: frozenset(v) for s, v in id_map[key].items()},
                names=tuple(name_map[key]),
                name_raw_by_norm=raw_map[key],
                postcode=postcode,
                entity_type=etype,
                foreign_registration=bool(foreign),
            )
        return out

    def _unique_norms(self, norms: set[str]) -> set[str]:
        if not norms:
            return set()
        self.con.register("_res_norms", pa.table({"name_norm": pa.array(sorted(norms), pa.string())}))
        try:
            rows = self.con.execute(
                """SELECT DISTINCT i.name_norm FROM res_name_index i JOIN _res_norms n USING (name_norm)
                   WHERE i.n_keys = 1"""
            ).fetchall()
        finally:
            self.con.unregister("_res_norms")
        return {r[0] for r in rows}

    # ------------------------------------------------------------------ scoring

    def _score(
        self,
        ref: Reference,
        generated: list[GeneratedCandidate],
        parties: dict[str, PartyView],
        unique_norms: set[str],
        alt: Reference | None = None,
    ) -> list[StoredCandidate]:
        by_key: dict[str, StoredCandidate] = {}
        for g in generated:
            party = parties.get(g.canonical_key)
            if party is None:
                continue
            c = by_key.get(g.canonical_key)
            if c is None:
                fv = self.extractor.extract(ref, party, unique_norms)
                scores = score_all(fv, self.scorers)
                if alt is not None:  # trading-as name: keep whichever name explains the party better
                    fv2 = self.extractor.extract(alt, party, unique_norms)
                    sc2 = score_all(fv2, self.scorers)
                    k1 = (len(fv.ref_tokens_missing_in_candidate), -(scores["fuzzy"] or 0.0))
                    k2 = (len(fv2.ref_tokens_missing_in_candidate), -(sc2["fuzzy"] or 0.0))
                    if k2 < k1:
                        fv, scores = fv2, sc2
                c = StoredCandidate(g.canonical_key, [], {}, fv, scores)
                by_key[g.canonical_key] = c
            if g.path not in c.paths:
                c.paths.append(g.path)
                c.query_text[g.path] = g.query_text
        return list(by_key.values())

    def _embed(self, pairs: list[tuple[Reference, StoredCandidate]]) -> None:
        """Embedding cosine for candidates that pass the two-way distinctive token gate (the
        only ones the semantic path may label, rule R7); everything else keeps None. One
        batched encode call for all the texts involved."""
        if self.embedder is None:
            return
        # A reference with an identifier match is decided by rule R1; no embedding needed.
        decided = {id(r) for r, c in pairs if c.features.identifier_match}
        todo = [(r, c) for r, c in pairs
                if id(r) not in decided and r.name_norm and c.features.compared_name
                and c.features.distinctive_coverage >= 1.0 and c.features.distinctive_coverage_rev >= 1.0]
        if not todo:
            return
        texts = sorted({t for r, c in todo for t in (r.name_norm, c.features.compared_name)})
        vecs = dict(zip(texts, self.embedder.encode(texts)))
        for r, c in todo:
            c.features.embedding_cosine = round(float((vecs[r.name_norm] * vecs[c.features.compared_name]).sum()), 4)
            c.scores = score_all(c.features, self.scorers)

    @staticmethod
    def ref_info(ref: Reference) -> dict[str, Any]:
        return ref.as_dict()

    # ------------------------------------------------------------------ single reference

    def candidates(self, ref: Reference) -> list[StoredCandidate]:
        alt = ref.alternative(self.names)
        names = [ref] + ([alt] if alt else [])
        gen = self.exact.generate_ids(ref, self.con)
        for r in names:
            gen += self.exact.generate_name(r, self.con)
        if not any(g.path == PATH_EXACT_ID for g in gen):
            for r in names:
                gen += self.blocking.generate(r, self.con)
        parties = self._party_views({g.canonical_key for g in gen})
        uniq = self._unique_norms({r.name_norm for r in names if r.name_norm})
        stored = self._score(ref, gen, parties, uniq, alt)
        self._embed([(ref, c) for c in stored])
        return stored

    def match(self, ref: Reference) -> Decision:
        """Generate, score and decide one reference (no writes)."""
        ref = self.prepare(ref)
        return arbitrate(self.ref_info(ref), self.candidates(ref), self.policy)

    def resolve(self, text: str) -> Decision:
        """Free text -> Decision (ranked candidates with match_type, score, evidence, query)."""
        return self.match(self.parser.parse(text))

    # ------------------------------------------------------------------ batch

    def _expand(self, refs: list[Reference]) -> list[tuple[str, Reference]]:
        """(key, reference) rows: every reference plus its trading-as alternative (key + ALT)."""
        out = []
        for r in refs:
            out.append((r.record_id, r))
            alt = r.alternative(self.names)
            if alt is not None:
                out.append((r.record_id + self.ALT, alt))
        return out

    def _register_refs(self, rows: list[tuple[str, Reference]]) -> None:
        con = self.con
        con.register("_res_refs", pa.table({
            "record_id": pa.array([k for k, _ in rows], pa.string()),
            "name_norm": pa.array([r.name_norm for _, r in rows], pa.string()),
            "block_token": pa.array([r.block_token for _, r in rows], pa.string()),
            "state": pa.array([r.state for _, r in rows], pa.string()),
        }))
        rid, tok = [], []
        for k, r in rows:
            for t in sorted(r.distinctive):
                rid.append(k)
                tok.append(t)
        con.register("_res_ref_tokens", pa.table({"record_id": pa.array(rid, pa.string()),
                                                  "token": pa.array(tok, pa.string())}))
        rid, sch, val = [], [], []
        for k, r in rows:
            if k.endswith(self.ALT):
                continue
            for i in r.identifiers:
                if i.scheme.value in JOINABLE_SCHEMES:
                    rid.append(k)
                    sch.append(i.scheme.value)
                    val.append(i.value)
        con.register("_res_ref_ids", pa.table({"record_id": pa.array(rid, pa.string()),
                                               "scheme": pa.array(sch, pa.string()),
                                               "value": pa.array(val, pa.string())}))

    def _unregister_refs(self) -> None:
        for t in ("_res_refs", "_res_ref_tokens", "_res_ref_ids"):
            try:
                self.con.unregister(t)
            except Exception:
                pass

    def _batch_generate(self, refs: list[Reference]) -> tuple[dict[str, list[GeneratedCandidate]], dict[str, float]]:
        """Candidates per record_id for a chunk of references (set-based SQL)."""
        con = self.con
        rows = self._expand(refs)
        by_key = dict(rows)
        base = {k: k[: -len(self.ALT)] if k.endswith(self.ALT) else k for k, _ in rows}
        gen: dict[str, list[GeneratedCandidate]] = defaultdict(list)
        t: dict[str, float] = {}
        self._register_refs(rows)
        try:
            t0 = time.perf_counter()
            for rid, key, scheme, value in con.execute(
                """SELECT r.record_id, i.canonical_key, r.scheme, r.value FROM _res_ref_ids r
                   JOIN res_party_identifier i ON i.scheme = r.scheme AND i.value = r.value"""
            ).fetchall():
                gen[base[rid]].append(GeneratedCandidate(key, PATH_EXACT_ID, self.exact.id_sql(scheme, value)))
            t["exact_identifier"] = time.perf_counter() - t0
            t0 = time.perf_counter()
            for rid, key in con.execute(
                """SELECT DISTINCT r.record_id, i.canonical_key FROM _res_refs r
                   JOIN res_name_index i ON i.name_norm = r.name_norm"""
            ).fetchall():
                gen[base[rid]].append(
                    GeneratedCandidate(key, PATH_NAME_EXACT, self.exact.name_sql(by_key[rid].name_norm)))
            t["exact_name"] = time.perf_counter() - t0
        finally:
            self._unregister_refs()
        # Blocking only for references the identifier join did not resolve to a party, in
        # chunks so a common block token cannot blow up one giant join.
        name_only = [(k, r) for k, r in rows
                     if not any(g.path == PATH_EXACT_ID for g in gen.get(base[k], []))]
        for blocker in self.blocking.blockers:
            t[blocker.path_name] = 0.0
        for start in range(0, len(name_only), self.BLOCK_CHUNK):
            chunk = name_only[start:start + self.BLOCK_CHUNK]
            self._register_refs(chunk)
            try:
                for blocker in self.blocking.blockers:
                    t0 = time.perf_counter()
                    bsql = blocker.batch_sql()
                    if bsql is None:  # not SQL-backed (embedding): per reference
                        for k, r in chunk:
                            gen[base[k]].extend(blocker.block(r, con))
                    else:
                        for rid, key, _ in con.execute(bsql).fetchall():
                            sql = blocker.sql(by_key[rid])
                            if sql:
                                gen[base[rid]].append(GeneratedCandidate(key, blocker.path_name, sql))
                    t[blocker.path_name] += time.perf_counter() - t0
            finally:
                self._unregister_refs()
        return gen, t

    def match_batch(
        self,
        source_id: str,
        store: DuckDBStore | None = None,
        limit: int | None = None,
        strip_identifiers: bool = False,
    ) -> RunSummary:
        """Resolve every (latest) record of a source; persist candidates, links, abstentions.

        Works in chunks of SCORE_CHUNK references (generate, score, decide, persist) so
        memory stays bounded; the whole run is one transaction. `strip_identifiers=True`
        drops every identifier from the references (name path only) and runs under its own
        matcher version: the experiment that measures name-path precision and recall
        against the identifier links.
        """
        if store is not None and store is not self.store:
            raise ValueError("match_batch: the matcher is bound to its own store")
        t_start = time.perf_counter()
        version = self.version
        if strip_identifiers:
            version = MatcherVersion.create(self.policy, {**version.config, "strip_identifiers": True})
        version.save(self.store)
        run_id = version.version
        summary = RunSummary(run_id, version.version, source_id)
        timings: dict[str, float] = defaultdict(float)

        t0 = time.perf_counter()
        refs: list[Reference] = []
        for rec in self.store.records.by_source(source_id):
            ref = Reference.from_record(rec, self.names)
            if strip_identifiers:
                ref = dataclasses.replace(ref, identifiers=())
            refs.append(self.prepare(ref))
            if limit and len(refs) >= limit:
                break
        summary.records = len(refs)
        timings["load_refs"] = time.perf_counter() - t0

        con = self.con
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM candidate WHERE run_id = ? AND source = ?", [run_id, source_id])
            con.execute("DELETE FROM candidate_ref WHERE run_id = ? AND source = ?", [run_id, source_id])
            self._delete_decisions(version.version, source_id)
            for start in range(0, len(refs), self.SCORE_CHUNK):
                chunk = refs[start:start + self.SCORE_CHUNK]
                gen, gt = self._batch_generate(chunk)
                for k, v in gt.items():
                    timings[f"gen_{k}"] += v

                t0 = time.perf_counter()
                parties = self._party_views({g.canonical_key for gs in gen.values() for g in gs})
                uniq = self._unique_norms({r.name_norm for _, r in self._expand(chunk) if r.name_norm})
                timings["load_parties"] += time.perf_counter() - t0
                t0 = time.perf_counter()
                scored = [(ref, self._score(ref, gen.get(ref.record_id, []), parties, uniq,
                                            ref.alternative(self.names))) for ref in chunk]
                timings["features"] += time.perf_counter() - t0
                t0 = time.perf_counter()
                self._embed([(ref, c) for ref, cs in scored for c in cs])
                timings["embed"] += time.perf_counter() - t0

                t0 = time.perf_counter()
                cand_rows: list[dict[str, Any]] = []
                decisions: list[Decision] = []
                for ref, stored in scored:
                    info = self.ref_info(ref)
                    for c in stored:
                        cand_rows.extend(self._candidate_rows(run_id, ref, info, c))
                    decisions.append(arbitrate(info, stored, self.policy))
                timings["decide"] += time.perf_counter() - t0

                t0 = time.perf_counter()
                summary.candidates += self.store.candidates.save_many(cand_rows)
                self._save_refs(run_id, [(ref, self.ref_info(ref)) for ref, _ in scored])
                self._insert_decisions(version.version, decisions)
                timings["persist"] += time.perf_counter() - t0
                self._tally(summary, decisions)
                del cand_rows, decisions, gen, parties, scored
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        timings["total"] = time.perf_counter() - t_start
        summary.timings_s = {k: round(v, 3) for k, v in timings.items()}
        return summary

    def _save_refs(self, run_id: str, refs: list[tuple[Reference, dict[str, Any]]]) -> None:
        """One `candidate_ref` row per reference (also those with no candidate)."""
        if not refs:
            return
        self.con.register("_res_cref", pa.table({
            "run_id": [run_id] * len(refs),
            "source": [r.source for r, _ in refs],
            "record_id": [r.record_id for r, _ in refs],
            "ref": [_jdump(info) for _, info in refs],
        }))
        try:
            self.con.execute("INSERT OR REPLACE INTO candidate_ref SELECT run_id, source, record_id, ref::JSON "
                             "FROM _res_cref")
        finally:
            self.con.unregister("_res_cref")

    @staticmethod
    def _candidate_rows(run_id: str, ref: Reference, info: dict[str, Any], c: StoredCandidate) -> list[dict[str, Any]]:
        rows = []
        best = max([v for v in c.scores.values() if v is not None] or [0.0])
        for path in c.paths:
            rows.append({
                "run_id": run_id,
                "source": ref.source,
                "record_id": ref.record_id,
                "canonical_key": c.canonical_key,
                "path": path,
                "features": {
                    "features": c.features.as_dict(),
                    "scores": c.scores,
                    "query_text": c.query_text[path],
                },
                "score": best,
            })
        return rows

    @staticmethod
    def _tally(summary: RunSummary, decisions: list[Decision]) -> None:
        for d in decisions:
            if isinstance(d, Link):
                summary.links += 1
                summary.by_match_type[str(d.match_type)] = summary.by_match_type.get(str(d.match_type), 0) + 1
            elif isinstance(d, Abstention):
                summary.abstentions += 1
                summary.by_reason[str(d.reason)] = summary.by_reason.get(str(d.reason), 0) + 1

    def _delete_decisions(self, version: str, source_id: str) -> None:
        self.con.execute("DELETE FROM link WHERE matcher_version = ? AND source = ?", [version, source_id])
        self.con.execute("DELETE FROM abstention WHERE matcher_version = ? AND source = ?", [version, source_id])

    def _write_decisions(self, version: str, source_id: str, decisions: list[Decision]) -> None:
        """Set-based replace of this version's decisions for the source (caller owns the transaction)."""
        self._delete_decisions(version, source_id)
        self._insert_decisions(version, decisions)

    def _insert_decisions(self, version: str, decisions: list[Decision]) -> None:
        con = self.con
        links = [d for d in decisions if isinstance(d, Link)]
        abst = [d for d in decisions if isinstance(d, Abstention)]
        if links:
            con.register("_res_links", pa.table({
                "link_id": [_link_id(version, d.source, d.record_id) for d in links],
                "matcher_version": [version] * len(links),
                "source": [d.source for d in links],
                "record_id": [d.record_id for d in links],
                "canonical_key": [d.canonical_key for d in links],
                "match_type": [str(d.match_type) for d in links],
                "confidence": pa.array([float(d.confidence) for d in links], pa.float64()),
                "evidence": [_jdump(d.evidence.as_dict() if d.evidence else None) for d in links],
            }))
            try:
                con.execute(
                    """INSERT OR REPLACE INTO link (link_id, matcher_version, source, record_id, canonical_key,
                                                    match_type, confidence, evidence)
                       SELECT link_id, matcher_version, source, record_id, canonical_key, match_type,
                              confidence, evidence::JSON FROM _res_links"""
                )
            finally:
                con.unregister("_res_links")
        if abst:
            has_ev = bool(con.execute(
                "SELECT count(*) FROM duckdb_columns() WHERE table_name = 'abstention' AND column_name = 'evidence'"
            ).fetchall()[0][0])
            con.register("_res_abst", pa.table({
                "matcher_version": [version] * len(abst),
                "source": [d.source for d in abst],
                "record_id": [d.record_id for d in abst],
                "best_candidate": pa.array([d.best_candidate for d in abst], pa.string()),
                "best_score": pa.array([d.best_score for d in abst], pa.float64()),
                "reason": [str(d.reason) for d in abst],
                "evidence": [_jdump({"explanation": d.explanation,
                                     **(d.evidence.as_dict() if d.evidence else {})}) for d in abst],
            }))
            try:
                ev_col, ev_sel = (", evidence", ", evidence::JSON") if has_ev else ("", "")
                con.execute(
                    f"""INSERT OR REPLACE INTO abstention (matcher_version, source, record_id, best_candidate,
                                                          best_score, reason{ev_col})
                        SELECT matcher_version, source, record_id, best_candidate, best_score, reason{ev_sel}
                        FROM _res_abst"""
                )
            finally:
                con.unregister("_res_abst")

    # ------------------------------------------------------------------ recalibration

    def redecide(
        self,
        run_id: str,
        policy: ThresholdPolicy,
        source_id: str | None = None,
        scorer_config: ScorerConfig | None = None,
    ) -> RunSummary:
        """Re-apply `policy` to the stored candidates of `run_id`. No candidate generation and
        no feature extraction: features are read back from `candidate`.

        Scores are the stored ones, unless `scorer_config` is given: then they are recomputed
        from the stored features with the new weights and penalties, so a scorer change is as
        cheap as a policy change (only a new FEATURE needs a re-match). Writes a new matcher
        version (prefix 'mr-', candidates_run_id = run_id, config records the scorer config)
        and returns a summary with a diff against the run's own decisions.
        """
        t_start = time.perf_counter()
        con = self.con
        base = self.store.matcher_versions.get(run_id)
        if base is None:
            raise ValueError(f"unknown run {run_id!r}")
        base_policy = base["policy"] if isinstance(base["policy"], dict) else json.loads(base["policy"])
        config = dict(base_policy.get("config", {}))
        rescorers = None
        if scorer_config is not None:
            config["scorer_config"] = scorer_config.to_dict()
            config["rescored"] = True
            rescorers = scorer_config.scorers()
        mv = MatcherVersion.create(policy, config, candidates_run_id=run_id)
        mv.save(self.store)

        where, params = "WHERE run_id = ?", [run_id]
        if source_id:
            where += " AND source = ?"
            params.append(source_id)
        t0 = time.perf_counter()
        rows = con.execute(
            f"SELECT source, record_id, canonical_key, path, features FROM candidate {where} "
            "ORDER BY source, record_id, canonical_key, path",
            params,
        ).fetchall()
        infos: dict[tuple[str, str], dict[str, Any]] = {}
        for source, record_id, blob in con.execute(
            f"SELECT source, record_id, ref FROM candidate_ref {where}", params
        ).fetchall():
            infos[(source, record_id)] = json.loads(blob) if isinstance(blob, str) else blob
        grouped: dict[tuple[str, str], dict[str, StoredCandidate]] = defaultdict(dict)
        for source, record_id, key, path, blob in rows:
            payload = json.loads(blob) if isinstance(blob, str) else blob
            rk = (source, record_id)
            if rk not in infos:  # runs written before candidate_ref kept the reference per row
                infos[rk] = payload.get("ref") or {"source": source, "record_id": record_id}
            c = grouped[rk].get(key)
            if c is None:
                fv = FeatureVector.from_dict(payload["features"])
                scores = score_all(fv, rescorers) if rescorers else payload["scores"]
                c = StoredCandidate(key, [], {}, fv, scores)
                grouped[rk][key] = c
            c.paths.append(path)
            c.query_text[path] = payload.get("query_text", "")
        load_s = time.perf_counter() - t0

        # Records the base run abstained on with no candidate have no candidate rows.
        no_cand_sql = "SELECT source, record_id FROM abstention WHERE matcher_version = ? AND reason = 'NO_CANDIDATE'"
        no_cand_params: list[Any] = [run_id]
        if source_id:
            no_cand_sql += " AND source = ?"
            no_cand_params.append(source_id)
        no_cand = con.execute(no_cand_sql, no_cand_params).fetchall()

        t0 = time.perf_counter()
        by_source: dict[str, list[Decision]] = defaultdict(list)
        for rk, cands in grouped.items():
            by_source[rk[0]].append(arbitrate(infos[rk], list(cands.values()), policy))
        for source, record_id in no_cand:
            if (source, record_id) not in grouped:
                by_source[source].append(arbitrate({"source": source, "record_id": record_id}, [], policy))
        decide_s = time.perf_counter() - t0

        summary = RunSummary(run_id, mv.version, source_id or "*")
        con.execute("BEGIN TRANSACTION")
        try:
            for source, decisions in by_source.items():
                self._write_decisions(mv.version, source, decisions)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        for decisions in by_source.values():
            summary.records += len(decisions)
            self._tally(summary, decisions)
        summary.candidates = len(rows)
        summary.diff = self.diff(run_id, mv.version, source_id)
        summary.timings_s = {"load_candidates": round(load_s, 3), "decide": round(decide_s, 3),
                             "total": round(time.perf_counter() - t_start, 3)}
        return summary

    def diff(self, old_version: str, new_version: str, source_id: str | None = None) -> dict[str, int]:
        """Links added, dropped, retargeted and unchanged between two versions."""
        src = "AND source = ?" if source_id else ""
        params = [old_version] + ([source_id] if source_id else []) + [new_version] + ([source_id] if source_id else [])
        row = self.con.execute(
            f"""WITH o AS (SELECT source, record_id, canonical_key FROM link WHERE matcher_version = ? {src}),
                     n AS (SELECT source, record_id, canonical_key FROM link WHERE matcher_version = ? {src})
                SELECT count(*) FILTER (WHERE o.record_id IS NULL),
                       count(*) FILTER (WHERE n.record_id IS NULL),
                       count(*) FILTER (WHERE o.record_id IS NOT NULL AND n.record_id IS NOT NULL
                                        AND o.canonical_key <> n.canonical_key),
                       count(*) FILTER (WHERE o.canonical_key = n.canonical_key)
                FROM o FULL OUTER JOIN n USING (source, record_id)""",
            params,
        ).fetchall()[0]
        return {"links_added": row[0], "links_dropped": row[1], "links_retargeted": row[2], "links_unchanged": row[3]}


def reference_from_text(text: str) -> Reference:
    return ReferenceParser().parse(text)


__all__ = ["Matcher", "MatcherVersion", "RunSummary", "code_hash", "reference_from_text"]

