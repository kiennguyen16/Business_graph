"""Feature extraction: one `FeatureVector` per (reference, candidate party).

Features are raw measurements, never decisions. They are stored on every candidate
row so a new threshold or arbiter rule can be re-applied without regenerating
candidates (`Matcher.redecide`).
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from bizgraph.normalise.names import GENERIC_TOKENS, NameNormaliser, NormalisedName
from bizgraph.resolution.reference import LICENCE_SCHEMES, PARTY_SCHEMES, REGISTER_SOURCES, Reference

# Legal form families. Two forms conflict only when both are present and the families differ.
# None means the form says nothing about the register (CORP / CO appear in statutory names).
_FORM_FAMILY: dict[str, str | None] = {
    "PTY LTD": "proprietary",
    "LTD": "public",
    "NL": "public",
    "PLC": "public",
    "INC": "association",
    "LLC": "foreign",
    "CORP": "corporation",  # statutory / foreign corporations: compatible with public, not with PTY
    "CO": None,
}

TOKEN_JW_MIN = 0.93  # two distinctive tokens are "the same" when equal or a near-identical typo
TOKEN_JW_MIN_LEN = 5  # ...and only tokens this long may match by typo


@dataclass(frozen=True)
class PartyView:
    """What the matcher needs to know about one canonical party."""

    canonical_key: str
    party_type: str | None
    name: str | None
    name_norm: str | None
    state: str | None
    quarantined: bool
    identifiers: dict[str, frozenset[str]]  # scheme -> values
    names: tuple[tuple[str, str], ...] = ()  # (name_norm, kind) incl. aliases
    name_raw_by_norm: dict[str, str] = field(default_factory=dict)
    postcode: str | None = None
    entity_type: str | None = None  # ABR entity type code (PRV, OIE, DTT, SMF, ...) or ASIC type
    foreign_registration: bool = False  # the Australian registration of a foreign body (FNOS / OIE / ARBN)
    former_name_conflicts: frozenset[str] = frozenset()


@dataclass
class FeatureVector:
    identifier_match: bool = False
    identifier_match_schemes: list[str] = field(default_factory=list)
    identifier_conflict: bool = False
    identifier_conflict_schemes: list[str] = field(default_factory=list)
    name_exact: bool = False  # reference name_norm equals one of the party's names / aliases
    name_exact_unique: bool = False  # ...and no other party carries that name_norm
    jaro_winkler: float = 0.0
    token_set_ratio: float = 0.0
    distinctive_overlap: float = 0.0  # Jaccard on distinctive tokens (typo-tolerant)
    distinctive_coverage: float = 0.0  # share of the reference's distinctive tokens found in the candidate
    distinctive_coverage_rev: float = 0.0  # share of the candidate's distinctive tokens found in the reference
    distinctive_missing: list[str] = field(default_factory=list)  # reference tokens not in the candidate
    distinctive_extra: list[str] = field(default_factory=list)  # candidate tokens not in the reference
    legal_form_compatible: bool = True
    state_match: bool | None = None
    state_basis: str | None = None  # 'text' (stated in a free-text reference) or 'register'
    type_compatible: bool = True
    candidate_party_type: str | None = None
    candidate_quarantined: bool = False
    embedding_cosine: float | None = None
    compared_name: str | None = None
    compared_name_kind: str | None = None
    # v2: all meaningful tokens (generic words included; only stop words and legal forms out)
    ref_tokens_missing_in_candidate: list[str] = field(default_factory=list)
    candidate_extra_tokens: list[str] = field(default_factory=list)
    token_overlap: float = 0.0  # Jaccard on meaningful tokens (typo-tolerant, AU geography exempt)
    entity_kind_conflict: bool = False  # trust / fund vs company
    geo_conflict: bool = False  # formal reference without 'Australia' vs a candidate that has it
    weak_alias: bool = False  # formal reference matched only through a business / trading name
    ref_formal: bool = False  # the reference is a registered legal name (legal form or register source)
    ref_legal_form: str | None = None
    candidate_legal_form: str | None = None
    # v3 gate inputs, stored so a gate change can be replayed by redecide
    ref_jurisdiction: str | None = None
    candidate_foreign_registration: bool = False
    jurisdiction_conflict: bool = False  # non-AU reference vs an Australian-incorporated party
    ref_postcode: str | None = None
    candidate_postcode: str | None = None
    postcode_match: bool | None = None
    trust_like: bool = False  # trust or super fund on either side (needs postcode / state agreement)
    candidate_entity_type: str | None = None
    party_type_basis: str | None = None
    former_name_conflict: bool = False
    person_business_name_exact: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FeatureVector:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# 'A' is not a stop word: in registered names it is a class letter ('... TRUST A').
STOP_TOKENS: frozenset[str] = frozenset({"THE", "OF", "AND", "FOR"})
# Australian geography words may be absent from the candidate (and are not counted as extras for
# an informal reference): 'Commonwealth Bank' is COMMONWEALTH BANK OF AUSTRALIA. NZ and other
# country words are NOT exempt: 'X (NZ) LIMITED' is a different entity from the Australian X.
AU_GEO: frozenset[str] = frozenset({"AUSTRALIA", "AUSTRALIAN", "AUST", "AUS"})
TRUST_END: frozenset[str] = frozenset({"TRUST", "FUND", "SCHEME"})
# ABR entity types that are trusts or superannuation funds.
TRUST_ENTITY_TYPES: frozenset[str] = frozenset(
    "SMF DTT DIT FUT DST TRT FXT HYT PQT CUT CMT PUT PTT STU SSS NRF POF NPF PST".split()
)
WEAK_ALIAS_KINDS: frozenset[str] = frozenset({"business_name", "trading_name", "other_name", "dgr_name"})
COMPANY_FAMILIES: frozenset[str] = frozenset({"proprietary", "public"})


def meaningful_tokens(norm: str | None) -> list[str]:
    return [t for t in (norm or "").split() if t not in STOP_TOKENS]


def entity_kind(norm: str | None, legal_form: str | None, raw: str | None = None) -> str | None:
    """'company' (proprietary or public legal form), 'trust' (a 'trustee for' name, or the name
    ends TRUST / FUND / SCHEME), else None."""
    if legal_form and _FORM_FAMILY.get(legal_form) in COMPANY_FAMILIES:
        return "company"  # THE GROWTH FUND PTY LTD is a company, whatever its last word
    if raw and re.search(r"\bTRUSTEES? (FOR|OF)\b|\bATF\b", raw.upper()):
        return "trust"
    toks = meaningful_tokens(norm)
    if toks and toks[-1] in TRUST_END:
        return "trust"
    return None


def token_alignment(ref: list[str], cand: list[str], typos: bool = True) -> tuple[list[str], list[str], int]:
    """Greedy one-to-one alignment of token lists (multiset). Returns (missing, extra, matched)."""
    remaining = list(cand)
    missing: list[str] = []
    matched = 0
    for t in ref:
        hit = next((i for i, c in enumerate(remaining) if c == t), None)
        if hit is None:
            hit = next((i for i, c in enumerate(remaining) if typos and _token_match(t, c)), None)
        if hit is None:
            missing.append(t)
        else:
            remaining.pop(hit)
            matched += 1
    return missing, remaining, matched


def _token_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < TOKEN_JW_MIN_LEN:
        return False
    return JaroWinkler.similarity(a, b) >= TOKEN_JW_MIN


_GENERIC_LONG = tuple(sorted(t for t in GENERIC_TOKENS if len(t) >= TOKEN_JW_MIN_LEN))
_typo_generic_cache: dict[str, bool] = {}


def is_generic_typo(token: str) -> bool:
    """'TRADNG' is a typo of the generic 'TRADING', not a distinctive token."""
    hit = _typo_generic_cache.get(token)
    if hit is None:
        hit = len(token) >= TOKEN_JW_MIN_LEN and any(_token_match(token, g) for g in _GENERIC_LONG)
        if len(_typo_generic_cache) < 200_000:
            _typo_generic_cache[token] = hit
    return hit


def distinctive_alignment(ref: frozenset[str], cand: frozenset[str], typos: bool = True
                          ) -> tuple[list[str], list[str], int]:
    """Greedy one-to-one alignment. Returns (ref tokens unmatched, cand tokens unmatched, matched)."""
    remaining = set(cand)
    missing: list[str] = []
    matched = 0
    for t in sorted(ref):
        hit = t if t in remaining else next(
            (c for c in sorted(remaining) if typos and _token_match(t, c)), None)
        if hit is None:
            missing.append(t)
        else:
            remaining.discard(hit)
            matched += 1
    return missing, sorted(remaining), matched


class Embedder:
    """Optional local sentence embeddings (sentence-transformers, CPU).

    `Embedder.load()` returns None when the package is missing or BIZGRAPH_EMBEDDINGS=0,
    and the semantic path is then simply absent (never an error).
    """

    DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self, model: Any, model_name: str) -> None:
        self.model = model
        self.model_name = model_name
        self._cache: dict[str, Any] = {}

    @classmethod
    def load(cls, model_name: str | None = None) -> Embedder | None:
        if os.environ.get("BIZGRAPH_EMBEDDINGS", "1") == "0":
            return None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except Exception:
            return None
        name = model_name or os.environ.get("BIZGRAPH_EMBEDDING_MODEL", cls.DEFAULT_MODEL)
        try:
            model = SentenceTransformer(name, device="cpu")
        except Exception:
            return None
        return cls(model, name)

    def encode(self, texts: list[str]) -> list[Any]:
        todo = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if todo:
            vecs = self.model.encode(todo, batch_size=256, normalize_embeddings=True, show_progress_bar=False)
            for t, v in zip(todo, vecs):
                self._cache[t] = v
        return [self._cache[t] for t in texts]

    def cosine(self, a: str, b: str) -> float:
        va, vb = self.encode([a, b])
        return float((va * vb).sum())


class FeatureExtractor:
    def __init__(self, normaliser: NameNormaliser | None = None, embedder: Embedder | None = None) -> None:
        self.names = normaliser or NameNormaliser()
        self.embedder = embedder
        self._norm_cache: dict[str, NormalisedName | None] = {}

    def _normalise_norm(self, norm: str, person: bool = False) -> NormalisedName | None:
        """Re-normalise an already-normalised name (idempotent) to get its distinctive tokens.
        Individuals use the person normaliser (no legal-form or trust handling)."""
        key = ("P:" if person else "O:") + norm
        if key not in self._norm_cache:
            if len(self._norm_cache) > 500_000:
                self._norm_cache.clear()
            self._norm_cache[key] = self.names.normalise_person(norm) if person else self.names.normalise(norm)
        return self._norm_cache[key]

    def _legal_form(self, raw: str | None) -> str | None:
        if not raw:
            return None
        n = self.names.normalise(raw)
        return n.legal_form if n else None

    @staticmethod
    def _forms_compatible(a: str | None, b: str | None) -> bool:
        if not a or not b:
            return True
        fa, fb = _FORM_FAMILY.get(a), _FORM_FAMILY.get(b)
        if fa is None or fb is None or fa == fb:
            return True
        return {fa, fb} == {"corporation", "public"}

    def extract(
        self,
        ref: Reference,
        party: PartyView,
        unique_norms: set[str] | None = None,
    ) -> FeatureVector:
        fv = FeatureVector()
        # ---- identifiers
        for ident in ref.identifiers:
            scheme = ident.scheme.value
            have = party.identifiers.get(scheme)
            if not have:
                continue
            if ident.value in have:
                if scheme not in fv.identifier_match_schemes:
                    fv.identifier_match_schemes.append(scheme)
            elif scheme in PARTY_SCHEMES and not (scheme == "lei" and ref.lei_is_duplicate):
                # A DUPLICATE LEI means the entity has another LEI too: not a conflict.
                if scheme not in fv.identifier_conflict_schemes:
                    fv.identifier_conflict_schemes.append(scheme)
            elif scheme in LICENCE_SCHEMES:
                pass  # licences transfer; a different number is not evidence against identity
        fv.identifier_match = bool(fv.identifier_match_schemes)
        fv.identifier_conflict = bool(fv.identifier_conflict_schemes)

        # ---- type / quarantine / state
        fv.candidate_party_type = party.party_type
        hint = str(ref.party_type_hint)
        fv.type_compatible = not (
            hint in ("person", "organisation") and party.party_type in ("person", "organisation")
            and hint != party.party_type
        )
        fv.candidate_quarantined = bool(party.quarantined)
        fv.ref_jurisdiction = ref.jurisdiction
        fv.candidate_foreign_registration = bool(party.foreign_registration)
        fv.jurisdiction_conflict = bool(ref.jurisdiction and ref.jurisdiction != "AU"
                                        and not party.foreign_registration)
        fv.ref_postcode, fv.candidate_postcode = ref.postcode, party.postcode
        if ref.postcode and party.postcode:
            fv.postcode_match = ref.postcode == party.postcode
        fv.candidate_entity_type = party.entity_type
        fv.party_type_basis = ref.party_type_basis
        if ref.state and party.state:
            fv.state_match = ref.state.upper() == party.state.upper()
            fv.state_basis = ref.state_basis

        # ---- names: compare against every name / alias of the party; keep the one that misses the
        # fewest reference tokens, then the most similar
        ref_norm = ref.name_norm
        if not ref_norm:
            return fv
        ref_toks = meaningful_tokens(ref_norm)
        # Australian geography words are exempt only for an informal reference ('Commonwealth
        # Bank'); in a registered legal name they are part of the name ('NAOL AUSTRALIA PTY
        # LIMITED' is not NAOL PTY LTD).
        exempt = frozenset() if ref.formal else AU_GEO
        ref_core = [t for t in ref_toks if t not in exempt]
        names = list(party.names) or ([(party.name_norm, "name")] if party.name_norm else [])
        best: tuple[tuple[int, float], str, str, list[str], list[str], int] | None = None
        for norm, kind in names:
            if not norm:
                continue
            cand_core = [t for t in meaningful_tokens(norm) if t not in exempt]
            # A name read from a register is spelt exactly: no typo tolerance ('SUNRISE MEDICAL' is
            # not 'SUNRISE MEDIA'); free text keeps it ('Comonwealth Bank').
            missing, extra, matched = token_alignment(ref_core, cand_core, typos=ref.source not in REGISTER_SOURCES)
            if norm == ref_norm:
                key = (-1, 0.0)
            else:
                key = (len(missing), -(JaroWinkler.similarity(ref_norm, norm)
                                       + fuzz.token_set_ratio(ref_norm, norm) / 100.0))
            if best is None or key < best[0]:
                best = (key, norm, kind, missing, extra, matched)
        if best is None:
            return fv
        _, cnorm, ckind, missing_all, extra_all, matched_all = best
        fv.compared_name, fv.compared_name_kind = cnorm, ckind
        fv.former_name_conflict = ckind == "former_name" and cnorm in party.former_name_conflicts
        fv.name_exact = cnorm == ref_norm
        fv.name_exact_unique = fv.name_exact and (unique_norms is None or cnorm in unique_norms)
        fv.person_business_name_exact = (
            party.party_type == "person" and fv.name_exact_unique
            and ckind in ("business_name", "trading_name")
            and ref.state_basis == "text" and hint != "person" and "person_shaped_name" not in ref.notes
        )
        fv.jaro_winkler = round(JaroWinkler.similarity(ref_norm, cnorm), 4)
        fv.token_set_ratio = round(fuzz.token_set_ratio(ref_norm, cnorm) / 100.0, 4)
        fv.ref_tokens_missing_in_candidate = missing_all
        fv.candidate_extra_tokens = extra_all
        union_all = len(ref_core) + len(extra_all)
        fv.token_overlap = round(matched_all / union_all, 4) if union_all else 0.0

        cn = self._normalise_norm(cnorm, person=party.party_type == "person"
                                  and ckind not in ("business_name", "trading_name"))
        cand_d = frozenset(t for t in (cn.distinctive if cn else ()) if not is_generic_typo(t))
        ref_d = frozenset(t for t in ref.distinctive if not is_generic_typo(t))
        missing, extra, matched = distinctive_alignment(ref_d, cand_d, typos=ref.source not in REGISTER_SOURCES)
        union = len(ref_d) + len(cand_d) - matched
        fv.distinctive_overlap = round(matched / union, 4) if union else 0.0
        fv.distinctive_coverage = round(matched / len(ref_d), 4) if ref_d else 0.0
        fv.distinctive_coverage_rev = round(matched / len(cand_d), 4) if cand_d else 0.0
        fv.distinctive_missing, fv.distinctive_extra = missing, extra

        ref_form = ref.normalised.legal_form if ref.normalised else None
        cand_form = None if party.party_type == "person" else self._legal_form(
            party.name_raw_by_norm.get(cnorm) or party.name)
        fv.ref_legal_form, fv.candidate_legal_form = ref_form, cand_form
        # The candidate's current legal name must be compatible too: a former name can be reused
        # ('VECTOR LIMITED' as a former name of a company now called EMPORESS PTY LTD).
        current_form = None if party.party_type == "person" else self._legal_form(party.name)
        fv.legal_form_compatible = (self._forms_compatible(ref_form, cand_form)
                                    and self._forms_compatible(ref_form, current_form))
        cand_raw = party.name_raw_by_norm.get(cnorm) or party.name
        rk = entity_kind(ref_norm, ref_form, ref.name_raw)
        ck = entity_kind(cnorm, cand_form or current_form, cand_raw)
        fv.entity_kind_conflict = bool(rk and ck and rk != ck)
        fv.trust_like = (rk == "trust" or ck == "trust" or (party.entity_type or "") in TRUST_ENTITY_TYPES
                         or any(t in ("SUPER", "SUPERANNUATION", "SUPERFUND") for t in ref_toks))
        formal = ref.formal
        fv.ref_formal = formal
        cand_geo = any(t in AU_GEO for t in meaningful_tokens(cnorm))
        ref_geo = any(t in AU_GEO for t in ref_toks)
        fv.geo_conflict = formal and cand_geo and not ref_geo
        fv.weak_alias = formal and ckind in WEAK_ALIAS_KINDS

        if self.embedder is not None:
            fv.embedding_cosine = round(self.embedder.cosine(ref_norm, cnorm), 4)
        return fv
