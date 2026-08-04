"""Ask a Python language server what members a template expression has.

Attribute completion needs the declared type resolved, not just named, and resolving types
is the one thing this project deliberately does not do itself. So it asks a real language
server: build a probe module that binds the template's context and ends in the expression
the cursor is on, hand it over, and forward the completions back.

Any LSP-speaking Python checker will do, and ``CANDIDATES`` is the list tried in order.
Adding one is a single entry. When none is installed, member completion returns nothing:
completion is additive, so its absence stays quiet rather than becoming an error.

The probe is never written to disk and never executed; it is sent over the wire as an
unsaved document. The server is started on first use and reused, because starting one costs
far more than a query.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

_TIMEOUT_SECONDS = 10.0

_CAPABILITIES = {
    'textDocument': {
        'completion': {
            'completionItem': {
                'documentationFormat': ['markdown', 'plaintext'],
                'resolveSupport': {'properties': ['detail', 'documentation']},
            },
        },
    },
}
"""Declared so a server that withholds a member's type until resolve will hand it over."""

__all__ = ['CANDIDATES', 'Member', 'MemberResolver']

CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('pyright-langserver', ('--stdio',)),
    ('basedpyright-langserver', ('--stdio',)),
    ('ty', ('server',)),
    ('pylsp', ()),
    ('jedi-language-server', ()),
)
"""Language servers to try, most precise first, as ``(executable, arguments)``.

pyright leads because its completion details carry the resolved type. A project that wants
a particular one names it in ``[tool.types_for_jinja] language_server``.
"""


@dataclass(frozen=True)
class Member:
    """One attribute or method offered on a template expression."""

    name: str
    kind: int
    detail: str


def discover(preferred: str = '') -> tuple[str, tuple[str, ...]] | None:
    """The first candidate language server on PATH, or ``None`` when there is none.

    ``preferred`` pins one by executable name and disables the fallback, so a project that
    asks for a specific server never silently gets a different one.
    """
    candidates = [entry for entry in CANDIDATES if entry[0] == preferred] if preferred else list(CANDIDATES)
    if preferred and not candidates:
        candidates = [(preferred, ())]
    return next(((name, args) for name, args in candidates if shutil.which(name) is not None), None)


