"""Attribute completion, which delegates member lookup to pyright."""

import shutil
from pathlib import Path

import pytest

from types_for_jinja.complete import cursor_context, probe_module
from types_for_jinja.config import Config
from types_for_jinja.header import parse_header
from types_for_jinja.lsp import complete
from types_for_jinja.members import MemberResolver

_OK = Path('examples/templates/greeting_ok.html.jinja')
_SOURCE = _OK.read_text(encoding='utf-8')

requires_langserver = pytest.mark.skipif(
    shutil.which('pyright-langserver') is None,
    reason='pyright-langserver is required',
)


def _typed(old, new):
    return _SOURCE.replace(old, new)


def _probe(source, line, expression):
    header = parse_header(source)
    assert header is not None
    return probe_module(source, header, Config(), line, expression)


def test_probe_reaches_the_cursor_and_stops_there():
    probe = _probe(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ user.'), 5, 'user')

    assert probe is not None
    assert probe.rstrip().endswith('_tj_probe = user.')
    assert 'item' not in probe


def test_probe_places_the_expression_inside_the_loop_scope():
    typed = _typed('  <li>{{ item.title }}{% if item.done %} (done){% endif %}</li>', '  <li>{{ item.')

    probe = _probe(typed, 11, 'item')

    assert probe is not None
    assert 'for item in user.items:' in probe
    assert probe.rstrip().endswith('    _tj_probe = item.')


def test_probe_is_none_when_no_repair_parses():
    assert _probe('{#def\nx: str\n#}\n{% for %}\n{{ x.\n', 5, 'x') is None


@requires_langserver
def test_attribute_completion_offers_the_declared_type_members():
    labels = [item.label for item in complete(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ user.'), 4, 12)]

    assert labels == ['name', 'is_admin', 'items']


@requires_langserver
def test_attribute_completion_narrows_a_loop_variable():
    typed = _typed('  <li>{{ item.title }}{% if item.done %} (done){% endif %}</li>', '  <li>{{ item.')

    labels = [item.label for item in complete(typed, 10, 16)]

    assert labels == ['title', 'done']


@requires_langserver
def test_attribute_completion_follows_item_access():
    labels = [item.label for item in complete(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ user.items[0].'), 4, 21)]

    assert labels == ['title', 'done']


@requires_langserver
def test_unresolvable_base_offers_nothing_rather_than_guessing():
    assert complete(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ nope.'), 4, 12) == []


def test_cursor_after_a_dot_never_falls_back_to_name_completion():
    """Offering context names right after a `.` would suggest things that cannot go there."""
    assert cursor_context('{{ (user.items | first).', 24).kind == 'attribute'


def test_resolver_returns_empty_when_the_language_server_is_missing(monkeypatch):
    monkeypatch.setattr('types_for_jinja.members.shutil.which', lambda _name: None)

    assert MemberResolver(Path.cwd()).members('_tj_probe = "".') == []
