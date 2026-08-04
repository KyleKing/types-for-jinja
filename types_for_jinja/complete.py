"""Resolve the names a template's typed context makes available at a cursor position.

The header declares parameters, ``[tool.types_for_jinja]`` declares Environment globals,
and the template itself binds more names through ``{% for %}``, ``{% set %}``,
``{% with %}``, ``{% macro %}``, and ``{% import %}``. This module walks the Jinja AST
and reports which of those are visible on a given line, so the LSP can offer them as
completions and describe them on hover.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from jinja2 import Environment, TemplateSyntaxError, nodes

from types_for_jinja.config import Config
from types_for_jinja.header import TemplateHeader
from types_for_jinja.transpile import MacroTypes, deepest_line, macro_defs

_IDENT_RUN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*$')
_WORD_AT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_OPENERS = ('{{', '{%', '{#')
_CLOSERS = ('}}', '%}', '#}')
_CLOSING = {'{{': ' }}', '{%': ' %}', '{#': ' #}'}

__all__ = ['ContextName', 'CursorContext', 'context_names', 'cursor_context', 'describe']


@dataclass(frozen=True)
class ContextName:
    """A name the template can reference, and where it came from."""

    name: str
    type_str: str
    origin: str


@dataclass(frozen=True)
class CursorContext:
    """What the cursor is positioned to complete inside a template."""

    in_expression: bool
    attribute_of: str
    prefix: str


def cursor_context(line_text: str, column: int) -> CursorContext:
    """Classify the cursor at zero-based ``column`` of ``line_text``.

    ``attribute_of`` is the dotted expression left of a trailing ``.`` (empty when the
    cursor is completing a bare name). Only ``{{ }}`` and ``{% %}`` count as expressions;
    a ``{# #}`` comment does not.
    """
    head = line_text[:column]
    opener, closer = _last_index(head, _OPENERS), _last_index(head, _CLOSERS)
    if opener is None or (closer is not None and closer > opener) or head[opener : opener + 2] == '{#':
        return CursorContext(in_expression=False, attribute_of='', prefix='')
    match = _IDENT_RUN.search(head)
    prefix = match.group(0) if match else ''
    before = head[: len(head) - len(prefix)]
    return CursorContext(in_expression=True, attribute_of=_dotted_base(before), prefix=prefix)


def context_names(
    source: str,
    header: TemplateHeader,
    config: Config | None = None,
    line: int = 1,
) -> list[ContextName]:
    """Return every name visible on one-based ``line``, sorted by name.

    A buffer being typed into rarely parses, so the template-bound names are best effort:
    when no repair of ``source`` parses, only the header and configured globals come back.
    """
    config = config or Config()
    param_names = {name for name, _ in header.params}
    found = [ContextName(name, type_str, 'parameter') for name, type_str in header.params]
    found.extend(ContextName(name, type_str, 'global') for name, type_str in config.globals if name not in param_names)
    tree = _parse_tolerantly(source, line)
    if tree is not None:
        macro_types, _ = macro_defs(source, tree)
        _scan(tree.body, line, source.count('\n') + 1, found, macro_types)
    return sorted(_deduplicate(found), key=lambda entry: entry.name)


def describe(entry: ContextName) -> str:
    """Render a one-line description of ``entry`` for a hover or completion detail."""
    return f'{entry.name}: {entry.type_str} ({entry.origin})' if entry.type_str else f'{entry.name} ({entry.origin})'


def word_at(line_text: str, column: int) -> str:
    """Return the identifier spanning zero-based ``column``, empty when there is none."""
    for match in _WORD_AT.finditer(line_text):
        if match.start() <= column <= match.end():
            return match.group(0)
    return ''


def _parse_tolerantly(source: str, line: int) -> nodes.Template | None:
    """Parse ``source``, first as written, then with the half-typed line closed, then blanked.

    Blanking rather than deleting keeps every other line at its original number.
    """
    for candidate in (source, _with_line(source, line, _closed), _with_line(source, line, lambda _: '')):
        if candidate is None:
            continue
        try:
            return Environment(autoescape=True).parse(candidate)
        except TemplateSyntaxError:
            continue
    return None


def _with_line(source: str, line: int, repair: Callable[[str], str | None]) -> str | None:
    lines = source.splitlines()
    if not 1 <= line <= len(lines):
        return None
    repaired = repair(lines[line - 1])
    if repaired is None:
        return None
    lines[line - 1] = repaired
    return '\n'.join(lines) + '\n'


def _closed(text: str) -> str | None:
    """Terminate a delimiter left open on ``text``, or ``None`` when none is open."""
    opener = _last_index(text, _OPENERS)
    if opener is None:
        return None
    closer = _last_index(text, _CLOSERS)
    if closer is not None and closer > opener:
        return None
    return text + _CLOSING[text[opener : opener + 2]]


def _last_index(head: str, tokens: tuple[str, ...]) -> int | None:
    found = [index for index in (head.rfind(token) for token in tokens) if index >= 0]
    return max(found) if found else None


def _dotted_base(before: str) -> str:
    if not before.endswith('.'):
        return ''
    base = re.search(r'[A-Za-z_][A-Za-z0-9_.\[\]\'"]*\.$', before)
    return base.group(0)[:-1] if base else ''


def _deduplicate(entries: list[ContextName]) -> list[ContextName]:
    """Keep the last binding of each name, so an inner scope shadows an outer one."""
    return list({entry.name: entry for entry in entries}.values())


def _spans(body: list[nodes.Node], end: int) -> list[tuple[nodes.Node, int]]:
    """Pair each node with the last line it covers.

    Jinja records no line number for a closing tag, so the end is bounded by the next
    sibling and by the node's own deepest line plus one for the ``{% end... %}`` itself.
    """
    starts = [node.lineno for node in body]
    spans = []
    for index, node in enumerate(body):
        sibling_end = (starts[index + 1] - 1) if index + 1 < len(body) else end
        spans.append((node, min(sibling_end, deepest_line(node) + 1)))
    return spans


def _scan(body: list[nodes.Node], line: int, end: int, out: list[ContextName], types: MacroTypes) -> None:
    for node, node_end in _spans(body, end):
        if node.lineno > line:
            return
        contains = line <= node_end
        out.extend(_bindings(node, types, contains=contains))
        if contains:
            _descend(node, line, node_end, out, types)


def _bindings(node: nodes.Node, types: MacroTypes, *, contains: bool) -> list[ContextName]:  # ruff:ignore[too-many-return-statements]
    """Names ``node`` itself introduces; ``contains`` means the cursor is inside its body."""
    match node:
        case nodes.For() if contains:
            targets = [ContextName(name, '', 'loop target') for name in _target_names(node.target)]
            return [*targets, ContextName('loop', '', 'loop helper')]
        case nodes.With() if contains:
            return [ContextName(name, '', 'with target') for target in node.targets for name in _target_names(target)]
        case nodes.Macro():
            declared = types.get(node.lineno, {})
            params = (
                [ContextName(arg.name, declared.get(arg.name, ''), 'macro parameter') for arg in node.args]
                if contains
                else []
            )
            return [ContextName(node.name, '', 'macro'), *params]
        case nodes.Assign() | nodes.AssignBlock():
            return [ContextName(name, '', 'set') for name in _target_names(node.target)]
        case nodes.Import():
            return [ContextName(node.target, '', 'imported macros')]
        case nodes.FromImport():
            return [
                ContextName(entry[1] if isinstance(entry, tuple) else entry, '', 'imported macro')
                for entry in node.names
            ]
        case _:
            return []


def _descend(node: nodes.Node, line: int, end: int, out: list[ContextName], types: MacroTypes) -> None:
    """Recurse into the child bodies of a node that encloses the cursor."""
    match node:
        case nodes.If():
            for branch in [node.body, *(elif_node.body for elif_node in node.elif_), node.else_]:
                _scan(branch, line, end, out, types)
        case nodes.For():
            _scan(node.body, line, end, out, types)
            _scan(node.else_, line, end, out, types)
        case nodes.Block() | nodes.Scope() | nodes.FilterBlock() | nodes.CallBlock() | nodes.Macro() | nodes.With():
            _scan(node.body, line, end, out, types)
        case _:
            return


def _target_names(target: nodes.Node) -> list[str]:
    match target:
        case nodes.Name():
            return [target.name]
        case nodes.Tuple():
            return [name for item in target.items for name in _target_names(item)]
        case _:
            return []
