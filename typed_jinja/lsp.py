"""Language server that publishes typed-jinja diagnostics to an editor.

On open and on save of a template, it runs the checker over the file on disk and
publishes the results as LSP diagnostics. It checks the saved file, not unsaved buffer
edits, which is enough for the v1 spike.
"""

from __future__ import annotations

from pathlib import Path

from lsprotocol import types as t
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from typed_jinja.check import Diagnostic, PyrightNotFoundError, check_file

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
    """Run the checker over ``path`` and return LSP diagnostics (empty if pyright is absent)."""
    try:
        diagnostics = check_file(path)
    except PyrightNotFoundError:
        return []
    return [_to_lsp(diagnostic) for diagnostic in diagnostics]


def _publish(server: LanguageServer, uri: str) -> None:
    fs_path = to_fs_path(uri)
    if fs_path is None:
        return
    diagnostics = compute_diagnostics(Path(fs_path))
    server.text_document_publish_diagnostics(t.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))


@SERVER.feature(t.TEXT_DOCUMENT_DID_OPEN)
def did_open(server: LanguageServer, params: t.DidOpenTextDocumentParams) -> None:
    """Check a template when it is opened."""
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
