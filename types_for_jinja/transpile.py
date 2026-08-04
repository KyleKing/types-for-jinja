"""Transpile a Jinja2 template into a Python type-checking stub.

The stub is never executed. It exercises every expression the template uses so a
type checker (pyright) can validate variable, attribute, and item access against the
declared context. Jinja still renders the template at runtime, unchanged. Each emitted
line carries a ``# L<n>`` marker back to its source line in the template.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass, field, replace
from pathlib import Path

from jinja2 import Environment, TemplateSyntaxError, nodes

from types_for_jinja import filters
from types_for_jinja.config import Config, Syntax
from types_for_jinja.header import TemplateHeader, parse_defs
from types_for_jinja.resolve import resolve_template, search_paths

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


MacroTypes = dict[int, dict[str, str]]
"""Declared parameter types for each ``{% macro %}``, keyed by the macro's line number."""


@dataclass(frozen=True)
class _Emit:
    """What the emitters need beyond the node itself: declared types and how to reach other files."""

    macro_types: MacroTypes
    search_dirs: list[Path]
    env: Environment
    syntax: Syntax
    seen: frozenset[Path] = frozenset()


def macro_defs(source: str, tree: nodes.Template, syntax: Syntax | None = None) -> tuple[MacroTypes, list[str]]:
    """Bind each ``{#def #}`` block inside a macro body to that macro.

    A block belongs to the closest macro that starts at or before it and still encloses
    it, so a macro nested in another macro claims its own block. Returns the per-macro
    parameter types and the imports those blocks declare.
    """
    macros = sorted(tree.find_all(nodes.Macro), key=lambda node: node.lineno)
    types: MacroTypes = {}
    imports: list[str] = []
    for block in parse_defs(source, syntax):
        owner = next(
            (
                macro
                for macro in reversed(macros)
                if macro.lineno <= block.lineno <= deepest_line(macro) and macro.lineno not in types
            ),
            None,
        )
        if owner is None:
            continue
        types[owner.lineno] = dict(block.params)
        imports.extend(block.imports)
    return types, imports


def build_environment(syntax: Syntax) -> Environment:
    """A parsing-only Environment honouring a project's (possibly non-standard) delimiters."""
    return Environment(
        autoescape=True,
        block_start_string=syntax.block_start_string,
        block_end_string=syntax.block_end_string,
        variable_start_string=syntax.variable_start_string,
        variable_end_string=syntax.variable_end_string,
        comment_start_string=syntax.comment_start_string,
        comment_end_string=syntax.comment_end_string,
        line_statement_prefix=syntax.line_statement_prefix,
        line_comment_prefix=syntax.line_comment_prefix,
    )


def deepest_line(node: nodes.Node) -> int:
    """The last line any part of ``node`` occupies; Jinja records no line for a closing tag."""
    return max((child.lineno for child in node.find_all(nodes.Node)), default=node.lineno)


def _ident(name: str) -> str:
    """Rename a Jinja variable that collides with a Python keyword (``{% set class = %}``)."""
    return f'_tj_kw_{name}' if keyword.iskeyword(name) else name


class UnsupportedTemplateError(Exception):
    """A Jinja node this v1 transpiler does not model as a typed expression.

    Callers that walk a set of templates must catch this and skip the one template, so a
    single unsupported construct cannot take down a whole run.
    """


@dataclass
class Line:
    """One emitted stub statement and the template line it checks."""

    indent: int
    text: str
    lineno: int
    foreign: bool = False


@dataclass
class GeneratedModule:
    """A transpiled type-checking stub and the context parameters it declares."""

    code: str
    param_names: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    preamble_len: int = 0


