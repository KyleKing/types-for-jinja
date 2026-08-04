"""The language server writes stubs and reports only what it knows without a checker.

Type errors inside a template are not this server's job any more: it re-transpiles the live
buffer into the stub tree and the project's own Python language server reports them. So these
tests assert two things. The stub on disk tracks the buffer, including unsaved edits, and the
diagnostics the server does publish are the four it can determine on its own.
"""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from lsprotocol import types as t
from pygls.lsp.server import LanguageServer

from types_for_jinja.config import Config
from types_for_jinja.lsp import _publish, _publish_debounced, did_close, remap_positions, stub_for, sync_stub

from . import backends
from .backends import STUB_DIR, TEMPLATE_PATH

_STUB = Path(STUB_DIR) / 'templates/page_html_jinja.py'


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    backends.write_project(tmp_path)
    return tmp_path


@pytest.fixture
def config():
    return Config(out_dir=STUB_DIR)


def _dummy() -> LanguageServer:
    """The custom handlers ignore the server argument, but its type is still enforced."""
    return LanguageServer('test', '0')


def _server(monkeypatch):
    server = LanguageServer('test', '0')
    captured: list[t.PublishDiagnosticsParams] = []
    monkeypatch.setattr(server, 'text_document_publish_diagnostics', captured.append)
    return server, captured


def test_opening_a_template_writes_its_stub(project, config):
    source = (project / TEMPLATE_PATH).read_text(encoding='utf-8')

    assert sync_stub(source, Path(TEMPLATE_PATH), config) == []
    assert '_ = user.naem' in (project / _STUB).read_text(encoding='utf-8')


def test_the_stub_tracks_an_unsaved_edit(project, config):
    """This is the whole mechanism: the project's language server only sees the file on disk."""
    edited = (project / TEMPLATE_PATH).read_text(encoding='utf-8').replace('user.naem', 'user.nmae')

    sync_stub(edited, Path(TEMPLATE_PATH), config)

    stub = (project / _STUB).read_text(encoding='utf-8')
    assert '_ = user.nmae' in stub
    assert 'naem' not in stub


def test_a_template_with_no_header_is_reported_not_stubbed(project, config):
    template = Path('templates/bare.html.jinja')
    (project / template).write_text('<p>{{ whatever }}</p>\n', encoding='utf-8')

    diagnostics = sync_stub((project / template).read_text(encoding='utf-8'), template, config)

    assert [d.severity for d in diagnostics] == [t.DiagnosticSeverity.Warning]
    assert 'no {#def ... #} type header' in diagnostics[0].message


def test_a_malformed_header_is_an_error_on_the_header_line(project, config):
    source = '{#def\nuser: User = #}\n<p>{{ user }}</p>\n'

    diagnostics = sync_stub(source, Path('templates/broken.html.jinja'), config)

    assert [d.severity for d in diagnostics] == [t.DiagnosticSeverity.Error]
    assert diagnostics[0].range.start.line == 0


def test_a_jinja_syntax_error_lands_on_the_broken_tag(project, config):
    broken_line = 5
    source = '{#def\nx: str\n#}\n<p>ok</p>\n{% for %}\n'

    diagnostics = sync_stub(source, Path('templates/broken.html.jinja'), config)

    assert [d.severity for d in diagnostics] == [t.DiagnosticSeverity.Error]
    assert diagnostics[0].range.start.line == broken_line - 1
    assert 'syntax error' in diagnostics[0].message


def test_an_unsupported_construct_is_a_warning_not_a_failure(project, config):
    """One template the transpiler cannot model must not take the rest of the editor down."""
    source = '{#def\nx: str\n#}\n{% set ns = namespace(n=0) %}\n{% set ns.n = 1 %}\n'

    diagnostics = sync_stub(source, Path('templates/ns.html.jinja'), config)

    assert [d.severity for d in diagnostics] == [t.DiagnosticSeverity.Warning]
    assert 'unsupported template construct' in diagnostics[0].message


