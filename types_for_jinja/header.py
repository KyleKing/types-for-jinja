"""Parse ``{#def ... #}`` type declarations from a Jinja template.

The first one is the template's own context header. A later one inside a
``{% macro %}`` body types that macro's parameters.

The patterns are built from the project's configured delimiters, so a Jinja superset
that changes them still gets its headers read.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache

from types_for_jinja.config import Syntax


@lru_cache(maxsize=8)
def _patterns(syntax: Syntax) -> tuple[re.Pattern[str], re.Pattern[str]]:
    open_c, close_c = re.escape(syntax.comment_start_string), re.escape(syntax.comment_end_string)
    open_b = re.escape(syntax.block_start_string)
    return (
        re.compile(rf'{open_c}-?\s*def\b(?P<body>.*?)-?{close_c}', re.DOTALL),
        re.compile(rf'{open_b}-?\s*macro\b'),
    )


@dataclass(frozen=True)
class TemplateHeader:
    """The typed context a template declares via its ``{#def ... #}`` comment."""

    imports: list[str]
    params: list[tuple[str, str]]
    lineno: int


def parse_header(source: str, syntax: Syntax | None = None) -> TemplateHeader | None:
    """Return the template's own ``{#def ... #}`` header, or ``None`` if it has none.

    A block that follows the first ``{% macro %}`` types that macro's parameters, not the
    template, so a macros-only file reports no header rather than borrowing one.
    """
    header_re, macro_re = _patterns(syntax or Syntax())
    match = header_re.search(source)
    if match is None:
        return None
    macro = macro_re.search(source)
    if macro is not None and macro.start() < match.start():
        return None
    return _parse_block(match, source)


def parse_defs(source: str, syntax: Syntax | None = None) -> list[TemplateHeader]:
    """Return every ``{#def ... #}`` declaration in ``source``, in source order."""
    header_re, _ = _patterns(syntax or Syntax())
    return [_parse_block(match, source) for match in header_re.finditer(source)]


def _parse_block(match: re.Match[str], source: str) -> TemplateHeader:
    imports: list[str] = []
    params: list[tuple[str, str]] = []
    for raw in match.group('body').splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(('import ', 'from ')):
            imports.append(line)
        elif ':' in line:
            name, type_str = line.split(':', 1)
            params.append((name.strip(), type_str.strip()))
    return TemplateHeader(imports=imports, params=params, lineno=source.count('\n', 0, match.start()) + 1)


def header_errors(header: TemplateHeader) -> list[str]:
    """Return messages for header entries that are not valid Python, empty when the header is sound.

    Each declaration occupies its own line. A formatter that joins them produces text that
    still matches the header pattern but no longer parses, which this catches.
    """
    messages = [
        f'malformed import in {{#def #}} header: {statement!r} (one declaration per line)'
        for statement in header.imports
        if not _parses(statement)
    ]
    messages.extend(
        f'malformed parameter in {{#def #}} header: {name!r} is not an identifier (one declaration per line)'
        for name, _ in header.params
        if not name.isidentifier()
    )
    messages.extend(
        f'malformed annotation in {{#def #}} header for {name!r}: {annotation!r}'
        for name, annotation in header.params
        if name.isidentifier() and not _parses(annotation, mode='eval')
    )
    return messages


def _parses(source: str, mode: str = 'exec') -> bool:
    try:
        ast.parse(source, mode=mode)
    except SyntaxError:
        return False
    return True
