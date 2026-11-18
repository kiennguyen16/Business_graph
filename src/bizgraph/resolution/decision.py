"""Scorers, threshold policy, decisions and the arbiter.

Scoring is separated from deciding: scorers turn a `FeatureVector` into raw path
scores (stored with every candidate); `arbitrate` turns the stored candidates of
one reference plus a `ThresholdPolicy` into a `Link` or an `Abstention`. Nothing in
`arbitrate` touches the database, which is what lets `Matcher.redecide` re-run it
over stored candidates under a new policy.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from bizgraph.domain.models import AbstainReason, MatchType
from bizgraph.resolution.features import FeatureVector
from bizgraph.resolution.reference import PARTY_SCHEMES as PARTY_ID_SCHEMES

# Exact path label per identifier scheme, in precedence order. ARBN / ARSN are ASIC
# register numbers in the same 9-digit space as the ACN; they get EXACT_ACN as the
# label and the scheme is kept in the evidence (no separate concept in the vocabulary yet).
SCHEME_MATCH_TYPE: dict[str, MatchType] = {
    "abn": MatchType.EXACT_ABN,
    "acn": MatchType.EXACT_ACN,
    "arbn": MatchType.EXACT_ACN,
    "arsn": MatchType.EXACT_ACN,
    "lei": MatchType.EXACT_LEI,
    "afsl": MatchType.EXACT_LICENCE_NO,
    "acl": MatchType.EXACT_LICENCE_NO,
    "liquidator_no": MatchType.EXACT_LICENCE_NO,
}

PATH_EXACT_ID = "exact_identifier"
PATH_NAME_EXACT = "exact_name"
PATH_TOKEN_STATE = "block_token_state"
PATH_FTS = "block_fts"
PATH_EMBEDDING = "block_embedding"


# --------------------------------------------------------------------------- scorers


class Scorer(ABC):
    name: str

    @abstractmethod
    def score(self, fv: FeatureVector) -> float | None: ...


class ExactScorer(Scorer):
    """1.0 when an identifier matches and no party identifier disagrees, else 0.0."""

    name = "exact"

    def score(self, fv: FeatureVector) -> float:
        return 1.0 if fv.identifier_match and not fv.identifier_conflict else 0.0


@dataclass(frozen=True)
class ScorerConfig:
    """Every number the scorers use. Recorded in the matcher version's config; passing a new
    one to `Matcher.redecide` recomputes the scores from the stored features (no re-match).

    state_penalty_text      the reference text explicitly states a state and the party is elsewhere
    state_penalty_register  register-to-register (e.g. GLEIF legal address vs ABR business
                            location): the two addresses mean different things, so a small penalty
    state_bonus             tie-breaker when the states agree
    """

    w_jw: float = 0.30
    w_tsr: float = 0.20
    w_tok: float = 0.50
    legal_form_penalty: float = 0.10
    state_penalty_text: float = 0.15
    state_penalty_register: float = 0.05
    state_bonus: float = 0.02

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ScorerConfig:
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def adjustments(self, fv: FeatureVector) -> float:
        """Score adjustments shared by the fuzzy and semantic paths."""
        adj = 0.0
        if fv.state_match is False:
            adj -= self.state_penalty_text if fv.state_basis == "text" else self.state_penalty_register
        elif fv.state_match is True:
            adj += self.state_bonus
        if not fv.legal_form_compatible:
            adj -= self.legal_form_penalty
        return adj

    def scorers(self) -> tuple[Scorer, ...]:
        return (ExactScorer(), FuzzyScorer(self), SemanticScorer(self))


class FuzzyScorer(Scorer):
    """Character and token similarity, weighted towards whole-name token agreement.

    token_set_ratio alone scores a subset as 1.0 ('COMMONWEALTH' vs 'COMMONWEALTH BANK'),
    so half the weight sits on the Jaccard over all meaningful tokens (generic words included,
    Australian geography words exempt for informal references), which punishes extra or missing
    tokens on either side: 'Quorva' scores the same against QUORVA TRADING and QUORVA TRADERS.
    """

    name = "fuzzy"

    def __init__(self, config: ScorerConfig | None = None) -> None:
        self.config = config or ScorerConfig()

    def score(self, fv: FeatureVector) -> float:
        c = self.config
        s = c.w_jw * fv.jaro_winkler + c.w_tsr * fv.token_set_ratio + c.w_tok * fv.token_overlap
        return round(min(1.0, max(0.0, s + c.adjustments(fv))), 4)


class SemanticScorer(Scorer):
    """Embedding cosine on normalised names (same adjustments as fuzzy), or None when no
    embedder is installed or the candidate failed the two-way token gate."""

    name = "semantic"

    def __init__(self, config: ScorerConfig | None = None) -> None:
        self.config = config or ScorerConfig()

    def score(self, fv: FeatureVector) -> float | None:
        if fv.embedding_cosine is None:
            return None
        return round(min(1.0, max(0.0, fv.embedding_cosine + self.config.adjustments(fv))), 4)


DEFAULT_SCORER_CONFIG = ScorerConfig()
DEFAULT_SCORERS: tuple[Scorer, ...] = DEFAULT_SCORER_CONFIG.scorers()


def score_all(fv: FeatureVector, scorers: tuple[Scorer, ...] = DEFAULT_SCORERS) -> dict[str, float | None]:
    return {s.name: s.score(fv) for s in scorers}


# --------------------------------------------------------------------------- policy


@dataclass(frozen=True)
class ThresholdPolicy:
    """Every number the decision depends on. Serialised into `matcher_version.policy`.

    default            name-path threshold for ordinary sources (provisional until the label sweep)
    per_source         stricter thresholds where a wrong link publishes an accusation
    min_margin         top-1 minus top-2 below this -> AMBIGUOUS
    strict_min_margin  margin for the strict (per_source above default) sources
    unknown_type_threshold  floor for references whose party type is unknown
    person_name_links  False: a person is never linked on a name alone
    name_exact_confidence   confidence of NAME_NORMALISED_EXACT (unique normalised name)
    semantic_min_fuzzy fuzzy floor below which the semantic path cannot lift a candidate
    """

    default: float = 0.90
    per_source: dict[str, float] = field(
        default_factory=lambda: {"asic_banned_org": 0.97, "accc_notice": 0.97}
    )
    min_margin: float = 0.05
    strict_min_margin: float = 0.10
    unknown_type_threshold: float = 0.95
    person_name_links: bool = False
    name_exact_confidence: float = 0.97
    semantic_min_fuzzy: float = 0.80
    licence_confidence: float = 0.95

    def threshold(self, source: str, party_type_hint: str | None = None) -> float:
        t = self.per_source.get(source, self.default)
        if (party_type_hint or "unknown") == "unknown":
            t = max(t, self.unknown_type_threshold)
        return t

    def is_strict(self, source: str) -> bool:
        return self.per_source.get(source, self.default) > self.default

    def margin(self, source: str) -> float:
        return self.strict_min_margin if self.is_strict(source) else self.min_margin

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["per_source"] = dict(sorted(self.per_source.items()))
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ThresholdPolicy:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- decisions


@dataclass
class StoredCandidate:
    """One (reference, party) pair as persisted in `candidate` (paths merged)."""

    canonical_key: str
    paths: list[str]
    query_text: dict[str, str]  # path -> SQL that found it
    features: FeatureVector
    scores: dict[str, float | None]


@dataclass
class RankedCandidate:
    canonical_key: str
    match_type: str
    path: str  # 'exact' or 'semantic' (the named path the label belongs to)
    score: float
    eligible: bool
    veto: str | None
    found_by: list[str]
    query_text: dict[str, str]
    features: dict[str, Any]
    scores: dict[str, float | None]
    name_pass: bool = False  # the name path alone (before any veto) clears the threshold

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    features: dict[str, Any]
    path: str
    found_by: list[str]
    query_text: dict[str, str]
    scores: dict[str, float | None]
    explanation: str
    threshold: float | None = None
    runner_up: dict[str, Any] | None = None
    disagreement: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    source: str
    record_id: str
    ranked: list[RankedCandidate]
    explanation: str

    @property
    def resolved(self) -> bool:
        return isinstance(self, Link)


@dataclass
class Link(Decision):
    canonical_key: str = ""
    match_type: MatchType = MatchType.NAME_FUZZY
    confidence: float = 0.0
    evidence: Evidence | None = None


@dataclass
class Abstention(Decision):
    reason: AbstainReason = AbstainReason.NO_CANDIDATE
    best_candidate: str | None = None
    best_score: float | None = None
    evidence: Evidence | None = None


# --------------------------------------------------------------------------- arbiter


def _exact_label(fv: FeatureVector) -> MatchType:
    for scheme in SCHEME_MATCH_TYPE:  # precedence order
        if scheme in fv.identifier_match_schemes:
            return SCHEME_MATCH_TYPE[scheme]
    return MatchType.EXACT_ABN  # unreachable when identifier_match is True


def _name_path(c: StoredCandidate, policy: ThresholdPolicy, strict: bool) -> tuple[MatchType, float, bool, str | None]:
    """Label, score, eligible, why-not for the name paths of one candidate (rules R5 to R7)."""
    fv = c.features
    fuzzy = float(c.scores.get("fuzzy") or 0.0)
    semantic = c.scores.get("semantic")
    why = None
    if fv.ref_tokens_missing_in_candidate:  # R5a: every reference token (generic ones too)
        why = f"reference token(s) missing from candidate: {','.join(fv.ref_tokens_missing_in_candidate)}"
    elif fv.distinctive_coverage < 1.0:  # R5b: at least one distinctive token, all present
        why = (
            "reference has no distinctive token" if not fv.distinctive_missing
            else f"distinctive token(s) missing from candidate: {','.join(fv.distinctive_missing)}"
        )
    elif not fv.legal_form_compatible:  # R5c
        why = f"legal form incompatible ({fv.ref_legal_form} vs {fv.candidate_legal_form})"
    elif fv.entity_kind_conflict:  # R5d
        why = "entity kind conflict (trust or fund vs company)"
    elif fv.geo_conflict:  # R5e
        why = "formal name without AUSTRALIA vs an Australian-named candidate (likely another group entity)"
    elif fv.trust_like and (fv.postcode_match is False or fv.state_match is False):  # R5h
        why = ("trust or super fund: "
               + ("postcode differs" if fv.postcode_match is False else "stated state differs"))
    elif fv.weak_alias:  # R5f
        why = f"formal name matches only a {fv.compared_name_kind} of the candidate, not a legal name"
    elif fv.ref_formal and fv.candidate_extra_tokens:  # R5g
        why = f"formal name, candidate has extra token(s): {','.join(fv.candidate_extra_tokens)}"
    if why:
        return MatchType.NAME_FUZZY, fuzzy, False, why
    if fv.name_exact_unique and not fv.weak_alias and fv.state_match is not False:
        return MatchType.NAME_NORMALISED_EXACT, policy.name_exact_confidence, True, None  # R6
    # R7: the semantic path may lift a candidate only with full two-way token agreement and
    # a fuzzy floor; it can never rescue a candidate the token gate rejected.
    if (
        semantic is not None
        and not fv.candidate_extra_tokens
        and fv.distinctive_coverage_rev >= 1.0
        and fuzzy >= policy.semantic_min_fuzzy
        and semantic > fuzzy
    ):
        return MatchType.NAME_SEMANTIC, float(semantic), True, None
    return MatchType.NAME_FUZZY, fuzzy, True, None


SOFT_TYPE_BASES = ("gleif_entity_category", "sole_proprietor")


def _soft_type_hint(ref_info: dict[str, Any]) -> bool:
    """The reference's party type is a hint, not a register fact (GLEIF entity category,
    GLEIF SOLE_PROPRIETOR, or unknown)."""
    if (ref_info.get("party_type_hint") or "unknown") == "unknown":
        return True
    return str(ref_info.get("party_type_basis") or "").startswith(SOFT_TYPE_BASES)


def arbitrate(
    ref_info: dict[str, Any],
    candidates: list[StoredCandidate],
    policy: ThresholdPolicy,
) -> Decision:
    """Decide one reference. Rules, applied in order (first that fires wins):

    R0  No candidate at all                                    -> abstain NO_CANDIDATE.
    R1  Exact path. Party identifiers (ABN, ACN, ARBN, ARSN, LEI) outrank licence numbers
        (AFSL, ACL, liquidator number), which transfer between holders:
        a. the winning identifiers point at two or more parties -> abstain IDENTIFIER_CONFLICT
        b. the matched party disagrees on another party identifier (a GLEIF DUPLICATE LEI
           never counts)                                        -> abstain IDENTIFIER_CONFLICT
        c. person vs organisation                               -> abstain PARTY_TYPE_CONFLICT,
           except when an ABN stated by the source matches and the reference's type is only
           a hint (GLEIF entity category / SOLE_PROPRIETOR, or unknown): link EXACT_ABN and
           record the type disagreement in the evidence
        d. the party is quarantined                             -> abstain QUARANTINED_TARGET
        e. rivals = other parties whose name path alone clears the threshold (vetoed or not),
           plus licence matches elsewhere. Licence-only match with a rival, or any rival on
           a strict source                                       -> abstain IDENTIFIER_CONFLICT
        f. otherwise link EXACT_<scheme>: confidence 1.0 for a party identifier,
           policy.licence_confidence (0.95) for a licence number (so it must also clear the
           threshold). Rivals are recorded in evidence.disagreement, never acted on.
    R2  A name candidate whose party identifiers disagree with the reference's is vetoed (a
        name never overrides an identifier). If the veto blocked a candidate that would
        otherwise clear the threshold                           -> abstain IDENTIFIER_CONFLICT.
    R3  Person vs organisation candidates are vetoed the same way -> PARTY_TYPE_CONFLICT.
    R3b A reference whose legal jurisdiction is not AU (GLEIF) may match on name only a party
        that is the Australian registration of a foreign body (ABR OIE, ASIC FNOS / RACN,
        ARBN); any other name candidate is vetoed                 -> JURISDICTION_MISMATCH.
        A vetoed candidate below the threshold is only a weak candidate (R8 applies).
    R4  A person reference is never linked on a name alone (policy.person_name_links). An
        UNKNOWN reference shaped like a person's name ('John Smith') counts as a person
        (Matcher.prepare), and so do liquidator records.          -> BELOW_THRESHOLD.
    R5  Name gate; failing any part makes the candidate ineligible whatever its fuzzy or
        embedding score:
        a. every meaningful reference token (generic words included: CAPITAL, TRUST,
           SECURITIES, GROUP; only stop words, legal forms and Australian geography words
           exempt) is in the candidate's name or one alias (typo tolerant);
        b. the reference has a distinctive token and all of them are present
           ('COMMONWEALTH BANK' cannot reach 'COMMONWEALTH SUPERANNUATION');
        c. compatible legal forms (PTY LTD vs LTD vs INC are different entities);
        d. no trust or fund vs company conflict ('BLUEGUM TRUST' is not BLUEGUM PTY LTD);
        e. a formal name without AUSTRALIA does not match a candidate named '... AUSTRALIA'
           (typically the local subsidiary of a foreign parent). "Formal" = the reference
           carries a legal form or comes from a register (GLEIF, ASIC registers): its name
           is a registered legal name;
        f. a formal name does not match through a business / trading / other name alias;
        h. a trust or super fund (either side) needs postcode agreement when both sides have
           one, and a stated state that differs is a veto, not a penalty;
        g. a formal name does not match a candidate whose name has extra tokens
           ('... SHARES FUND' is not '... SUSTAINABLE SHARES FUND').
    R6  NAME_NORMALISED_EXACT when the normalised name (or a registered legal-name alias) is
        equal, no other party has it, it is not only a business / trading name of a formal
        reference, and no stated state disagrees; confidence policy.name_exact_confidence.
    R7  Otherwise NAME_FUZZY with the fuzzy score, or NAME_SEMANTIC when the embedding
        cosine (same adjustments) is higher, the candidate has no extra token, and the fuzzy
        score clears policy.semantic_min_fuzzy. Adjustments: a stated state that differs
        -0.15 when the reference text states it, -0.05 register to register; a matching
        state +0.02 (all in ScorerConfig).
    R8  Best score below policy.threshold(source, type)         -> abstain BELOW_THRESHOLD.
    R9  The best eligible candidate is quarantined               -> abstain QUARANTINED_TARGET.
    R10 Best minus second-best eligible (another party), rounded to 4 dp, below
        policy.margin(source), or an exact tie                   -> abstain AMBIGUOUS.
    R11 Link with the label from R6 / R7.
    """
    source, record_id = ref_info.get("source", ""), ref_info.get("record_id", "")
    hint = ref_info.get("party_type_hint") or "unknown"
    strict = policy.is_strict(source)
    threshold = policy.threshold(source, hint)

    def abstain(reason: AbstainReason, ranked: list[RankedCandidate], why: str,
                best: RankedCandidate | None = None) -> Abstention:
        best = best or (ranked[0] if ranked else None)
        ev = None
        if best is not None:
            ev = Evidence(best.features, best.path, best.found_by, best.query_text, best.scores, why, threshold)
        return Abstention(source, record_id, ranked, why, reason=reason,
                          best_candidate=best.canonical_key if best else None,
                          best_score=best.score if best else None, evidence=ev)

    # R0
    if not candidates:
        return abstain(AbstainReason.NO_CANDIDATE, [], "no candidate from any generator")

    ranked: list[RankedCandidate] = []
    blocked: list[tuple[RankedCandidate, AbstainReason]] = []  # vetoed, but would have passed on name
    reused_former_names: list[RankedCandidate] = []
    for c in candidates:
        fv = c.features
        veto = None
        would_pass = False
        if fv.identifier_conflict:
            veto = f"identifier conflict on {','.join(fv.identifier_conflict_schemes)}"
        elif not fv.type_compatible and (fv.identifier_match or not fv.person_business_name_exact):
            veto = f"party type conflict (reference {hint}, candidate {fv.candidate_party_type})"
        elif fv.jurisdiction_conflict and not fv.identifier_match:
            veto = (f"jurisdiction mismatch: {fv.ref_jurisdiction} entity vs an Australian-incorporated party "
                    f"({fv.candidate_entity_type or 'unknown type'}), not a foreign-body registration")
        if fv.identifier_match:
            label, score, eligible, why = _exact_label(fv), (1.0 if veto is None else 0.0), veto is None, veto
            path = "exact"
        else:
            label, score, eligible, why = _name_path(c, policy, strict)
            path = "exact" if label is MatchType.NAME_NORMALISED_EXACT else "semantic"
            would_pass = eligible and score >= threshold
            if veto:
                eligible, why = False, veto
            elif fv.former_name_conflict:
                eligible, why = False, "former name has another current holder or multiple former holders"
            elif not policy.person_name_links and hint == "person":
                eligible, why = False, "person references are not linked on a name alone"
            elif ref_info.get("state_basis") == "text" and fv.candidate_party_type == "person" and (
                not fv.person_business_name_exact or label is not MatchType.NAME_NORMALISED_EXACT
            ):
                eligible, why = False, "person candidate requires a unique exact business or trading name"
        rc = RankedCandidate(c.canonical_key, str(label), path, round(score, 4), eligible, why,
                             sorted(c.paths), c.query_text, fv.as_dict(), c.scores, would_pass)
        ranked.append(rc)
        if fv.former_name_conflict and not fv.identifier_match and (would_pass or fv.name_exact):
            reused_former_names.append(rc)
        if veto and not fv.identifier_match and (would_pass or (
            fv.jurisdiction_conflict and fv.name_exact and not fv.identifier_conflict and fv.type_compatible
        )):
            if fv.identifier_conflict:
                kind = AbstainReason.IDENTIFIER_CONFLICT
            elif not fv.type_compatible and not fv.person_business_name_exact:
                kind = AbstainReason.PARTY_TYPE_CONFLICT
            else:
                kind = AbstainReason.JURISDICTION_MISMATCH
            blocked.append((rc, kind))
    ranked.sort(key=lambda r: (not r.features["identifier_match"], not r.eligible, -r.score, r.canonical_key))

    # R1 exact path. Party identifiers (ABN, ACN, ARBN, ARSN, LEI) outrank licence numbers,
    # which transfer between holders.
    id_hits = [r for r in ranked if r.features["identifier_match"]]
    if id_hits:
        party_hits = [r for r in id_hits if set(r.features["identifier_match_schemes"]) & PARTY_ID_SCHEMES]
        licence_only = not party_hits
        hits = party_hits or id_hits
        keys = sorted({r.canonical_key for r in hits})
        if len(keys) > 1:
            return abstain(AbstainReason.IDENTIFIER_CONFLICT, ranked,
                           f"reference identifiers point at {len(keys)} different parties: {', '.join(keys)}")
        top = hits[0]
        f = top.features
        if top.veto and not f["identifier_conflict"] and not f["type_compatible"] \
                and "abn" in f["identifier_match_schemes"] and _soft_type_hint(ref_info):
            top.eligible, top.veto, top.score = True, None, 1.0
        if f["identifier_conflict"]:
            return abstain(AbstainReason.IDENTIFIER_CONFLICT, ranked,
                           f"{','.join(f['identifier_match_schemes'])} matches {top.canonical_key} but "
                           f"{','.join(f['identifier_conflict_schemes'])} disagrees", top)
        type_note = None
        if not f["type_compatible"]:
            if "abn" in f["identifier_match_schemes"] and _soft_type_hint(ref_info):
                # R1c exception: the source states the ABN; its party type is only a hint.
                type_note = (f"party type hint {hint} ({ref_info.get('party_type_basis')}) disagrees with "
                             f"the ABN holder's type {f.get('candidate_party_type')}; the stated ABN wins")
            else:
                return abstain(AbstainReason.PARTY_TYPE_CONFLICT, ranked, top.veto or "party type conflict", top)
        if f["candidate_quarantined"]:
            return abstain(AbstainReason.QUARANTINED_TARGET, ranked,
                           f"identifier resolves to quarantined party {top.canonical_key}", top)
        # Name candidates (vetoed or not) that alone would clear the threshold for another party,
        # and licence matches that point elsewhere, are disagreements.
        rivals = [r for r in ranked if r.canonical_key != top.canonical_key
                  and (r.name_pass or (r.features["identifier_match"] and not licence_only))]
        disagreement = None
        if rivals:
            parts = [f"{r.canonical_key} via {r.match_type} {r.score}" + (f" (vetoed: {r.veto})" if r.veto else "")
                     for r in rivals[:5]]
            disagreement = f"identifier says {top.canonical_key}; other evidence says " + "; ".join(parts)
        if licence_only and rivals:
            return abstain(AbstainReason.IDENTIFIER_CONFLICT, ranked,
                           f"licence number names {top.canonical_key} (licences transfer) but {disagreement}", top)
        if strict and rivals:
            return abstain(AbstainReason.IDENTIFIER_CONFLICT, ranked, f"strict source: {disagreement}", top)
        conf = policy.licence_confidence if licence_only else 1.0
        if conf < threshold:
            return abstain(AbstainReason.BELOW_THRESHOLD, ranked,
                           f"{top.match_type} confidence {conf} < threshold {threshold}", top)
        why = f"{top.match_type}: {','.join(f['identifier_match_schemes'])} equal, no identifier disagrees"
        if disagreement:
            why += "; identifier wins over the name path"
        if type_note:
            disagreement = f"{disagreement}; {type_note}" if disagreement else type_note
            why += "; " + type_note
        ev = Evidence(top.features, "exact", top.found_by, top.query_text, top.scores, why, threshold,
                      None, disagreement)
        return Link(source, record_id, ranked, why, canonical_key=top.canonical_key,
                    match_type=MatchType(top.match_type), confidence=conf, evidence=ev)

    # R2 / R3: a veto is the abstain reason only when it blocked a candidate that would
    # otherwise have cleared the threshold; a vetoed weak candidate is just a weak candidate.
    if blocked:
        blocked.sort(key=lambda b: (-b[0].score, b[0].canonical_key))
        b, kind = blocked[0]
        return abstain(kind, ranked, f"{b.canonical_key} ({b.match_type} {b.score}) blocked: {b.veto}", b)
    eligible = [r for r in ranked if r.eligible]
    if reused_former_names and not any(r.features["name_exact"] and r.score >= threshold
                                       for r in eligible):
        best = max(reused_former_names, key=lambda r: r.score)
        return abstain(AbstainReason.AMBIGUOUS, ranked, best.veto or "reused former name", best)
    # R4 / R5
    if not eligible:
        best = ranked[0]
        return abstain(AbstainReason.BELOW_THRESHOLD, ranked, f"no eligible candidate: {best.veto}", best)
    top = eligible[0]
    # R8
    if top.score < threshold:
        return abstain(AbstainReason.BELOW_THRESHOLD, ranked,
                       f"best {top.match_type} score {top.score} < threshold {threshold}", top)
    # R9
    if top.features["candidate_quarantined"]:
        return abstain(AbstainReason.QUARANTINED_TARGET, ranked,
                       f"best candidate {top.canonical_key} is quarantined", top)
    # R10
    second = next((r for r in eligible[1:] if r.canonical_key != top.canonical_key), None)
    margin = policy.margin(source)
    gap = round(top.score - second.score, 4) if second is not None else None
    if second is not None and (gap < margin or gap == 0):
        return abstain(AbstainReason.AMBIGUOUS, ranked,
                       f"top {top.canonical_key} {top.score} vs {second.canonical_key} {second.score}: "
                       f"margin {round(top.score - second.score, 4)} < {margin}", top)
    # R11
    why = f"{top.match_type} score {top.score} >= {threshold}"
    if second is not None:
        why += f", margin {round(top.score - second.score, 4)} over {second.canonical_key}"
    runner = {"canonical_key": second.canonical_key, "score": second.score} if second else None
    ev = Evidence(top.features, top.path, top.found_by, top.query_text, top.scores, why, threshold, runner)
    return Link(source, record_id, ranked, why, canonical_key=top.canonical_key,
                match_type=MatchType(top.match_type), confidence=top.score, evidence=ev)
