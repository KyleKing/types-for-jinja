"""Locate templates referenced by ``extends`` / ``include`` / ``import`` / ``from import``.

Resolution stays deliberately strict. When a reference cannot be located under the
known search directories, the resolver returns ``None`` so the caller skips that
construct rather than guessing (the dbt-extractor "certain or bail" posture).

A search directory may be a plain path or a ``package:subdirectory`` reference, which
covers templates shipped inside an installed package the way ``jinja2.PackageLoader``
loads them. Only the top-level package is looked up, so nothing in the project is
imported to answer the question.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def search_paths(template_dirs: list[str]) -> list[Path]:
    """Turn configured search directories into real paths, dropping any that do not exist."""
    resolved = (_package_path(entry) if ':' in entry else Path(entry) for entry in template_dirs)
    return [path for path in resolved if path is not None and path.is_dir()]


def _package_path(entry: str) -> Path | None:
    package, _, subdirectory = entry.partition(':')
    try:
        spec = importlib.util.find_spec(package.split('.', 1)[0])
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).parent.joinpath(*package.split('.')[1:], subdirectory)


def resolve_template(ref: str, search_dirs: list[Path]) -> tuple[Path, str] | None:
    """Return ``(path, source)`` for ``ref`` under ``search_dirs``, or ``None`` if unresolved."""
    for base in search_dirs:
        candidate = base / ref
        if candidate.is_file():
            return candidate, candidate.read_text(encoding='utf-8')
    return None
