"""Language server for Jinja templates. It never runs a type checker.

On open, save, and once an edit settles, it re-transpiles the live buffer and writes the
stub into the project's stub tree. The project's own Python language server is already
watching that tree, so it re-checks the changed file inside its incremental session and
reports the type errors itself, on the template's own line. ``editors/nvim`` mirrors those
onto the template buffer.

What this server publishes is only what it knows without a checker: a template with no
``{#def ... #}`` header, a malformed header, a Jinja syntax error, or a construct the
transpiler cannot model. It also completes and describes the names the typed context makes
available at the cursor, which is what the header is for.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

from lsprotocol import types as t
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from types_for_jinja import filters
from types_for_jinja.complete import ContextName, context_names, cursor_context, describe, probe_module, word_at
from types_for_jinja.config import Config, load_config
from types_for_jinja.diagnostic import Diagnostic
from types_for_jinja.generate import diagnose, generate, write
from types_for_jinja.header import parse_header
from types_for_jinja.members import MemberResolver

SERVER = LanguageServer('types-for-jinja-lsp', '0.0.1')

DEBOUNCE_SECONDS = 0.3
"""How long a buffer must be idle before an edit triggers a re-sync."""

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


def sync_stub(source: str, path: Path, config: Config | None = None) -> list[t.Diagnostic]:
    """Write ``path``'s stub from live buffer ``source`` and report what stopped it.

    Writing the buffer's stub, rather than the saved file's, is what makes an unsaved edit
    visible to the project's Python language server. It leaves the stub tree ahead of the
    saved template until the next save, which is the point.
    """
    resolved = config or load_config(Path.cwd())
    diagnostics = diagnose(source, path, resolved)
    write(generate([path], Path(resolved.out_dir), resolved, sources={path: source}))
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


_RESOLVER: MemberResolver | None = None
_RESOLVER_LOCK = threading.Lock()


def resolver() -> MemberResolver:
    """The shared language server connection for member lookup, built on first use.

    Built lazily rather than at import, because the project root is only known once the client
    has said which workspace it opened. Rooted there so the template's own declared types
    resolve; the probe itself is self-contained and needs nothing generated beside it.
    """
    global _RESOLVER  # ruff:ignore[global-statement]
    with _RESOLVER_LOCK:
        if _RESOLVER is None:
            _RESOLVER = MemberResolver(Path.cwd(), Path('_tj_probe.py'))
        return _RESOLVER


def complete(source: str, line: int, column: int) -> list[t.CompletionItem]:  # ruff:ignore[too-many-return-statements]
    """Complete whatever the cursor is positioned on at zero-based ``line`` and ``column``.

    An empty list means "no suggestion", never "no such name"; the checker is what reports
    a name or attribute that does not exist.
    """
    lines = source.splitlines()
    if line >= len(lines):
        return []
    context = cursor_context(lines[line], column, load_config(Path.cwd()).syntax)
    match context.kind:
        case 'name':
            return _name_items(source, line)
        case 'attribute':
            return _member_items(source, line, context.attribute_of)
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


def _member_items(source: str, line: int, expression: str) -> list[t.CompletionItem]:
    """Ask pyright what ``expression`` offers, inside the scopes the template puts it in."""
    config = load_config(Path.cwd())
    header = parse_header(source, config.syntax)
    if header is None or not expression:
        return []
    probe = probe_module(source, header, config, line + 1, expression)
    if probe is None:
        return []
    return [
        t.CompletionItem(label=member.name, kind=t.CompletionItemKind(member.kind), detail=member.detail)
        for member in resolver().members(probe)
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
    if source is None:
        try:
            source = path.read_text(encoding='utf-8')
        except OSError:
            return
    server.text_document_publish_diagnostics(
        t.PublishDiagnosticsParams(uri=uri, diagnostics=sync_stub(source, path)),
    )


def _publish_debounced(server: LanguageServer, uri: str, delay: float = DEBOUNCE_SECONDS) -> None:
    """Re-sync ``uri`` once the buffer has been quiet for ``delay``, replacing any pending sync.

    Transpiling is fast, but writing a stub on every keystroke would make the project's own
    language server re-check the file that often, and its work is what the debounce protects.
    """
    with _PENDING_LOCK:
        pending = _PENDING.pop(uri, None)
        if pending is not None:
            pending.cancel()
        timer = threading.Timer(delay, _publish, args=(server, uri))
        timer.daemon = True
        _PENDING[uri] = timer
        timer.start()


@SERVER.feature(t.INITIALIZED)
def initialized(server: LanguageServer, _params: t.InitializedParams) -> None:
    """Move to the workspace root, which every relative path in this process then resolves against.

    ``pyproject.toml`` and the stub output directory both belong to the project, not to
    whatever directory the editor happened to start in. One server process serves one
    workspace, so changing directory is the whole fix.
    """
    root = server.workspace.root_path
    if root and Path(root).is_dir():
        os.chdir(root)


@SERVER.feature(t.TEXT_DOCUMENT_DID_OPEN)
def did_open(server: LanguageServer, params: t.DidOpenTextDocumentParams) -> None:
    """Write the template's stub when it is opened."""
    _publish(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_CHANGE)
def did_change(server: LanguageServer, params: t.DidChangeTextDocumentParams) -> None:
    """Re-write the stub from the live buffer once it settles, before the template is saved."""
    _publish_debounced(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_SAVE)
def did_save(server: LanguageServer, params: t.DidSaveTextDocumentParams) -> None:
    """Re-write the stub when the template is saved."""
    _publish(server, params.text_document.uri)


@SERVER.feature(t.TEXT_DOCUMENT_DID_CLOSE)
def did_close(server: LanguageServer, params: t.DidCloseTextDocumentParams) -> None:
    """Put the stub back to what the saved template says, discarding any abandoned edit."""
    _cancel_pending(params.text_document.uri)
    _publish(server, params.text_document.uri)


def _cancel_pending(uri: str) -> None:
    with _PENDING_LOCK:
        pending = _PENDING.pop(uri, None)
    if pending is not None:
        pending.cancel()


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


@SERVER.feature(t.SHUTDOWN)
def shutdown(_server: LanguageServer, _params: object) -> None:
    """Stop the language server connection member completion holds open."""
    resolver().shutdown()


def main() -> None:
    """Start the language server over stdio."""
    try:
        SERVER.start_io()
    finally:
        resolver().shutdown()


if __name__ == '__main__':
    main()
