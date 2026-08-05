"""The aligned stubs and their sidecars must be valid Python and line-aligned.

What a real checker makes of them is `tests/test_backends.py`, over every backend.
"""

import ast
from pathlib import Path

from types_for_jinja.config import Config
from types_for_jinja.generate import generate
from types_for_jinja.header import parse_header
from types_for_jinja.layout import layout
from types_for_jinja.transpile import UnsupportedTemplateError, transpile

_EXAMPLES = Path('examples')


def _generated(tmp_path):
    return generate(sorted(_EXAMPLES.rglob('*.html.jinja')) + sorted(_EXAMPLES.rglob('*.html')), tmp_path)


def test_every_generated_file_parses(tmp_path):
    for path, text in _generated(tmp_path).files.items():
        ast.parse(text, filename=str(path))


def test_aligned_stub_keeps_template_line_numbers(tmp_path):
    generated = _generated(tmp_path)

    assert generated.stubs
    assert generated.unaligned == []


def test_sidecar_binds_the_declared_context(tmp_path):
    """An unbound name in the sidecar buries the real errors from the other template."""
    sidecars = [text for path, text in _generated(tmp_path).files.items() if '_tj_shared' in path.name]

    assert sidecars
    for text in sidecars:
        assert 'current_route: str = _tj_any' in text or 'current_route' not in text


def _aligned(source):
    header = parse_header(source)
    assert header is not None
    return layout(transpile(source, header, Config()), header, 'shared')


def test_inline_conditional_has_an_aligned_form():
    """Two compound statements cannot share a line, so if/else collapses to an expression."""
    source = '{#def\nname: str\n#}\n<p>{% if name %}{{ name.a }}{% else %}{{ name.b }}{% endif %}</p>\n'

    aligned = _aligned(source)

    assert aligned is not None
    assert aligned.code.splitlines()[3] == '_ = (name.a if name else name.b)'


def test_multi_statement_branch_still_has_no_aligned_form():
    """Only a branch that is a single checked expression fits in a conditional expression."""
    source = '{#def\nname: str\n#}\n<p>{% if name %}{{ name.a }}{{ name.c }}{% else %}{{ name.b }}{% endif %}</p>\n'

    assert _aligned(source) is None


def test_a_namespace_assignment_has_an_aligned_form(tmp_path):
    """``{% set ns.n = 1 %}`` used to raise out of transpile and skip the whole template."""
    source = '{#def\nname: str\n#}\n{% set ns = namespace(n=0) %}\n{% set ns.n = 1 %}\n{{ ns.n }}\n'
    template = tmp_path / 'ns.html.jinja'
    template.write_text(source, encoding='utf-8')

    generated = generate([template], tmp_path / 'out')

    assert generated.skipped == []
    assert 'ns.n = 1' in generated.stubs[0].files[generated.stubs[0].path]


def test_marker_mode_if_branch_keeps_its_own_body(tmp_path):
    """``else`` sharing the ``if``'s own line used to strand the if-branch's later-lined body.

    Not under ``examples/``: this template can have no aligned form (a multi-statement
    for-loop branch), and ``test_aligned_stub_keeps_template_line_numbers`` requires every
    shipped example to align.
    """
    source = (
        '{#def\nitems: list[str]\n#}\n'
        '{% if items %}\n'
        '  {% for item in items %}\n'
        '    {{ item.upper() }}{{ item.lower() }}\n'
        '  {% endfor %}\n'
        '{% else %}\n'
        '  none\n'
        '{% endif %}\n'
    )
    template = tmp_path / 'list_page.html.jinja'
    template.write_text(source, encoding='utf-8')

    generated = generate([template], tmp_path / 'out')

    assert generated.unaligned == [template]
    code = generated.stubs[0].files[generated.stubs[0].path]
    tree = ast.parse(code)
    if_node = next(node for node in ast.walk(tree) if isinstance(node, ast.If))
    assert any(isinstance(stmt, ast.For) for stmt in if_node.body)


def test_an_unsupported_construct_skips_one_template_not_the_run(tmp_path, monkeypatch):
    """One template the transpiler cannot model must not stop the others being generated."""
    real = transpile

    def refuse(source, header, config=None, template_path=None, depth=0):
        if template_path is not None and template_path.name == 'odd.html.jinja':
            raise UnsupportedTemplateError('OddNode')
        return real(source, header, config, template_path, depth)

    monkeypatch.setattr('types_for_jinja.generate.transpile', refuse)
    odd = tmp_path / 'odd.html.jinja'
    odd.write_text('{#def\nname: str\n#}\n{{ name }}\n', encoding='utf-8')

    generated = generate([Path('examples/templates/greeting_bad.html.jinja'), odd], tmp_path / 'out')

    assert [reason for path, reason in generated.skipped if path == odd] == ['unsupported template construct: OddNode']
    assert generated.stubs
