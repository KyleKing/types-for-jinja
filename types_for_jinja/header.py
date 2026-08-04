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
class Param:
    """One declared context name, with its annotation and default when the header gives them.

    ``annotation`` is ``None`` for a bare name, which JinjaX allows. Each emitter picks its own
    stand-in, because a generated stub and a generated wrapper spell ``Any`` differently.
    """

    name: str
    annotation: str | None = None
    default: str | None = None

    def annotated(self, fallback: str) -> str:
        """``name: annotation``, falling back to ``fallback`` for an untyped name."""
        return f'{self.name}: {self.annotation or fallback}'


@dataclass(frozen=True)
class TemplateHeader:
    """The typed context a template declares via its ``{#def ... #}`` comment."""

    imports: list[str]
    params: list[Param]
    lineno: int
    malformed: str | None = None
    """Why the parameter list could not be read, when it could not."""


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
    declarations: list[str] = []
    for raw in match.group('body').splitlines():
        line = raw.strip().rstrip(',')
        if not line:
            continue
        if line.startswith(('import ', 'from ')):
            imports.append(line)
        else:
            declarations.append(line)
    params, malformed = _parse_params(', '.join(declarations))
    return TemplateHeader(
        imports=imports,
        params=params,
        lineno=source.count('\n', 0, match.start()) + 1,
        malformed=malformed,
    )


def _parse_params(text: str) -> tuple[list[Param], str | None]:
    """Read the declarations as a Python parameter list, which is exactly what they are.

    Handing the text to Python's own parser is what makes the two spellings one case: a
    declaration per line, as this project's docs show, and the comma-separated one-liner with
    defaults and untyped names that JinjaX writes. Anything Python would reject is reported
    rather than half-read.
    """
    if not text:
        return [], None
    try:
        tree = ast.parse(f'def _tj({text}): pass')
    except SyntaxError:
        return [], f'malformed {{#def #}} header: {text!r} is not a valid parameter list'
    function = tree.body[0]
    if not isinstance(function, ast.FunctionDef):  # pragma: no cover
        return [], f'malformed {{#def #}} header: {text!r}'
    return _params_of(function.args), None


def _params_of(args: ast.arguments) -> list[Param]:
    """Flatten Python's argument groups, keeping each name paired with its own default."""
    positional = [*args.posonlyargs, *args.args]
    padding: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    pairs = list(zip(positional, [*padding, *args.defaults], strict=True))
    pairs.extend(zip(args.kwonlyargs, args.kw_defaults, strict=True))
    return [
        Param(
            name=arg.arg,
            annotation=ast.unparse(arg.annotation) if arg.annotation is not None else None,
            default=ast.unparse(default) if default is not None else None,
        )
        for arg, default in pairs
    ]


def header_errors(header: TemplateHeader) -> list[str]:
    """Return messages for header entries that are not valid Python, empty when the header is sound.

    A formatter that collapses the header onto one line produces text that still matches the
    comment pattern but no longer parses as a declaration list, which this catches.
    """
    messages = [
        f'malformed import in {{#def #}} header: {statement!r} (one import per line)'
        for statement in header.imports
        if not _parses(statement)
    ]
    if header.malformed is not None:
        messages.append(header.malformed)
    return messages


def _parses(source: str, mode: str = 'exec') -> bool:
    try:
        ast.parse(source, mode=mode)
    except SyntaxError:
        return False
    return True
