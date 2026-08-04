"""Ask pyright what members a template expression has.

Attribute completion needs the declared type resolved, not just named, and resolving
types is the one thing this project deliberately does not do itself. So it asks the same
checker the diagnostics come from: build a probe stub that binds the template's context
and ends in the expression the cursor is on, hand it to ``pyright-langserver``, and
forward the completions back.

The stub is never written to disk and never executed; it is sent over the wire as an
unsaved document. The server is started on first use and reused, because starting one
costs far more than a query.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_PROBE_NAME = '_tj_probe.py'
_TIMEOUT_SECONDS = 10.0

__all__ = ['Member', 'MemberResolver']


@dataclass(frozen=True)
class Member:
    """One attribute or method offered on a template expression."""

    name: str
    kind: int
    detail: str


class MemberResolver:
    """A reusable ``pyright-langserver`` connection scoped to one project root.

    Not thread-safe on its own; ``members`` serialises callers behind a lock. Call
    ``shutdown`` when finished, after which the resolver must not be reused.
    """

    def __init__(self, root: Path) -> None:
        """Bind the resolver to ``root``; no server starts until the first query."""
        self._root = root.resolve()
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
        uri = (self._root / _PROBE_NAME).as_uri()
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
        return _to_members(result)

    def _ensure_started(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        executable = shutil.which('pyright-langserver')
        if executable is None:
            message = 'pyright-langserver not found on PATH'
            raise OSError(message)
        self._process = subprocess.Popen(  # ruff:ignore[subprocess-without-shell-equals-true]
            [executable, '--stdio'],
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
                'capabilities': {},
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


def _to_members(result: object) -> list[Member]:
    items = result.get('items', []) if isinstance(result, dict) else result
    if not isinstance(items, list):
        return []
    members = []
    for raw_item in items:
        if not isinstance(raw_item, dict) or 'label' not in raw_item:
            continue
        item = cast('dict[str, object]', raw_item)
        label = str(item['label'])
        if label.startswith('__'):
            continue
        kind = item.get('kind', 5)
        detail = str(item.get('detail', ''))
        members.append(Member(name=label, kind=kind if isinstance(kind, int) else 5, detail=detail))
    return members