def test_publish_reads_the_file_when_no_buffer_is_tracked(project, monkeypatch):
    server, captured = _server(monkeypatch)

    _publish(server, (project / TEMPLATE_PATH).as_uri())

    assert len(captured) == 1
    assert (project / _STUB).is_file()


def test_publish_prefers_the_live_buffer_over_the_file(project, monkeypatch):
    edited = (project / TEMPLATE_PATH).read_text(encoding='utf-8').replace('user.naem', 'user.nmae')
    monkeypatch.setattr('types_for_jinja.lsp._live_source', lambda _server, _uri: edited)
    server, _ = _server(monkeypatch)

    _publish(server, (project / TEMPLATE_PATH).as_uri())

    assert '_ = user.nmae' in (project / _STUB).read_text(encoding='utf-8')


def test_closing_a_template_restores_the_saved_stub(project, monkeypatch):
    """An abandoned edit would otherwise leave the stub reporting errors the file does not have."""
    edited = (project / TEMPLATE_PATH).read_text(encoding='utf-8').replace('user.naem', 'user.nmae')
    monkeypatch.setattr('types_for_jinja.lsp._live_source', lambda _server, _uri: edited)
    server, _ = _server(monkeypatch)
    uri = (project / TEMPLATE_PATH).as_uri()
    _publish(server, uri)

    monkeypatch.setattr('types_for_jinja.lsp._live_source', lambda _server, _uri: None)
    did_close(server, t.DidCloseTextDocumentParams(text_document=t.TextDocumentIdentifier(uri=uri)))

    assert '_ = user.naem' in (project / _STUB).read_text(encoding='utf-8')


def test_stub_for_names_the_stub_a_template_generates(project, config):
    """The editor mirror needs this to know which buffer to watch."""
    sync_stub((project / TEMPLATE_PATH).read_text(encoding='utf-8'), Path(TEMPLATE_PATH), config)

    answer = stub_for(_dummy(), {'template': str(project / TEMPLATE_PATH)})

    assert answer == {'stub': str(_STUB)}


def test_stub_for_is_quiet_about_a_template_with_no_stub(project, config):
    assert stub_for(_dummy(), {'template': str(project / 'templates/bare.html.jinja')}) == {'stub': None}
    assert stub_for(_dummy(), {'nonsense': 1}) == {'stub': None}


def test_remap_turns_stub_positions_into_template_positions(project, config):
    """Same arithmetic as the CLI, so the mirror and `types-for-jinja remap` cannot disagree."""
    sync_stub((project / TEMPLATE_PATH).read_text(encoding='utf-8'), Path(TEMPLATE_PATH), config)

    answer = remap_positions(_dummy(), {'stub': str(_STUB), 'positions': [{'line': 4, 'character': 4}]})

    assert answer['template'] == TEMPLATE_PATH
    assert answer['positions'] == [{'line': 4, 'character': 13}]


def test_remap_reports_nothing_for_a_path_it_does_not_own(project, config):
    answer = remap_positions(_dummy(), {'stub': 'app/broken.py', 'positions': [{'line': 1, 'character': 0}]})

    assert answer == {'template': None, 'positions': []}


def test_the_custom_requests_read_an_attribute_object(project, config):
    """Pygls has no schema for a custom method, so it hands over attributes rather than a mapping."""
    sync_stub((project / TEMPLATE_PATH).read_text(encoding='utf-8'), Path(TEMPLATE_PATH), config)
    params = SimpleNamespace(template=str(project / TEMPLATE_PATH))

    assert stub_for(_dummy(), params) == {'stub': str(_STUB)}


def test_rapid_edits_collapse_into_one_sync(monkeypatch):
    """Every keystroke sends a change; only the last should make the project's checker re-run."""
    synced: list[str] = []
    monkeypatch.setattr('types_for_jinja.lsp._publish', lambda _server, uri: synced.append(uri))
    uri = Path(TEMPLATE_PATH).resolve().as_uri()

    for _ in range(10):
        _publish_debounced(LanguageServer('test', '0'), uri, delay=0.05)
    time.sleep(0.3)

    assert synced == [uri]
