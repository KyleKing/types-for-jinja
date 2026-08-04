"""The aligned stubs and their sidecars must be valid Python and line-aligned.

What a real checker makes of them is `tests/test_backends.py`, over every backend.
"""

import ast
from pathlib import Path

from types_for_jinja.config import Config
from types_for_jinja.generate import generate
from types_for_jinja.header import parse_header
from types_for_jinja.layout import layout
from types_for_jinja.transpile import transpile

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


def test_unsupported_construct_skips_one_template(tmp_path):
    """A namespace assignment used to raise out of transpile and take down the whole run."""
    source = '{#def\nname: str\n#}\n{% set ns = namespace(n=0) %}\n{% set ns.n = 1 %}\n'
    template = tmp_path / 'ns.html.jinja'
    template.write_text(source, encoding='utf-8')

    generated = generate([Path('examples/templates/greeting_bad.html.jinja'), template], tmp_path / 'out')

    assert [reason for path, reason in generated.skipped if path == template] == [
        'unsupported template construct: NSRef'
    ]
    assert generated.stubs