def transpile(
    source: str,
    header: TemplateHeader,
    config: Config | None = None,
    template_path: Path | None = None,
) -> GeneratedModule:
    """Transpile ``source`` into a Python stub checkable against ``header``'s context.

    ``config`` supplies project-wide Jinja Environment globals (for example
    ``static_url``) so a template that references them is not flagged as undefined.
    ``template_path`` locates the template on disk so ``extends`` / ``import`` /
    ``from import`` references can be resolved against it and ``config.template_dirs``.
    """
    config = config or Config()
    env = build_environment(config.syntax)
    tree = env.parse(source)
    macro_types, macro_imports = macro_defs(source, tree, config.syntax)
    ctx = _Emit(
        macro_types=macro_types,
        search_dirs=_search_dirs(template_path, config),
        env=env,
        syntax=config.syntax,
        seen=frozenset({template_path.resolve()} if template_path is not None else ()),
    )
    split = _split_top_level(tree, ctx)

    lines = _preamble(header, config, [*macro_imports, *split.imports, *filter_imports(tree)])
    preamble_len = len(lines)
    lines.extend(split.foreign_defs)
    lines.extend(split.module_defs)

    signature = ', '.join(f'{name}: {type_str}' for name, type_str in header.params)
    lines.append(Line(0, f'def _render({signature}) -> None:', header.lineno))
    body: list[Line] = []
    _emit_body(split.render_nodes, body, 1, ctx)
    inherited: list[Line] = []
    _emit_body(split.base_nodes, inherited, 1, ctx)
    body.extend(_mark_foreign(inherited, split.base_lineno))
    if not body:
        body.append(Line(1, 'pass', header.lineno))
    lines.extend(body)
    code = '\n'.join(_render_line(line) for line in lines) + '\n'
    return GeneratedModule(
        code=code,
        param_names=[name for name, _ in header.params],
        lines=lines,
        preamble_len=preamble_len,
    )


@dataclass
class _TopLevel:
    """A template's top level, sorted into what defines names and what gets rendered."""

    module_defs: list[Line] = field(default_factory=list)
    render_nodes: list[nodes.Node] = field(default_factory=list)
    base_nodes: list[nodes.Node] = field(default_factory=list)
    foreign_defs: list[Line] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    base_lineno: int = 1


def _split_top_level(tree: nodes.Template, ctx: _Emit) -> _TopLevel:
    split = _TopLevel()
    for node in tree.body:
        match node:
            case nodes.Macro():
                _emit_macro(node, split.module_defs, ctx)
            case nodes.Extends():
                defs: list[Line] = []
                split.base_nodes.extend(_load_base_nodes(node, ctx, defs, split.imports))
                split.foreign_defs.extend(_mark_foreign(defs, node.lineno))
                split.base_lineno = node.lineno
            case nodes.FromImport():
                defs = []
                _emit_from_import(node, ctx, defs, split.imports)
                split.foreign_defs.extend(_mark_foreign(defs, node.lineno))
            case nodes.Import():
                defs = []
                _emit_import(node, ctx, defs, split.imports)
                split.foreign_defs.extend(_mark_foreign(defs, node.lineno))
            case _:
                split.render_nodes.append(node)
    return split


def _preamble(header: TemplateHeader, config: Config, extra_imports: list[str]) -> list[Line]:
    param_names = {name for name, _ in header.params}
    declared = _unique([*header.imports, *config.imports, *extra_imports])
    lines = [Line(0, imp, header.lineno) for imp in declared]
    lines.extend(
        [
            Line(0, 'from typing import Any as _TJAny', header.lineno),
            Line(0, 'def _tj_any(*args: _TJAny, **kwargs: _TJAny) -> _TJAny: ...', header.lineno),
            Line(0, '_tj_loop: _TJAny', header.lineno),
            Line(0, '_tj_default: _TJAny = _tj_any()', header.lineno),
            Line(0, '_: _TJAny', header.lineno),
        ]
    )
    lines.extend(
        Line(0, f'{name}: {type_str}', header.lineno) for name, type_str in config.globals if name not in param_names
    )
    return lines


