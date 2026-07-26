"""Load project configuration for typed-jinja from ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Project-level context shared by every template (Jinja Environment globals)."""

    imports: list[str] = field(default_factory=list)
    globals: list[tuple[str, str]] = field(default_factory=list)
    template_dirs: list[str] = field(default_factory=list)


def load_config(root: Path) -> Config:
    """Read ``[tool.typed_jinja]`` from ``root/pyproject.toml``; empty ``Config`` if absent."""
    pyproject = root / 'pyproject.toml'
    if not pyproject.is_file():
        return Config()
    table = tomllib.loads(pyproject.read_text(encoding='utf-8')).get('tool', {}).get('typed_jinja')
    if not table:
        return Config()
    declared = table.get('globals', {})
    return Config(
        imports=list(table.get('imports', [])),
        globals=[(name, type_str) for name, type_str in declared.items()],
        template_dirs=list(table.get('template_dirs', [])),
    )
