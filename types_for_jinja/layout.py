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

from types_for_jinja.header import TemplateHeader
from types_for_jinja.transpile import GeneratedModule, Line

_LOOP_BINDING = 'loop = _tj_loop'
_SCAFFOLD = (
    'from typing import Any as _TJAny, cast as _tj_cast',
    '_tj_any = _tj_cast(_TJAny, 0)',
    'loop = _tj_any',
    '_tj_default = _tj_any',
)
_SCAFFOLD_PREFIXES = ('def _tj_any', '_tj_loop', '_tj_default')
_RENDER_DEF = 'def _render('


class LayoutError(Exception):
    """The emitted statements have no line-aligned Python form."""


@dataclass(frozen=True)
class AlignedModule:
    """A line-aligned stub plus the sidecar holding definitions from other templates.

    ``sidecar_line`` is the template line the whole sidecar is attributed to, which is the
    ``{% extends %}`` or ``{% include %}`` tag that pulled the other file in. A sidecar cannot
    be line-aligned, because its statements come from a file with different line numbers, so
    the local tag is the only position in this template that means anything.
    """

    code: str
    sidecar: str
    sidecar_line: int = 1


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
    body = _drop_loop_bindings(local)
    for transform in (_collapse_inline_conditionals, _relocate_else, _demote_empty_blocks, _fill_empty_suites):
        body = transform(body)
    _reject_unplaceable(body, header.lineno)
    buckets = _bucket(body)
    imports = [Line(0, f'from {sidecar_name} import *  # noqa: F403', header.lineno)] if foreign else []
    buckets[header.lineno] = [
        *_flatten_preamble(preamble, header),
        *imports,
        *buckets.get(header.lineno, []),
    ]
    code = '\n'.join(_physical_line(buckets.get(lineno, [])) for lineno in range(1, max(buckets) + 1)) + '\n'
    return AlignedModule(
        code=code,
        sidecar=_sidecar(preamble, foreign, header),
        sidecar_line=min((line.lineno for line in foreign), default=header.lineno),
    )


def _sidecar(preamble: list[Line], foreign: list[Line], header: TemplateHeader) -> str:
    """Emit the definitions another template contributed, over a fully bound preamble.

    The sidecar needs the same bound names the aligned stub has. A bare annotation would
    leave every global unbound and every header parameter undefined, so the real errors
    from the other template would be buried.

    A sidecar always sits at the root of the output tree even when its stub is nested, so its
    inherited relative imports are re-pointed to that depth.
    """
    if not foreign:
        return ''
    body = [
        *(replace(line, text=_at_root(line.text)) for line in _flatten_preamble(preamble, header)),
        *(replace(line, indent=max(line.indent - 1, 0)) for line in foreign),
    ]
    return '\n'.join('    ' * line.indent + line.text for line in body) + '\n'


def _at_root(text: str) -> str:
    """Rewrite a generated relative import for a module living at the output root."""
    if not text.startswith('from .'):
        return text
    return f'from .{text[len("from ") :].lstrip(".")}'


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
    """Preamble lines the aligned form replaces with its own bound equivalents in ``_SCAFFOLD``.

    Binding one of these again would produce a second assignment on an already-assigned
    statement, which is not valid Python.
    """
    return text.startswith(_SCAFFOLD_PREFIXES)


def _bind(text: str) -> str:
    return f'{text} = _tj_any'


def _collapse_inline_conditionals(body: list[Line]) -> list[Line]:
    """Rewrite an ``if``/``else`` packed onto one template line as a conditional expression.

    Python forbids two compound statements on one physical line, so
    ``{% if a %}{{ x }}{% else %}{{ y }}{% endif %}`` has no aligned form as a statement.
    ``_ = (x if a else y)`` checks both branches under the same narrowing and fits on the
    single line the template used.
    """
    out = list(body)
    changed = True
    while changed:
        changed = False
        for index in range(len(out) - 1, -1, -1):
            collapsed = _collapse_at(out, index)
            if collapsed is not None:
                out = collapsed
                changed = True
    return out


def _collapse_at(body: list[Line], index: int) -> list[Line] | None:
    group = body[index : index + 4]
    if len(group) < 4:  # noqa: PLR2004
        return None
    head, then, alt, other = group
    tail = body[index + 4] if index + 4 < len(body) else None
    shaped = (
        alt.text == 'else:'
        and alt.indent == head.indent
        and then.indent == head.indent + 1
        and other.indent == head.indent + 1
        and {line.lineno for line in group} == {head.lineno}
        and (tail is None or tail.indent <= head.indent)
    )
    condition = _if_condition(head.text)
    left, right = _checked_expression(then.text), _checked_expression(other.text)
    if not (shaped and condition and left and right):
        return None
    collapsed = Line(head.indent, f'_ = ({left} if {condition} else {right})', head.lineno)
    return [*body[:index], collapsed, *body[index + 4 :]]


def _if_condition(text: str) -> str | None:
    return text.removeprefix('if ').removesuffix(':') if text.startswith('if ') and text.endswith(':') else None


def _checked_expression(text: str) -> str | None:
    """The expression a bare ``_ = <expr>`` check evaluates, or ``None`` for anything else."""
    return text.removeprefix('_ = ') if text.startswith('_ = ') and ';' not in text else None


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
