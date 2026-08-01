"""Tests for the typed-jinja language server (in-process, no subprocess)."""

import shutil
from pathlib import Path

import pytest
from lsprotocol import types as t
from pygls.lsp.server import LanguageServer

from typed_jinja.lsp import _publish, compute_diagnostics, compute_diagnostics_source

_BAD = Path('examples/templates/greeting_bad.html')
_OK = Path('examples/templates/greeting_ok.html')
_ERRORS_IN_BAD = 3

pytestmark = pytest.mark.skipif(shutil.which('pyright') is None, reason='pyright is required')


def test_compute_diagnostics_maps_positions_and_severity():
    diagnostics = compute_diagnostics(_BAD)

    assert len(diagnostics) == _ERRORS_IN_BAD
    assert sorted(d.range.start.line for d in diagnostics) == [4, 10, 10]
    assert all(d.source == 'typed-jinja' for d in diagnostics)
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


def test_publish_checks_the_live_buffer_over_a_clean_file(monkeypatch):
    edited = _OK.read_text(encoding='utf-8').replace('user.name', 'user.nmae')
    monkeypatch.setattr('typed_jinja.lsp._live_source', lambda _server, _uri: edited)
    server = LanguageServer('test', '0')
    captured: list[t.PublishDiagnosticsParams] = []
    monkeypatch.setattr(server, 'text_document_publish_diagnostics', captured.append)

    _publish(server, _OK.resolve().as_uri())

    assert len(captured) == 1
    assert any('nmae' in d.message for d in captured[0].diagnostics)
