"""Language server that publishes types-for-jinja diagnostics to an editor.

On open, change, and save of a template, it runs the checker and publishes the
results as LSP diagnostics. It checks the live buffer text while a document is
open, so unsaved edits are reflected, and falls back to the file on disk when no
buffer is tracked.

It also completes and describes the names the typed context makes available at the
cursor, which is what the ``{#def ... #}`` header is for.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from lsprotocol import types as t
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from types_for_jinja import filters
from types_for_jinja.check import Diagnostic, PyrightNotFoundError, check_file, check_source
from types_for_jinja.complete import ContextName, context_names, cursor_context, describe, word_at
from types_for_jinja.config import load_config
from types_for_jinja.header import parse_header

SERVER = LanguageServer('types-for-jinja-lsp', '0.0.1')

DEBOUNCE_SECONDS = 0.3
"""How long a buffer must be idle before an edit triggers a re-check."""

_PENDING: dict[str, threading.Timer] = {}
_PENDING_LOCK = threading.Lock()


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
        source='types-for-jinja',
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


_ORIGIN_KINDS = {
    'global': t.CompletionItemKind.Variable,
    'imported macro': t.CompletionItemKind.Function,
    'imported macros': t.CompletionItemKind.Module,
    'loop helper': t.CompletionItemKind.Variable,
    'loop target': t.CompletionItemKind.Variable,
    'macro': t.CompletionItemKind.Function,
    'macro parameter': t.CompletionItemKind.Variable,
    'parameter': t.CompletionItemKind.Field,
    'set': t.CompletionItemKind.Variable,
    'with target': t.CompletionItemKind.Variable,
}


def visible_names(source: str, line: int) -> list[ContextName]:
    """Return the context names visible on one-based ``line`` of ``source``."""
    config = load_config(Path.cwd())
    header = parse_header(source, config.syntax)
    if header is None:
        return []
    return context_names(source, header, config, line=line)


def complete(source: str, line: int, column: int) -> list[t.CompletionItem]:
    """Complete whatever the cursor is positioned on at zero-based ``line`` and ``column``.

    Attribute access (anything after a ``.``) is left to the checker for now, so an empty
    list there means "no suggestion", not "no such attribute".
    """
    lines = source.splitlines()
    if line >= len(lines):
        return []
    context = cursor_context(lines[line], column, load_config(Path.cwd()).syntax)
    match context.kind:
        case 'name':
            return _name_items(source, line)
        case 'filter':
            return _catalog_items(filters.RETURNS, t.CompletionItemKind.Function, _filter_detail)
        case 'test':
            return _catalog_items(dict.fromkeys(filters.TESTS, 'bool'), t.CompletionItemKind.Function, _test_detail)
        case 'tag':
            return _catalog_items(dict.fromkeys(filters.TAGS, ''), t.CompletionItemKind.Keyword, _tag_detail)
        case _:
            return []


def _name_items(source: str, line: int) -> list[t.CompletionItem]:
    return [
        t.CompletionItem(
            label=entry.name,
            kind=_ORIGIN_KINDS.get(entry.origin, t.CompletionItemKind.Variable),
            detail=describe(entry),
        )
        for entry in visible_names(source, line + 1)
    ]


def _catalog_items(
    catalog: dict[str, str],
    kind: t.CompletionItemKind,
    detail: Callable[[str, str], str],
) -> list[t.CompletionItem]:
    return [t.CompletionItem(label=name, kind=kind, detail=detail(name, value)) for name, value in catalog.items()]


def _filter_detail(name: str, returns: str) -> str:
    return f'{name} -> {_readable(returns)} (built-in filter)'


def _test_detail(name: str, _returns: str) -> str:
    return f'{name} -> bool (built-in test)'


def _tag_detail(name: str, _value: str) -> str:
    return f'{{% {name} %}} (Jinja tag)'


def _readable(returns: str) -> str:
    """Render an internal signature type the way a template author would read it."""
    return returns.replace('_TJAny', 'Any').replace('_T', 'item')


def builtin_hover(word: str) -> str | None:
    """Describe a built-in filter, test, or tag, or ``None`` when ``word`` is none of them."""
    if word in filters.RETURNS:
        return _filter_detail(word, filters.RETURNS[word])
    if word in filters.TESTS:
        return _test_detail(word, 'bool')
    return _tag_detail(word, '') if word in filters.TAGS else None


def hover_text(source: str, line: int, column: int) -> str | None:
    """Describe the context name under zero-based ``line`` and ``column``, if there is one."""
    lines = source.splitlines()
    if line >= len(lines):
        return None
    word = word_at(lines[line], column)
    if not word:
        return None
    described = next((describe(entry) for entry in visible_names(source, line + 1) if entry.name == word), None)
    return described if described is not None else builtin_hover(word)


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


def _publish_debounced(server: LanguageServer, uri: str, delay: float = DEBOUNCE_SECONDS) -> None:
    """Check ``uri`` once the buffer has been quiet for ``delay``, replacing any pending check.

    Each check spawns pyright, which is far slower than a keystroke, so checking on every
    change would queue work faster than it drains and stall completion and hover behind it.
    """
    with _PENDING_LOCK:
        pending = _PENDING.pop(uri, None)
        if pending is not None:
            pending.cancel()
        timer = threading.Timer(delay, _publish, args=(server, uri))
        timer.daemon = True
        _PENDING[uri] = timer
        timer.start()


@SERVER.feature(t.TEXT_DOCUMENT_DID_OPEN)
def did_open(server: LanguageServer, params: t.DidOpenTextDocumentParams) -> None:
    """Check a template when it is opened."""
    _publish(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_CHANGE)
def did_change(server: LanguageServer, params: t.DidChangeTextDocumentParams) -> None:
    """Re-check a template once its buffer settles, before it is saved."""
    _publish_debounced(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_SAVE)
def did_save(server: LanguageServer, params: t.DidSaveTextDocumentParams) -> None:
    """Re-check a template when it is saved."""
    _publish(server, params.text_document.uri)


def _document_source(server: LanguageServer, uri: str) -> str | None:
    source = _live_source(server, uri)
    if source is not None:
        return source
    fs_path = to_fs_path(uri)
    return Path(fs_path).read_text(encoding='utf-8') if fs_path else None


@SERVER.feature(t.TEXT_DOCUMENT_COMPLETION, t.CompletionOptions(trigger_characters=[' ', '.', '|', '%']))
def completion(server: LanguageServer, params: t.CompletionParams) -> t.CompletionList:
    """Offer the context names visible at the cursor."""
    source = _document_source(server, params.text_document.uri)
    if source is None:
        return t.CompletionList(is_incomplete=False, items=[])
    items = complete(source, params.position.line, params.position.character)
    return t.CompletionList(is_incomplete=False, items=items)


@SERVER.feature(t.TEXT_DOCUMENT_HOVER)
def hover(server: LanguageServer, params: t.HoverParams) -> t.Hover | None:
    """Describe the declared type of the context name under the cursor."""
    source = _document_source(server, params.text_document.uri)
    if source is None:
        return None
    text = hover_text(source, params.position.line, params.position.character)
    if text is None:
        return None
    return t.Hover(contents=t.MarkupContent(kind=t.MarkupKind.Markdown, value=f'```python\n{text}\n```'))


def main() -> None:
    """Start the language server over stdio."""
    SERVER.start_io()


if __name__ == '__main__':
    main()
