"""Registry of source adapters: the extension point for new sources."""

from __future__ import annotations

from bizgraph.sources.base import SourceAdapter


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[SourceAdapter]] = {}

    def register(self, adapter_cls: type[SourceAdapter]) -> type[SourceAdapter]:
        """Usable as a class decorator."""
        if adapter_cls.source_id in self._adapters:
            raise ValueError(f"duplicate source_id {adapter_cls.source_id!r}")
        self._adapters[adapter_cls.source_id] = adapter_cls
        return adapter_cls

    def get(self, source_id: str) -> SourceAdapter:
        try:
            return self._adapters[source_id]()
        except KeyError:
            known = ", ".join(sorted(self._adapters)) or "none"
            raise KeyError(f"unknown source {source_id!r}; registered: {known}") from None

    def all(self) -> list[type[SourceAdapter]]:
        return sorted(self._adapters.values(), key=lambda a: (a.tier, a.source_id))


registry = SourceRegistry()
