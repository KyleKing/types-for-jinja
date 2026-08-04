"""Lay out a transpiled stub so generated line N is template line N.

A line-aligned stub needs no marker remapping, so a user's own type checker reports
template errors at the right line with no wrapper process in between. Not every template
has an aligned form: Python forbids a compound statement as the inline body of another,
so a template packing nested blocks onto one physical line cannot be aligned. ``layout``
returns ``None`` for those and the caller falls back to marker-based output.

The aligned stub is emitted at module level rather than inside ``_render``, which frees
the indent level the template's own top level needs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from types_for_jinja.transpile import Line

if TYPE_CHECKING:
    from types_for_jinja.header import TemplateHeader
    from types_for_jinja.transpile import GeneratedModule

_LOOP_BINDING = 'loop = _tj_loop'
_SCAFFOLD = (
    'from typing import Any as _TJAny, cast as _tj_cast',
    '_tj_any = _tj_cast(_TJAny, 0)',
    'loop = _tj_any',
)
_RENDER_DEF = 'def _render('


class LayoutError(Exception):
    """The emitted statements have no line-aligned Python form."""


@dataclass(frozen=True)
class AlignedModule:
    """A line-aligned stub plus the sidecar holding definitions from other templates."""

    code: str
    sidecar: str


def layout(module: GeneratedModule, header: TemplateHeader, sidecar_name: str) -> AlignedModule | None:
    """Align ``module`` to its template's lines, or return ``None`` if it has no aligned form."""
    try:
        return _layout(module, header, sidecar_name)
    except LayoutError:
        return None


def _layout(module: GeneratedModule, header: TemplateHeader, sidecar_name: str) -> AlignedModule:
    preamble = module.lines[: module.preamble_len]
    rest = _unwrap_render(module.lines[module.preamble_len :])
    foreign = [line for line in rest if line.foreign]
    local = [line for line in rest if not line.foreign]
    body = _fill_empty_suites(_demote_empty_blocks(_relocate_else(_drop_loop_bindings(local))))
    _reject_unplaceable(body, header.lineno)
    buckets = _bucket(body)
    imports = [Line(0, f'from {sidecar_name} import *  # noqa: F403', header.lineno)] if foreign else []
    buckets[header.lineno] = [
        *_flatten_preamble(preamble, header),
        *imports,
        *buckets.get(header.lineno, []),
    ]
    code = '\n'.join(_physical_line(buckets.get(lineno, [])) for lineno in range(1, max(buckets) + 1)) + '\n'
    return AlignedModule(code=code, sidecar=_sidecar(preamble, foreign))


def _sidecar(preamble: list[Line], foreign: list[Line]) -> str:
    if not foreign:
        return ''
    body = [*preamble, *(replace(line, indent=max(line.indent - 1, 0)) for line in foreign)]
    return '\n'.join('    ' * line.indent + line.text for line in body) + '\n'


def _unwrap_render(body: list[Line]) -> list[Line]:
    """Drop the ``_render`` wrapper and pull its body out to module level.

    The wrapper's placeholder ``pass`` goes with it: module level needs no filler, and
    it carries the header's line number, which would sort behind any macro defined above.
    """
    for index, line in enumerate(body):
        if line.text.startswith(_RENDER_DEF):
            inner = body[index + 1 :]
            if inner and inner[0].text == 'pass':
                inner = inner[1:]
            return [*body[:index], *(replace(nxt, indent=nxt.indent - 1) for nxt in inner)]
    return body


def _drop_loop_bindings(body: list[Line]) -> list[Line]:
    """Hoisting ``loop`` to the preamble frees a for-body's first line for real statements."""
    return [line for line in body if line.text != _LOOP_BINDING]


def _flatten_preamble(preamble: list[Line], header: TemplateHeader) -> list[Line]:
    """Collapse the preamble onto the header's own line as ``;``-joined simple statements.

    Every declared name is bound to a value, not merely annotated. A module-level bare
    annotation leaves the name unbound, which buries the template's real errors under
    ``"user" is unbound`` on every use.
    """
    texts = [line.text for line in preamble if _is_import(line.text) and 'as _TJAny' not in line.text]
    texts.extend(_SCAFFOLD)
    texts.extend(_bind(line.text) for line in preamble if not _is_import(line.text) and not _is_scaffold(line.text))
    texts.extend(_bind(f'{name}: {type_str}') for name, type_str in header.params)
    return [Line(0, text, header.lineno) for text in texts]