def _unique(items: list[str]) -> list[str]:
    """Drop repeats while keeping the first occurrence, so a shared import is emitted once."""
    return list(dict.fromkeys(items))


def _mark_foreign(lines: list[Line], lineno: int) -> list[Line]:
    """Flag lines that came from another template and re-stamp them to the tag that pulled them in.

    Their own line numbers belong to a file the reader is not looking at, so an error in a
    base or included template is reported against the ``{% extends %}`` or ``{% include %}``
    that brought it here.
    """
    return [replace(line, foreign=True, lineno=lineno) for line in lines]


def _search_dirs(template_path: Path | None, config: Config) -> list[Path]:
    dirs = [Path(template_path).parent] if template_path is not None else []
    dirs.extend(search_paths(config.template_dirs))
    return dirs


def _render_line(line: Line) -> str:
    prefix = '    ' * line.indent
    marker = f'  # L{line.lineno}' if line.lineno else ''
    return f'{prefix}{line.text}{marker}'


def _emit_body(body: list[nodes.Node], out: list[Line], indent: int, ctx: _Emit) -> None:
    for node in body:
        _emit_node(node, out, indent, ctx)


def _emit_node(node: nodes.Node, out: list[Line], indent: int, ctx: _Emit) -> None:  # ruff:ignore[complex-structure, too-many-branches]
    match node:
        case nodes.Output():
            for child in node.nodes:
                if not isinstance(child, nodes.TemplateData):
                    _emit_expr_check(child, out, indent)
        case nodes.For():
            _emit_for(node, out, indent, ctx)
        case nodes.If():
            _emit_if(node, out, indent, ctx)
        case nodes.Assign():
            _emit_assign(node, out, indent)
        case nodes.AssignBlock():
            _emit_body(node.body, out, indent, ctx)
        case nodes.FilterBlock():
            _emit_body(node.body, out, indent, ctx)
        case nodes.Scope() | nodes.Block():
            _emit_body(node.body, out, indent, ctx)
        case nodes.With():
            _emit_with(node, out, indent, ctx)
        case nodes.CallBlock():
            _emit_expr_check(node.call, out, indent)
            _emit_body(node.body, out, indent, ctx)
        case nodes.Include():
            included, include_ctx = _load_include_nodes(node, ctx)
            inner: list[Line] = []
            _emit_body(included, inner, indent, include_ctx)
            out.extend(_mark_foreign(inner, node.lineno))
        case nodes.Macro():
            _emit_macro(node, out, ctx, indent=indent)
        case _:
            _emit_fallback_names(node, out, indent)


def _emit_for(node: nodes.For, out: list[Line], indent: int, ctx: _Emit) -> None:
    target = _target(node.target)
    iterable = _iter_expr(node.iter, out, indent)
    out.append(Line(indent, f'for {target} in {iterable}:', node.lineno))
    inner: list[Line] = [Line(indent + 1, 'loop = _tj_loop', node.lineno)]
    _emit_body(node.body, inner, indent + 1, ctx)
    out.extend(inner)
    if node.else_:
        out.append(Line(indent, 'if True:', node.lineno))
        _emit_body(node.else_, out, indent + 1, ctx)


def _emit_if(node: nodes.If, out: list[Line], indent: int, ctx: _Emit) -> None:
    out.append(Line(indent, f'if {_cond(node.test, out, indent)}:', node.lineno))
    _emit_block(node.body, out, indent, node.lineno, ctx)
    for elif_node in node.elif_:
        out.append(Line(indent, f'elif {_cond(elif_node.test, out, indent)}:', elif_node.lineno))
        _emit_block(elif_node.body, out, indent, elif_node.lineno, ctx)
    if node.else_:
        out.append(Line(indent, 'else:', node.lineno))
        _emit_block(node.else_, out, indent, node.lineno, ctx)


