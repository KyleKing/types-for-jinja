"""Load project configuration for types-for-jinja from ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


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
class Syntax:
    """Jinja's delimiters, which a superset is free to change.

    Field names match ``jinja2.Environment``'s own keyword arguments, so a project that
    already configures its Environment can copy the values across unchanged.
    """

    block_start_string: str = '{%'
    block_end_string: str = '%}'
    variable_start_string: str = '{{'
    variable_end_string: str = '}}'
    comment_start_string: str = '{#'
    comment_end_string: str = '#}'
    line_statement_prefix: str | None = None
    line_comment_prefix: str | None = None


@dataclass(frozen=True)
class Config:
    """Project-level context shared by every template (Jinja Environment globals)."""

    imports: list[str] = field(default_factory=list)
    globals: list[tuple[str, str]] = field(default_factory=list)
    template_dirs: list[str] = field(default_factory=list)
    wrapper: WrapperConfig = field(default_factory=WrapperConfig)
    syntax: Syntax = field(default_factory=Syntax)


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
        wrapper=WrapperConfig(**_known(WrapperConfig, table.get('wrapper', {}))),
        syntax=Syntax(**_known(Syntax, table.get('syntax', {}))),
    )


def _known(cls: Any, table: dict[str, str]) -> dict[str, str]:
    """Keep only the keys ``cls`` declares, so an unrecognised setting is ignored, not fatal."""
    names = {field_.name for field_ in fields(cls)}
    return {key: value for key, value in table.items() if key in names}
