"""Tests for the header parser, transpiler, and pyright-backed checker."""

from pathlib import Path

from types_for_jinja.check import check_file
from types_for_jinja.header import parse_header
from types_for_jinja.transpile import transpile

from .configuration import requires_pyright

_TEMPLATES = Path('examples/templates')
_BAD = _TEMPLATES / 'greeting_bad.html.jinja'
_OK = _TEMPLATES / 'greeting_ok.html.jinja'

pytestmark = requires_pyright


def test_parse_header_reads_imports_and_params():
    header = parse_header(_BAD.read_text(encoding='utf-8'))

    assert header is not None
    assert header.imports == ['from examples.models import User']
    assert header.params == [('user', 'User')]


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


def test_check_bad_template_reports_three_errors(tmp_path):
    diagnostics = check_file(_BAD, cache_dir=tmp_path)

    located = {(d.line, d.rule) for d in diagnostics}
    assert (5, 'reportAttributeAccessIssue') in located
    assert (11, 'reportAttributeAccessIssue') in located
    assert (11, 'reportUndefinedVariable') in located


def test_check_ok_template_is_clean(tmp_path):
    assert check_file(_OK, cache_dir=tmp_path) == []