def _emit_block(body: list[nodes.Node], out: list[Line], indent: int, lineno: int, ctx: _Emit) -> None:
    inner: list[Line] = []
    _emit_body(body, inner, indent + 1, ctx)
    if not inner:
        inner.append(Line(indent + 1, 'pass', lineno))
    out.extend(inner)


def _emit_assign(node: nodes.Assign, out: list[Line], indent: int) -> None:
    target = _target(node.target)
    try:
        value = _expr(node.node)
    except UnsupportedTemplateError:
        _emit_fallback_names(node.node, out, indent)
        value = 'None'
    out.append(Line(indent, f'{target} = {value}', node.lineno))


def _emit_with(node: nodes.With, out: list[Line], indent: int, ctx: _Emit) -> None:
    for target, value in zip(node.targets, node.values, strict=False):
        name = _target(target)
        try:
            rendered = _expr(value)
        except UnsupportedTemplateError:
            _emit_fallback_names(value, out, indent)
            rendered = 'None'
        out.append(Line(indent, f'{name} = {rendered}', node.lineno))
    _emit_body(node.body, out, indent, ctx)


def _macro_params(node: nodes.Macro, macro_types: MacroTypes) -> str:
    """Render the macro's parameter list, annotated from its own ``{#def #}`` block.

    An undeclared parameter stays unannotated so pyright infers it rather than
    reporting every use of it.
    """
    declared = macro_types.get(node.lineno, {})
    offset = len(node.args) - len(node.defaults)
    return ', '.join(
        _macro_param(_ident(arg.name), declared.get(arg.name), defaulted=index >= offset)
        for index, arg in enumerate(node.args)
    )


def _macro_param(name: str, type_str: str | None, *, defaulted: bool) -> str:
    if type_str is None:
        return f'{name}=None' if defaulted else name
    return f'{name}: {type_str} = _tj_default' if defaulted else f'{name}: {type_str}'


def _emit_macro(
    node: nodes.Macro,
    out: list[Line],
    ctx: _Emit,
    *,
    indent: int = 0,
    alias: str | None = None,
) -> None:
    name = alias or node.name
    signature = _macro_params(node, ctx.macro_types)
    out.append(Line(indent, f'def {name}({signature}) -> _TJAny:', node.lineno))
    inner: list[Line] = []
    _emit_body(node.body, inner, indent + 1, ctx)
    if not inner:
        inner.append(Line(indent + 1, 'pass', node.lineno))
    out.extend(inner)


def _emit_macro_stub(
    node: nodes.Macro,
    out: list[Line],
    indent: int,
    ctx: _Emit,
    *,
    alias: str | None = None,
) -> None:
    name = alias or node.name
    out.append(Line(indent, f'def {name}({_macro_params(node, ctx.macro_types)}) -> _TJAny: ...', node.lineno))


def _const_str(node: nodes.Node) -> str | None:
    return node.value if isinstance(node, nodes.Const) and isinstance(node.value, str) else None


@dataclass(frozen=True)
class _ForeignMacros:
    """Macros defined in another template, with the parameter types that template declares."""

    macros: dict[str, nodes.Macro]
    types: MacroTypes
    imports: list[str]


def _load_macros(template: nodes.Node, ctx: _Emit) -> _ForeignMacros | None:
    loaded = _load_template(template, ctx)
    if loaded is None:
        return None
    types, imports = macro_defs(loaded.source, loaded.tree, ctx.syntax)
    return _ForeignMacros(
        macros={child.name: child for child in loaded.tree.body if isinstance(child, nodes.Macro)},
        types=types,
        imports=imports,
    )


