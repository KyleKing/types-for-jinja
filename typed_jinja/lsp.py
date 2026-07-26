"""Language server that publishes typed-jinja diagnostics to an editor.

On open, change, and save of a template, it runs the checker and publishes the
results as LSP diagnostics. It checks the live buffer text while a document is
open, so unsaved edits are reflected, and falls back to the file on disk when no
buffer is tracked.
"""

from __future__ import annotations

from pathlib import Path

from lsprotocol import types as t
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from typed_jinja.check import Diagnostic, PyrightNotFoundError, check_file, check_source

SERVER = LanguageServer('typed-jinja-lsp', '0.0.1')


def _to_lsp(diagnostic: Diagnostic) -> t.Diagnostic:
    line = max(diagnostic.line - 1, 0)
    character = max(diagnostic.column - 1, 0)
    start = t.Position(line=line, character=character)
    end = t.Position(line=line, character=character + 1)
    severity = t.DiagnosticSeverity.Error if diagnostic.severity == 'error' else t.DiagnosticSeverity.Warning
    return t.Diagnostic(
        range=t.Range(start=start, end=end),
        message=diagnostic.message,
        severity=severity,
        code=diagnostic.rule or None,
        source='typed-jinja',
    )


def compute_diagnostics(path: Path) -> list[t.Diagnostic]:
    """Run the checker over ``path`` on disk (empty if pyright is absent)."""
    try:
        diagnostics = check_file(path)
    except PyrightNotFoundError:
        return []
    return [_to_lsp(diagnostic) for diagnostic in diagnostics]


def compute_diagnostics_source(source: str, path: Path) -> list[t.Diagnostic]:
    """Run the checker over live buffer ``source`` labelled as ``path``."""
    try:
        diagnostics = check_source(source, path)
    except PyrightNotFoundError:
        return []
    return [_to_lsp(diagnostic) for diagnostic in diagnostics]


def _live_source(server: LanguageServer, uri: str) -> str | None:
    try:
        return server.workspace.get_text_document(uri).source
    except Exception:
        return None


def _publish(server: LanguageServer, uri: str) -> None:
    fs_path = to_fs_path(uri)
    if fs_path is None:
        return
    path = Path(fs_path)
    source = _live_source(server, uri)
    diagnostics = compute_diagnostics(path) if source is None else compute_diagnostics_source(source, path)
    server.text_document_publish_diagnostics(t.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))


@SERVER.feature(t.TEXT_DOCUMENT_DID_OPEN)
def did_open(server: LanguageServer, params: t.DidOpenTextDocumentParams) -> None:
    """Check a template when it is opened."""
    _publish(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_CHANGE)
def did_change(server: LanguageServer, params: t.DidChangeTextDocumentParams) -> None:
    """Re-check a template as its buffer changes, before it is saved."""
    _publish(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_SAVE)
def did_save(server: LanguageServer, params: t.DidSaveTextDocumentParams) -> None:
    """Re-check a template when it is saved."""
    _publish(server, params.text_document.uri)


def main() -> None:
    """Start the language server over stdio."""
    SERVER.start_io()


if __name__ == '__main__':
    main()
