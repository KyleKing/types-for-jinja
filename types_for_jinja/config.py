"""Load project configuration for types-for-jinja from ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from types_for_jinja.suppress import STYLES


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


DEFAULT_OUT_DIR = '_jinja_stubs'
"""Where generated stubs go. Must not start with a dot, which pyright excludes by default."""

DEFAULT_TEMPLATE_GLOBS = ('*.html', '*.jinja', '*.j2')
"""Filename patterns a directory argument is searched for, recursively."""

EXTENSIONS: dict[str, tuple[str, ...]] = {
    'debug': (),
    'do': (),
    'i18n': ('_', 'gettext', 'ngettext', 'npgettext', 'pgettext'),
    'loopcontrols': (),
}
"""The extensions that may be declared, and the globals each one injects.

Only jinja2's own, by short name. A project-defined extension would mean importing project
code into the parsing Environment, which crosses the static-only line, and a custom tag's
meaning is not inferable from its parser hook anyway.
"""


@dataclass(frozen=True)
class Config:
    """Project-level context shared by every template (Jinja Environment globals).

    ``out_dir`` is read by both ``generate`` and the language server, which have to agree:
    the server writes the live buffer's stub where the project's own checker is already
    looking.
    """

    extensions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    globals: list[tuple[str, str]] = field(default_factory=list)
    language_server: str = ''
    out_dir: str = DEFAULT_OUT_DIR
    suppression: str = 'portable'
    template_dirs: list[str] = field(default_factory=list)
    template_globs: list[str] = field(default_factory=lambda: list(DEFAULT_TEMPLATE_GLOBS))
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
        extensions=_extensions(table.get('extensions', [])),
        imports=list(table.get('imports', [])),
        globals=[(name, type_str) for name, type_str in declared.items()],
        language_server=str(table.get('language_server', '')),
        out_dir=_out_dir(table.get('out_dir', DEFAULT_OUT_DIR)),
        suppression=_suppression(table.get('suppression', 'portable')),
        template_dirs=list(table.get('template_dirs', [])),
        template_globs=list(table.get('template_globs', DEFAULT_TEMPLATE_GLOBS)),
        wrapper=WrapperConfig(**_known(WrapperConfig, table.get('wrapper', {}))),
        syntax=Syntax(**_known(Syntax, table.get('syntax', {}))),
    )


def _extensions(values: list[str]) -> list[str]:
    """Reject an extension this project cannot load, naming the ones it can.

    Accepting a name silently would leave the template failing to parse with no hint that the
    declaration was the problem.
    """
    unknown = [value for value in values if value not in EXTENSIONS]
    if unknown:
        known = ', '.join(sorted(EXTENSIONS))
        msg = f'unknown extensions {unknown}; expected any of {known}'
        raise ValueError(msg)
    return list(values)


def _out_dir(value: str) -> str:
    """Reject an output directory a checker would silently skip or cannot import as a package.

    pyright excludes ``**/.*`` by default and would report a clean run over zero files, and
    the generated stubs import each other relatively, which needs every path segment to be a
    usable module name.
    """
    parts = Path(value).parts
    if not parts or any(not part.isidentifier() for part in parts):
        msg = f'out_dir {value!r} must be a relative path whose every segment is a Python identifier'
        raise ValueError(msg)
    return value


def _suppression(value: str) -> str:
    """Reject an unknown checker name loudly; a silent fallback would emit ignores nothing honours."""
    if value not in STYLES:
        known = ', '.join(sorted(STYLES))
        msg = f'unknown suppression style {value!r}; expected one of {known}'
        raise ValueError(msg)
    return value


def _known(cls: Any, table: dict[str, str]) -> dict[str, str]:
    """Keep only the keys ``cls`` declares, so an unrecognised setting is ignored, not fatal."""
    names = {field_.name for field_ in fields(cls)}
    return {key: value for key, value in table.items() if key in names}