def _load_base_nodes(
    node: nodes.Extends,
    ctx: _Emit,
    module_defs: list[Line],
    imports: list[str],
) -> list[nodes.Node]:
    """Collect the nodes a base template contributes, walking the whole ``extends`` chain.

    ``seen`` breaks a cycle, so a template that (directly or not) extends itself stops
    instead of recursing forever.
    """
    loaded = _load_template(node.template, ctx)
    if loaded is None:
        return []
    base_types, base_imports = macro_defs(loaded.source, loaded.tree, ctx.syntax)
    imports.extend(base_imports)
    base_ctx = replace(ctx, macro_types=base_types, seen=loaded.seen)
    top_level: list[nodes.Node] = []
    for child in loaded.tree.body:
        if isinstance(child, nodes.Macro):
            _emit_macro(child, module_defs, base_ctx)
        elif isinstance(child, nodes.Extends):
            top_level.extend(_load_base_nodes(child, base_ctx, module_defs, imports))
        elif not isinstance(child, nodes.Block):
            top_level.append(child)
    return top_level


def _load_include_nodes(node: nodes.Include, ctx: _Emit) -> tuple[list[nodes.Node], _Emit]:
    """Collect the nodes an included template contributes.

    ``{% include %}`` renders with the including template's context, so its expressions
    are checked against that context: a name the include needs and the includer never
    declared is an undefined variable, which is the whole point of checking it here.
    """
    loaded = _load_template(node.template, ctx)
    if loaded is None:
        return [], ctx
    types, _ = macro_defs(loaded.source, loaded.tree, ctx.syntax)
    body = [child for child in loaded.tree.body if not isinstance(child, nodes.Extends)]
    return body, replace(ctx, macro_types=types, seen=loaded.seen)


@dataclass(frozen=True)
class _LoadedTemplate:
    """Another template's parsed body, and the chain that reached it."""

    source: str
    tree: nodes.Template
    seen: frozenset[Path]


def _load_template(reference: nodes.Node, ctx: _Emit) -> _LoadedTemplate | None:
    ref = _const_str(reference)
    if ref is None:
        return None
    resolved = resolve_template(ref, ctx.search_dirs)
    if resolved is None:
        return None
    path, source = resolved
    if path.resolve() in ctx.seen:
        return None
    try:
        tree = ctx.env.parse(source)
    except TemplateSyntaxError:
        return None
    return _LoadedTemplate(source=source, tree=tree, seen=ctx.seen | {path.resolve()})


def _emit_from_import(
    node: nodes.FromImport,
    ctx: _Emit,
    module_defs: list[Line],
    imports: list[str],
) -> None:
    loaded = _load_macros(node.template, ctx)
    if loaded is None or not loaded.macros:
        return
    imports.extend(loaded.imports)
    for entry in node.names:
        name, alias = entry if isinstance(entry, tuple) else (entry, entry)
        macro = loaded.macros.get(name)
        if macro is not None:
            _emit_macro_stub(macro, module_defs, 0, replace(ctx, macro_types=loaded.types), alias=alias)


def _emit_import(
    node: nodes.Import,
    ctx: _Emit,
    module_defs: list[Line],
    imports: list[str],
) -> None:
    loaded = _load_macros(node.template, ctx)
    if loaded is None:
        return
    imports.extend(loaded.imports)
    cls = f'_TJNS_{node.target}'
    module_defs.append(Line(0, f'class {cls}:', node.lineno))
    if not loaded.macros:
        module_defs.append(Line(1, 'pass', node.lineno))
    for macro in loaded.macros.values():
        module_defs.append(Line(1, '@staticmethod', macro.lineno))
        _emit_macro_stub(macro, module_defs, 1, replace(ctx, macro_types=loaded.types))
    module_defs.append(Line(0, f'{node.target} = {cls}', node.lineno))


def _emit_expr_check(expr: nodes.Node, out: list[Line], indent: int) -> None:
    try:
        rendered = _expr(expr)
    except UnsupportedTemplateError:
        _emit_fallback_names(expr, out, indent)
        return
    out.append(Line(indent, f'_ = {rendered}', expr.lineno))


