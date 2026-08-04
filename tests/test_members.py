"""Attribute completion, which delegates member lookup to a real Python language server.

Any LSP-speaking checker will do, so the tests that need one run against every candidate
installed rather than pinning pyright. Adding a backend to ``members.CANDIDATES`` puts it
under test here automatically.
"""

import shutil
from pathlib import Path

import pytest

from types_for_jinja.complete import cursor_context, probe_module
from types_for_jinja.config import Config
from types_for_jinja.header import parse_header
from types_for_jinja.lsp import complete
from types_for_jinja.members import CANDIDATES, MemberResolver, discover

_OK = Path('examples/templates/greeting_ok.html.jinja')
_SOURCE = _OK.read_text(encoding='utf-8')

_INSTALLED = [name for name, _ in CANDIDATES if shutil.which(name) is not None]
_SERVERS = [pytest.param(name, id=name) for name in _INSTALLED] or [
    pytest.param('none', marks=pytest.mark.skip(reason='no Python language server installed'))
]

requires_langserver = pytest.mark.skipif(not _INSTALLED, reason='a Python language server is required')


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
    labels = {item.label for item in complete(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ user.'), 4, 12)}

    assert labels == {'name', 'is_admin', 'items'}


@requires_langserver
def test_attribute_completion_narrows_a_loop_variable():
    typed = _typed('  <li>{{ item.title }}{% if item.done %} (done){% endif %}</li>', '  <li>{{ item.')

    labels = {item.label for item in complete(typed, 10, 16)}

    assert labels == {'title', 'done'}


@requires_langserver
def test_attribute_completion_follows_item_access():
    labels = {item.label for item in complete(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ user.items[0].'), 4, 21)}

    assert labels == {'title', 'done'}


@requires_langserver
def test_unresolvable_base_offers_nothing_rather_than_guessing():
    assert complete(_typed('<h1>Hello {{ user.name }}</h1>', '<h1>{{ nope.'), 4, 12) == []


def _resolved(server, source, line, expression):
    probe = _probe(source, line, expression)
    assert probe is not None
    resolver = MemberResolver(Path.cwd(), Path('_tj_probe.py'), server)
    try:
        return resolver.members(probe)
    finally:
        resolver.shutdown()


@pytest.mark.parametrize('server', _SERVERS)
def test_every_installed_language_server_resolves_the_same_members(server):
    """A project switching checkers must not lose attribute completion."""
    typed = _typed('  <li>{{ item.title }}{% if item.done %} (done){% endif %}</li>', '  <li>{{ item.')

    members = _resolved(server, typed, 11, 'item')

    assert {member.name for member in members} == {'title', 'done'}


@pytest.mark.parametrize('server', _SERVERS)
def test_every_installed_language_server_reports_the_member_type(server):
    """Servers disagree on where the type goes, and a popup of bare names is not worth much.

    ty puts it in ``detail``; pyright withholds it until ``completionItem/resolve`` and then
    answers in ``documentation``. Both have to arrive as the type on its own.
    """
    typed = _typed('  <li>{{ item.title }}{% if item.done %} (done){% endif %}</li>', '  <li>{{ item.')

    details = {member.name: member.detail for member in _resolved(server, typed, 11, 'item')}

    assert details == {'title': 'str', 'done': 'bool'}


def test_cursor_after_a_dot_never_falls_back_to_name_completion():
    """Offering context names right after a `.` would suggest things that cannot go there."""
    assert cursor_context('{{ (user.items | first).', 24).kind == 'attribute'


def test_discovery_prefers_the_first_candidate_present():
    installed = {name for name, _ in CANDIDATES if shutil.which(name) is not None}
    found = discover()

    assert (found is None) == (not installed)
    if found is not None:
        assert found[0] == next(name for name, _ in CANDIDATES if name in installed)


def test_a_pinned_language_server_is_never_swapped_for_another(monkeypatch):
    """A project naming one checker must not silently get a different one's answers."""
    monkeypatch.setattr('types_for_jinja.members.shutil.which', lambda name: None if name == 'ty' else '/bin/' + name)

    assert discover('ty') is None
    assert discover('pyright-langserver') == ('pyright-langserver', ('--stdio',))


def test_resolver_returns_empty_when_no_language_server_is_installed(monkeypatch):
    """Completion is additive, so absence must stay quiet rather than raise."""
    monkeypatch.setattr('types_for_jinja.members.shutil.which', lambda _name: None)

    assert MemberResolver(Path.cwd(), Path('_tj_probe.py')).members('_tj_probe = "".') == []
