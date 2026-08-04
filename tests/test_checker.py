"""The header parser, the transpiler, and what a real checker makes of the generated stub."""

from pathlib import Path

from types_for_jinja.header import Param, parse_header
from types_for_jinja.transpile import transpile

from . import checked
from .checked import reported
from .configuration import requires_checker

_TEMPLATES = Path('examples/templates')
_BAD = _TEMPLATES / 'greeting_bad.html.jinja'


def test_parse_header_reads_imports_and_params():
    header = parse_header(_BAD.read_text(encoding='utf-8'))

    assert header is not None
    assert header.imports == ['from examples.models import User']
    assert header.params == [Param('user', 'User')]


def test_parse_header_absent_returns_none():
    assert parse_header('<h1>no header</h1>') is None


def test_transpile_narrows_loop_variable():
    source = _BAD.read_text(encoding='utf-8')
    header = parse_header(source)
    assert header is not None

    code = transpile(source, header).code

    assert 'def _render(user: User) -> None:' in code
    assert 'for item in user.items:' in code
    assert '_ = item.titel  # L11' in code


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_bad_template_reports_three_errors_on_the_right_lines(examples_project):
    found = reported(Path('examples/templates/greeting_bad.html.jinja'))

    assert [entry.line for entry in found] == [5, 11, 11]
    assert found[0].mentions('naem')
    assert found[1].mentions('titel')
    assert found[2].mentions('author')


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_good_template_is_clean(examples_project):
    assert reported(Path('examples/templates/greeting_ok.html.jinja')) == []