def _emit_fallback_names(node: nodes.Node, out: list[Line], indent: int) -> None:
    for attr in node.find_all(nodes.Getattr):
        try:
            rendered = _expr(attr)
        except UnsupportedTemplateError:
            continue
        out.append(Line(indent, f'_ = {rendered}', attr.lineno))
    out.extend(
        Line(indent, f'_ = {_ident(name.name)}', name.lineno)
        for name in node.find_all(nodes.Name)
        if name.ctx == 'load'
    )


def _cond(node: nodes.Node, out: list[Line], indent: int) -> str:
    try:
        return _expr(node)
    except UnsupportedTemplateError:
        _emit_fallback_names(node, out, indent)
        return 'True'


def _iter_expr(node: nodes.Node, out: list[Line], indent: int) -> str:
    try:
        return _expr(node)
    except UnsupportedTemplateError:
        _emit_fallback_names(node, out, indent)
        return '[]'


def _target(node: nodes.Node) -> str:
    match node:
        case nodes.Name():
            return _ident(node.name)
        case nodes.Tuple():
            return ', '.join(_target(item) for item in node.items)
        case _:
            raise UnsupportedTemplateError(type(node).__name__)


def _expr(node: nodes.Node) -> str:  # ruff:ignore[complex-structure, too-many-return-statements, too-many-branches]
    match node:
        case nodes.Name() if node.ctx == 'load':
            return _ident(node.name)
        case nodes.Const():
            return repr(node.value)
        case nodes.Getattr():
            return f'{_expr(node.node)}.{node.attr}'
        case nodes.Getitem():
            return f'{_expr(node.node)}[{_expr(node.arg)}]'
        case nodes.Filter() | nodes.Test():
            if node.node is None:
                raise UnsupportedTemplateError(type(node).__name__)
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
            raise UnsupportedTemplateError(type(node).__name__)


def _compare(node: nodes.Compare) -> str:
    parts = [_expr(node.expr)]
    for operand in node.ops:
        py_op = _CMP_OPS.get(operand.op)
        if py_op is None:
            raise UnsupportedTemplateError(operand.op)
        parts.append(f'{py_op} {_expr(operand.expr)}')
    return '(' + ' '.join(parts) + ')'


def _call(node: nodes.Call) -> str:
    args = [_expr(arg) for arg in node.args]
    args.extend(f'{kw.key}={_expr(kw.value)}' for kw in node.kwargs)
    return f'{_expr(node.node)}(' + ', '.join(args) + ')'


def _filtered(node: nodes.Filter | nodes.Test) -> str:
    """Apply a filter or test as a call, using its declared signature when there is one."""
    if node.node is None:
        raise UnsupportedTemplateError(type(node).__name__)
    args = [_expr(node.node)]
    args.extend(_expr(arg) for arg in node.args)
    args.extend(f'{kw.key}={_expr(kw.value)}' for kw in node.kwargs)
    return f'{_filter_callable(node)}(' + ', '.join(args) + ')'


def _filter_callable(node: nodes.Filter | nodes.Test) -> str:
    if isinstance(node, nodes.Test):
        return filters.TEST_STUB
    return filters.stub_name(node.name) if node.name in filters.RETURNS else '_tj_any'


def filter_imports(tree: nodes.Template) -> list[str]:
    """The names a stub for ``tree`` must import from the generated filter module."""
    used = {
        filters.stub_name(node.name)
        for node in tree.find_all(nodes.Filter)
        if node.node is not None and node.name in filters.RETURNS
    }
    if any(node.node is not None for node in tree.find_all(nodes.Test)):
        used.add(filters.TEST_STUB)
    return [f'from {filters.MODULE_NAME} import {", ".join(sorted(used))}'] if used else []


def _slice(node: nodes.Slice) -> str:
    start = _expr(node.start) if node.start is not None else ''
    stop = _expr(node.stop) if node.stop is not None else ''
    if node.step is not None:
        return f'{start}:{stop}:{_expr(node.step)}'
    return f'{start}:{stop}'
