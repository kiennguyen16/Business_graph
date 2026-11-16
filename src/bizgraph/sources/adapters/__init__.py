"""Concrete source adapters. Importing this package registers them in `registry`."""

from bizgraph.sources.adapters import tier1  # noqa: F401  (registration side effect)
from bizgraph.sources.adapters.tier1 import AbrAdapter, AsicCompanyAdapter

try:  # Tier 2 adapters are developed separately; tolerate their absence.
    from bizgraph.sources.adapters import tier2  # noqa: F401
except ImportError:  # pragma: no cover
    tier2 = None

try:  # Tier 3 (ACCC infringement notices); tolerate its absence.
    from bizgraph.sources.adapters import tier3  # noqa: F401
except ImportError:  # pragma: no cover
    tier3 = None

__all__ = ["AbrAdapter", "AsicCompanyAdapter"]
