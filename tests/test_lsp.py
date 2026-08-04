"""Tests for the types-for-jinja language server (in-process, no subprocess)."""

import time
from pathlib import Path

from lsprotocol import types as t
from pygls.lsp.server import LanguageServer

from types_for_jinja.lsp import _publish, _publish_debounced, compute_diagnostics, compute_diagnostics_source

from .configuration import requires_pyright

_BAD = Path('examples/templates/greeting_bad.html.jinja')
_OK = Path('examples/templates/greeting_ok.html.jinja')
_ERRORS_IN_BAD = 3

pytestmark = requires_pyright


def test_compute_diagnostics_maps_positions_and_severity():
    diagnostics = compute_diagnostics(_BAD)

    assert len(diagnostics) == _ERRORS_IN_BAD
    assert sorted(d.range.start.line for d in diagnostics) == [4, 10, 10]
    assert all(d.source == 'types-for-jinja' for d in diagnostics)
    assert all(d.severity == t.DiagnosticSeverity.Error for d in diagnostics)


def test_publish_sends_diagnostics_through_the_server(monkeypatch):
    server = LanguageServer('test', '0')
    captured: list[t.PublishDiagnosticsParams] = []
    monkeypatch.setattr(server, 'text_document_publish_diagnostics', captured.append)

    _publish(server, _BAD.resolve().as_uri())

    assert len(captured) == 1
    assert len(captured[0].diagnostics) == _ERRORS_IN_BAD


def test_compute_diagnostics_source_reflects_the_buffer_not_disk():
    on_disk = compute_diagnostics_source(_OK.read_text(encoding='utf-8'), _OK)
    assert on_disk == []

    edited = _OK.read_text(encoding='utf-8').replace('user.name', 'user.nmae')
    diagnostics = compute_diagnostics_source(edited, _OK)

    assert any('nmae' in d.message for d in diagnostics)


def test_rapid_edits_collapse_into_one_check(monkeypatch):
    """Every keystroke sends a change; only the last one should reach pyright."""
    checks: list[str] = []
    monkeypatch.setattr('types_for_jinja.lsp._publish', lambda _server, uri: checks.append(uri))
    uri = _OK.resolve().as_uri()

    for _ in range(10):
        _publish_debounced(LanguageServer('test', '0'), uri, delay=0.05)
    time.sleep(0.3)

    assert checks == [uri]


def test_publish_checks_the_live_buffer_over_a_clean_file(monkeypatch):
    edited = _OK.read_text(encoding='utf-8').replace('user.name', 'user.nmae')
    monkeypatch.setattr('types_for_jinja.lsp._live_source', lambda _server, _uri: edited)
    server = LanguageServer('test', '0')
    captured: list[t.PublishDiagnosticsParams] = []
    monkeypatch.setattr(server, 'text_document_publish_diagnostics', captured.append)

    _publish(server, _OK.resolve().as_uri())

    assert len(captured) == 1
    assert any('nmae' in d.message for d in captured[0].diagnostics)
