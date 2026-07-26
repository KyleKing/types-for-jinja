"""Context types for the yak-shears real-world example templates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YakInfo:
    """One yak card rendered by yaks_index.html.jinja."""

    path: str
    preview: str
    truncated: bool
    category: str
    tags: list[str]
    word_count: int
    link_count: int
    last_modified: str