def _is_import(text: str) -> bool:
    return text.startswith(('import ', 'from '))


def _is_scaffold(text: str) -> bool:
    return text.startswith(('def _tj_any', '_tj_loop'))


def _bind(text: str) -> str:
    return f'{text} = _tj_any'


def _relocate_else(body: list[Line]) -> list[Line]:
    """Jinja records no line for ``{% else %}``, so place it on the line before its branch."""
    out: list[Line] = []
    for index, line in enumerate(body):
        if line.text != 'else:':
            out.append(line)
            continue
        branch = [nxt for nxt in body[index + 1 :] if nxt.indent > line.indent]
        if not branch:
            continue
        target = branch[0].lineno - 1
        if out and target <= out[-1].lineno:
            raise LayoutError('no free line for else')
        out.append(replace(line, lineno=target))
    return out


def _demote_empty_blocks(body: list[Line]) -> list[Line]:
    """Rewrite a block with nothing to check inside it as a bare check of its own expression.

    ``{% if x %}{% endif %}`` only needs ``x`` validated, and a simple statement shares a
    physical line where a second compound statement could not.
    """
    out = list(body)
    changed = True
    while changed:
        changed = False
        for index in range(len(out) - 1, -1, -1):
            demoted = _demote_at(out, index)
            if demoted is not None:
                out = demoted
                changed = True
    return out


def _demote_at(body: list[Line], index: int) -> list[Line] | None:
    line = body[index]
    following = body[index + 1] if index + 1 < len(body) else None
    after = body[index + 2] if index + 2 < len(body) else None
    if not line.text.endswith(':') or line.text.startswith('def '):
        return None
    if following is None or following.text != 'pass' or following.indent != line.indent + 1:
        return None
    if after is not None and after.indent > line.indent:
        return None
    expr = _block_expression(line.text)
    replacement = [] if expr is None else [Line(line.indent, f'_ = {expr}', line.lineno)]
    return [*body[:index], *replacement, *body[index + 2 :]]


def _block_expression(text: str) -> str | None:
    inner = text.removesuffix(':')
    for prefix in ('if ', 'elif '):
        if inner.startswith(prefix):
            expr = inner.removeprefix(prefix)
            return None if expr == 'True' else expr
    if inner.startswith('for ') and ' in ' in inner:
        return inner.split(' in ', 1)[1]
    return None


def _fill_empty_suites(body: list[Line]) -> list[Line]:
    """Give a block whose only statement was the dropped ``loop`` binding an inline ``pass``."""
    out: list[Line] = []
    for index, line in enumerate(body):
        out.append(line)
        following = body[index + 1] if index + 1 < len(body) else None
        if line.text.endswith(':') and (following is None or following.indent <= line.indent):
            out.append(Line(line.indent + 1, 'pass', line.lineno))
    return out


def _reject_unplaceable(body: list[Line], header_line: int) -> None:
    if any(line.lineno < header_line for line in body):
        raise LayoutError('statement precedes the type header')
    linenos = [line.lineno for line in body]
    if linenos != sorted(linenos):
        raise LayoutError('statements are emitted out of template order')


def _bucket(body: list[Line]) -> dict[int, list[Line]]:
    buckets: dict[int, list[Line]] = defaultdict(list)
    for line in body:
        buckets[line.lineno].append(line)
    return buckets


def _physical_line(group: list[Line]) -> str:
    if not group:
        return ''
    head, rest = group[0], group[1:]
    prefix = '    ' * head.indent
    if not rest:
        return f'{prefix}{head.text}'
    if any(line.text.endswith(':') for line in rest):
        raise LayoutError('two compound statements share one template line')
    if head.text.endswith(':'):
        if any(line.indent != head.indent + 1 for line in rest):
            raise LayoutError('inline body is not a single suite')
        return f'{prefix}{head.text} ' + '; '.join(line.text for line in rest)
    if any(line.indent != head.indent for line in rest):
        raise LayoutError('mixed indentation on one template line')
    return prefix + '; '.join(line.text for line in group)