class MemberResolver:
    """A reusable Python language server connection scoped to one project root.

    Not thread-safe on its own; ``members`` serialises callers behind a lock. Call
    ``shutdown`` when finished, after which the resolver must not be reused.
    """

    def __init__(self, root: Path, probe: Path, language_server: str = '') -> None:
        """Bind the resolver to ``root``; no server starts until the first query.

        ``probe`` is where the throwaway module is claimed to live, relative to ``root`` or
        absolute. ``language_server`` pins one executable instead of taking the first of
        ``CANDIDATES`` found on PATH.
        """
        self._root = root.resolve()
        self._probe = probe if probe.is_absolute() else self._root / probe
        self._language_server = language_server
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._version = 0

    def members(self, probe: str) -> list[Member]:
        """Return the members offered at the end of ``probe``, empty when unresolvable.

        ``probe`` must be a Python module whose last line ends at the ``.`` being completed.
        """
        with self._lock:
            try:
                return self._query(probe)
            except (OSError, TypeError, ValueError, TimeoutError):
                self._stop()
                return []

    def shutdown(self) -> None:
        """Stop the language server if one is running."""
        with self._lock:
            self._stop()

    def _query(self, source: str) -> list[Member]:
        process = self._ensure_started()
        uri = self._probe.as_uri()
        self._version += 1
        method = 'textDocument/didOpen' if self._version == 1 else 'textDocument/didChange'
        self._notify(process, method, _document_params(uri, source, self._version))
        lines = source.rstrip('\n').split('\n')
        position = {'line': len(lines) - 1, 'character': len(lines[-1])}
        result = self._request(
            process,
            'textDocument/completion',
            {'textDocument': {'uri': uri}, 'position': position},
        )
        return [self._resolved(process, item) for item in _offered(result)]

    def _resolved(self, process: subprocess.Popen[bytes], item: dict[str, object]) -> Member:
        """Fill in a member's type when the server only sends it on resolve.

        ty answers with the type in ``detail`` straight away. pyright sends nothing there and
        puts it in ``documentation`` on resolve instead, so without this the popup lists
        member names with no types beside them.
        """
        member = _to_member(item)
        if member.detail or 'data' not in item:
            return member
        try:
            extra = self._request(process, 'completionItem/resolve', item)
        except (OSError, TypeError, ValueError):
            return member
        if not isinstance(extra, dict):
            return member
        return replace(member, detail=_detail_of(cast('dict[str, object]', extra)))

    def _ensure_started(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        found = discover(self._language_server)
        if found is None:
            message = 'no Python language server found on PATH'
            raise OSError(message)
        name, args = found
        self._process = subprocess.Popen(  # ruff:ignore[subprocess-without-shell-equals-true]
            [shutil.which(name) or name, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self._root,
        )
        self._version = 0
        self._request(
            self._process,
            'initialize',
            {
                'processId': os.getpid(),
                'rootUri': self._root.as_uri(),
                'capabilities': _CAPABILITIES,
                'initializationOptions': {},
            },
        )
        self._notify(self._process, 'initialized', {})
        return self._process

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.kill()
        process.wait(timeout=_TIMEOUT_SECONDS)

    @staticmethod
    def _send(process: subprocess.Popen[bytes], payload: dict[str, object]) -> None:
        if process.stdin is None:
            message = 'language server stdin is closed'
            raise OSError(message)
        body = json.dumps(payload).encode('utf-8')
        process.stdin.write(f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body)
        process.stdin.flush()

    @staticmethod
    def _notify(process: subprocess.Popen[bytes], method: str, params: dict[str, object]) -> None:
        MemberResolver._send(process, {'jsonrpc': '2.0', 'method': method, 'params': params})

    def _request(self, process: subprocess.Popen[bytes], method: str, params: dict[str, object]) -> object:
        request_id, self._next_id = self._next_id, self._next_id + 1
        MemberResolver._send(process, {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        while True:
            message = _read_message(process)
            if message.get('id') == request_id:
                return message.get('result')


def _document_params(uri: str, source: str, version: int) -> dict[str, object]:
    if version == 1:
        return {'textDocument': {'uri': uri, 'languageId': 'python', 'version': version, 'text': source}}
    return {
        'textDocument': {'uri': uri, 'version': version},
        'contentChanges': [{'text': source}],
    }


def _read_message(process: subprocess.Popen[bytes]) -> dict[str, object]:
    if process.stdout is None:
        message = 'language server stdout is closed'
        raise OSError(message)
    length = 0
    while True:
        header = process.stdout.readline()
        if not header:
            message = 'language server closed the connection'
            raise OSError(message)
        if header in {b'\r\n', b'\n'}:
            break
        name, _, value = header.decode('utf-8').partition(':')
        if name.strip().lower() == 'content-length':
            length = int(value.strip())
    payload = process.stdout.read(length)
    parsed = json.loads(payload.decode('utf-8'))
    if not isinstance(parsed, dict):
        message = 'language server sent a non-object message'
        raise TypeError(message)
    return parsed


def _offered(result: object) -> list[dict[str, object]]:
    """The completion items worth showing: labelled, and not a dunder."""
    items = result.get('items', []) if isinstance(result, dict) else result
    if not isinstance(items, list):
        return []
    offered: list[dict[str, object]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = cast('dict[str, object]', raw)
        label = item.get('label')
        if isinstance(label, str) and not label.startswith('__'):
            offered.append(item)
    return offered


def _to_member(item: dict[str, object]) -> Member:
    kind = item.get('kind', 5)
    return Member(name=str(item.get('label', '')), kind=kind if isinstance(kind, int) else 5, detail=_detail_of(item))


def _detail_of(item: dict[str, object]) -> str:
    """The type to show beside a member, from wherever the server chose to put it.

    Servers disagree on shape: ty answers ``str`` and pyright answers ``name: str``. The
    label is already in the popup, so the redundant prefix is dropped and both read alike.
    """
    detail = item.get('detail')
    text = detail.strip() if isinstance(detail, str) and detail.strip() else _plain(item.get('documentation'))
    prefix = f'{item.get("label", "")}:'
    return text.removeprefix(prefix).strip() if text.startswith(prefix) else text


def _plain(documentation: object) -> str:
    """Strip a markdown documentation block down to the one line that names the type."""
    text = documentation.get('value', '') if isinstance(documentation, dict) else documentation
    if not isinstance(text, str):
        return ''
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith('```')]
    return lines[0] if lines else ''
