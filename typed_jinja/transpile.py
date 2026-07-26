"""Transpile a Jinja2 template into a Python type-checking stub.

The stub is never executed. It exercises every expression the template uses so a
type checker (pyright) can validate variable, attribute, and item access against the
declared context. Jinja still renders the template at runtime, unchanged. Each emitted
line carries a ``# L<n>`` marker back to its source line in the template.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jinja2 import Environment, nodes

from typed_jinja.config import Config
from typed_jinja.header import TemplateHeader

_CMP_OPS = {
    'eq': '==',
    'ne': '!=',
    'lt': '<',
    'lteq': '<=',
    'gt': '>',
    'gteq': '>=',
    'in': 'in',
    'notin': 'not in',
}


class _UnsupportedError(Exception):
    """A Jinja node this v1 transpiler does not model as a typed expression."""


@dataclass
class _Line:
    indent: int
    text: str
    lineno: int


@dataclass
class GeneratedModule:
    """A transpiled type-checking stub and the context parameters it declares."""

    code: str
    param_names: list[str] = field(default_factory=list)


def transpile(source: str, header: TemplateHeader, config: Config | None = None) -> GeneratedModule:
    """Transpile ``source`` into a Python stub checkable against ``header``'s context.

    ``config`` supplies project-wide Jinja Environment globals (for example
    ``static_url``) so a template that references them is not flagged as undefined.
    """
    config = config or Config()
    tree = Environment(autoescape=True).parse(source)
    param_names = {name for name, _ in header.params}
    lines: list[_Line] = [_Line(0, imp, header.lineno) for imp in [*header.imports, *config.imports]]
    lines.extend([
        _Line(0, 'from typing import Any as _TJAny', header.lineno),
        _Line(0, 'def _tj_any(*args: _TJAny, **kwargs: _TJAny) -> _TJAny: ...', header.lineno),
    ])
    lines.extend(
        _Line(0, f'{name}: {type_str}', header.lineno)
        for name, type_str in config.globals
        if name not in param_names
    )
    signature = ', '.join(f'{name}: {type_str}' for name, type_str in header.params)
    lines.append(_Line(0, f'def _render({signature}) -> None:', header.lineno))
    body: list[_Line] = []
    _emit_body(tree.body, body, 1)
    if not body:
        body.append(_Line(1, 'pass', header.lineno))
    lines.extend(body)
    code = '\n'.join(_render_line(line) for line in lines) + '\n'
    return GeneratedModule(code=code, param_names=[name for name, _ in header.params])


def _render_line(line: _Line) -> str:
    prefix = '    ' * line.indent
    marker = f'  # L{line.lineno}' if line.lineno else ''
    return f'{prefix}{line.text}{marker}'


def _emit_body(body: list[nodes.Node], out: list[_Line], indent: int) -> None:
    for node in body:
        _emit_node(node, out, indent)


def _emit_node(node: nodes.Node, out: list[_Line], indent: int) -> None:  # ruff:ignore[complex-structure]
    match node:
        case nodes.Output():
            for child in node.nodes:
                if not isinstance(child, nodes.TemplateData):
                    _emit_expr_check(child, out, indent)
        case nodes.For():
            _emit_for(node, out, indent)
        case nodes.If():
            _emit_if(node, out, indent)
        case nodes.Assign():
            _emit_assign(node, out, indent)
        case nodes.AssignBlock():
            _emit_body(node.body, out, indent)
        case nodes.FilterBlock():
            _emit_body(node.body, out, indent)
        case nodes.Scope() | nodes.Block():
            _emit_body(node.body, out, indent)
        case nodes.With():
            _emit_with(node, out, indent)
        case nodes.Macro() | nodes.CallBlock():
            return
        case _:
            _emit_fallback_names(node, out, indent)


def _emit_for(node: nodes.For, out: list[_Line], indent: int) -> None:
    target = _target(node.target)
    iterable = _iter_expr(node.iter, out, indent)
    out.append(_Line(indent, f'for {target} in {iterable}:', node.lineno))
    inner: list[_Line] = []
    _emit_body(node.body, inner, indent + 1)
    if not inner:
        inner.append(_Line(indent + 1, 'pass', node.lineno))
    out.extend(inner)
    if node.else_:
        out.append(_Line(indent, 'if True:', node.lineno))
        _emit_body(node.else_, out, indent + 1)


def _emit_if(node: nodes.If, out: list[_Line], indent: int) -> None:
    out.append(_Line(indent, f'if {_cond(node.test, out, indent)}:', node.lineno))
    _emit_block(node.body, out, indent, node.lineno)
    for elif_node in node.elif_:
        out.append(_Line(indent, f'elif {_cond(elif_node.test, out, indent)}:', elif_node.lineno))
        _emit_block(elif_node.body, out, indent, elif_node.lineno)
    if node.else_:
        out.append(_Line(indent, 'else:', node.lineno))
        _emit_block(node.else_, out, indent, node.lineno)


def _emit_block(body: list[nodes.Node], out: list[_Line], indent: int, lineno: int) -> None:
    inner: list[_Line] = []
    _emit_body(body, inner, indent + 1)
    if not inner:
        inner.append(_Line(indent + 1, 'pass', lineno))
    out.extend(inner)


def _emit_assign(node: nodes.Assign, out: list[_Line], indent: int) -> None:
    target = _target(node.target)
    try:
        value = _expr(node.node)
    except _UnsupportedError:
        _emit_fallback_names(node.node, out, indent)
        value = 'None'
    out.append(_Line(indent, f'{target} = {value}', node.lineno))


def _emit_with(node: nodes.With, out: list[_Line], indent: int) -> None:
    for target, value in zip(node.targets, node.values, strict=False):
        name = _target(target)
        try:
            rendered = _expr(value)
        except _UnsupportedError:
            _emit_fallback_names(value, out, indent)
            rendered = 'None'
        out.append(_Line(indent, f'{name} = {rendered}', node.lineno))
    _emit_body(node.body, out, indent)


def _emit_expr_check(expr: nodes.Node, out: list[_Line], indent: int) -> None:
    try:
        rendered = _expr(expr)
    except _UnsupportedError:
        _emit_fallback_names(expr, out, indent)
        return
    out.append(_Line(indent, f'_ = {rendered}', expr.lineno))


def _emit_fallback_names(node: nodes.Node, out: list[_Line], indent: int) -> None:
    for attr in node.find_all(nodes.Getattr):
        try:
            rendered = _expr(attr)
        except _UnsupportedError:
            continue
        out.append(_Line(indent, f'_ = {rendered}', attr.lineno))
    out.extend(
        _Line(indent, f'_ = {name.name}', name.lineno)
        for name in node.find_all(nodes.Name)
        if name.ctx == 'load'
    )


def _cond(node: nodes.Node, out: list[_Line], indent: int) -> str:
    try:
        return _expr(node)
    except _UnsupportedError:
        _emit_fallback_names(node, out, indent)
        return 'True'


def _iter_expr(node: nodes.Node, out: list[_Line], indent: int) -> str:
    try:
        return _expr(node)
    except _UnsupportedError:
        _emit_fallback_names(node, out, indent)
        return '[]'


def _target(node: nodes.Node) -> str:
    match node:
        case nodes.Name():
            return node.name
        case nodes.Tuple():
            return ', '.join(_target(item) for item in node.items)
        case _:
            raise _UnsupportedError(type(node).__name__)


def _expr(node: nodes.Node) -> str:  # ruff:ignore[complex-structure, too-many-return-statements, too-many-branches]
    match node:
        case nodes.Name() if node.ctx == 'load':
            return node.name
        case nodes.Const():
            return repr(node.value)
        case nodes.Getattr():
            return f'{_expr(node.node)}.{node.attr}'
        case nodes.Getitem():
            return f'{_expr(node.node)}[{_expr(node.arg)}]'
        case nodes.Filter() | nodes.Test():
            if node.node is None:
                raise _UnsupportedError(type(node).__name__)
            return _filtered(node)
        case nodes.Slice():
            return _slice(node)
        case nodes.Compare():
            return _compare(node)
        case nodes.CondExpr():
            expr2 = _expr(node.expr2) if node.expr2 is not None else 'None'
            return f'({_expr(node.expr1)} if {_expr(node.test)} else {expr2})'
        case nodes.Concat():
            return '(' + ' + '.join(f'str({_expr(child)})' for child in node.nodes) + ')'
        case nodes.Tuple():
            inner = ', '.join(_expr(item) for item in node.items)
            return f'({inner},)' if len(node.items) == 1 else f'({inner})'
        case nodes.List():
            return '[' + ', '.join(_expr(item) for item in node.items) + ']'
        case nodes.Dict():
            return '{' + ', '.join(f'{_expr(p.key)}: {_expr(p.value)}' for p in node.items) + '}'
        case nodes.Call():
            return _call(node)
        case nodes.BinExpr():
            return f'({_expr(node.left)} {node.operator} {_expr(node.right)})'
        case nodes.UnaryExpr():
            sep = ' ' if node.operator[-1].isalpha() else ''
            return f'({node.operator}{sep}{_expr(node.node)})'
        case _:
            raise _UnsupportedError(type(node).__name__)


def _compare(node: nodes.Compare) -> str:
    parts = [_expr(node.expr)]
    for operand in node.ops:
        py_op = _CMP_OPS.get(operand.op)
        if py_op is None:
            raise _UnsupportedError(operand.op)
        parts.append(f'{py_op} {_expr(operand.expr)}')
    return '(' + ' '.join(parts) + ')'


def _call(node: nodes.Call) -> str:
    args = [_expr(arg) for arg in node.args]
    args.extend(f'{kw.key}={_expr(kw.value)}' for kw in node.kwargs)
    return f'{_expr(node.node)}(' + ', '.join(args) + ')'


def _filtered(node: nodes.Filter | nodes.Test) -> str:
    if node.node is None:
        raise _UnsupportedError(type(node).__name__)
    args = [_expr(node.node)]
    args.extend(_expr(arg) for arg in node.args)
    args.extend(f'{kw.key}={_expr(kw.value)}' for kw in node.kwargs)
    return '_tj_any(' + ', '.join(args) + ')'


def _slice(node: nodes.Slice) -> str:
    start = _expr(node.start) if node.start is not None else ''
    stop = _expr(node.stop) if node.stop is not None else ''
    if node.step is not None:
        return f'{start}:{stop}:{_expr(node.step)}'
    return f'{start}:{stop}'
