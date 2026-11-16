"""Entity resolution (ARCHITECTURE 3.5).

Exact path (identifier joins, unique normalised name) and semantic path (fuzzy and
optional embedding similarity over blocked candidates) are separate named paths;
`decision.arbitrate` is the documented rule that decides between them.
"""

from bizgraph.resolution.candidates import (
    Blocker,
    BlockingGenerator,
    CandidateGenerator,
    EmbeddingBlocker,
    ExactIdentifierGenerator,
    FtsBlocker,
    GeneratedCandidate,
    NameIndex,
    TokenStateBlocker,
)
from bizgraph.resolution.decision import (
    Abstention,
    Decision,
    Evidence,
    ExactScorer,
    FuzzyScorer,
    Link,
    RankedCandidate,
    Scorer,
    SemanticScorer,
    StoredCandidate,
    ThresholdPolicy,
    arbitrate,
)
from bizgraph.resolution.features import Embedder, FeatureExtractor, FeatureVector, PartyView
from bizgraph.resolution.matcher import Matcher, MatcherVersion, RunSummary, code_hash
from bizgraph.resolution.reference import Reference, ReferenceParser

__all__ = [
    "Abstention",
    "Blocker",
    "BlockingGenerator",
    "CandidateGenerator",
    "Decision",
    "EmbeddingBlocker",
    "Embedder",
    "Evidence",
    "ExactIdentifierGenerator",
    "ExactScorer",
    "FeatureExtractor",
    "FeatureVector",
    "FtsBlocker",
    "FuzzyScorer",
    "GeneratedCandidate",
    "Link",
    "Matcher",
    "MatcherVersion",
    "NameIndex",
    "PartyView",
    "RankedCandidate",
    "Reference",
    "ReferenceParser",
    "RunSummary",
    "Scorer",
    "SemanticScorer",
    "StoredCandidate",
    "ThresholdPolicy",
    "TokenStateBlocker",
    "arbitrate",
    "code_hash",
]
