"""Locate templates referenced by ``extends`` / ``import`` / ``from import``.

Resolution stays deliberately strict. When a reference cannot be located under the
known search directories, the resolver returns ``None`` so the caller skips that
construct rather than guessing (the dbt-extractor "certain or bail" posture).
"""

from __future__ import annotations

from pathlib import Path


def resolve_template(ref: str, search_dirs: list[Path]) -> tuple[Path, str] | None:
    """Return ``(path, source)`` for ``ref`` under ``search_dirs``, or ``None`` if unresolved."""
    for base in search_dirs:
        candidate = base / ref
        if candidate.is_file():
            return candidate, candidate.read_text(encoding='utf-8')
    return None
