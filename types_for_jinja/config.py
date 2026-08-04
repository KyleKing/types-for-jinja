"""Load project configuration for types-for-jinja from ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class WrapperConfig:
    """How ``types-for-jinja wrapper`` shapes the typed render functions it generates.

    ``return_type`` is called on the rendered string, so a framework response class
    (``HTMLResponse``) drops in where ``Markup`` sits by default. ``env_import`` must bind
    the project's Jinja Environment to ``_env``; without it the module declares
    ``_env: Environment`` for the caller to assign.
    """

    env_import: str | None = None
    out_dir: str = '_jinja_wrappers'
    return_import: str = 'from markupsafe import Markup'
    return_type: str = 'Markup'
    validator: str = 'none'


@dataclass(frozen=True)
class Config:
    """Project-level context shared by every template (Jinja Environment globals)."""

    imports: list[str] = field(default_factory=list)
    globals: list[tuple[str, str]] = field(default_factory=list)
    template_dirs: list[str] = field(default_factory=list)
    wrapper: WrapperConfig = field(default_factory=WrapperConfig)


def load_config(root: Path) -> Config:
    """Read ``[tool.types_for_jinja]`` from ``root/pyproject.toml``; empty ``Config`` if absent."""
    pyproject = root / 'pyproject.toml'
    if not pyproject.is_file():
        return Config()
    table = tomllib.loads(pyproject.read_text(encoding='utf-8')).get('tool', {}).get('types_for_jinja')
    if not table:
        return Config()
    declared = table.get('globals', {})
    return Config(
        imports=list(table.get('imports', [])),
        globals=[(name, type_str) for name, type_str in declared.items()],
        template_dirs=list(table.get('template_dirs', [])),
        wrapper=_wrapper_config(table.get('wrapper', {})),
    )


def _wrapper_config(table: dict[str, str]) -> WrapperConfig:
    known = {field_.name for field_ in fields(WrapperConfig)}
    return WrapperConfig(**{key: value for key, value in table.items() if key in known})
