"""Rewrite a type checker's output so it names the template instead of the generated stub.

Lines are already right: the aligned stub puts generated line N on template line N. Only
the path and the column need work, and neither can be fixed inside the stub because no
Python checker honours anything like Go's ``//line`` directive.

The path comes from the manifest. The column is recovered by taking the identifier the
checker pointed at in the stub and finding it again on the template line, which works
because an aligned stub keeps template expressions nearly verbatim. When the search misses,
the stub's own column is kept rather than invented.

Any location outside the stub tree passes through untouched, so piping a whole-project run
through ``remap`` leaves the project's own diagnostics exactly as the checker wrote them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from types_for_jinja import manifest

_MARKER_RE = re.compile(r'#\s*L(\d+)\s*$')
_LOCATION_RE = re.compile(
    r'^(?P<indent>\s*(?:-->\s*)?)(?P<path>.+?\.pyi?):(?P<line>\d+)(?::(?P<column>\d+))?(?=[\s:]|$)',
)
"""``path:line[:col]`` at the head of a line, which is where ty, mypy, and pyright all put it."""

_BARE_PATH_RE = re.compile(r'^(?P<indent>\s*)(?P<path>.+?\.pyi?)\s*$')
_SOURCE_RE = re.compile(r'^(?P<gutter>\s*)(?P<number>\d+)(?P<bar>\s*\|\s?)(?P<text>.*)$')
_CARET_RE = re.compile(r'^(?P<gutter>\s*\|\s*)(?P<carets>\^+)(?P<rest>.*)$')
_ANNOTATION_RE = re.compile(r'^::(?P<level>error|warning|notice)\s+(?P<attrs>[^:]*)::(?P<message>.*)$')
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')

FORMATS = ('auto', 'text', 'github', 'pyright-json', 'mypy-json', 'ty-gitlab')
"""Output shapes ``remap`` understands. ``auto`` picks one by looking at the payload.

``text`` covers ty's ``concise`` and default ``full``, mypy's default, and pyright's
default, because all four head the line with ``path:line[:col]``. ty's ``full`` also prints
the offending source line, which ``text`` replaces with the template's own so the snippet
and the path above it describe the same file.
"""


@dataclass(frozen=True)
class Location:
    """A diagnostic position, in one-based line and column."""

    path: Path
    line: int
    column: int


class Remapper:
    """Translate positions inside a generated stub tree back to their templates.

    Built once per run and reused across every diagnostic, because it caches the stub and
    template text it reads.
    """

    def __init__(self, out_dir: Path, root: Path | None = None) -> None:
        """Read the manifest in ``out_dir``; ``root`` is what relative paths resolve against."""
        self._out_dir = out_dir
        self._root = root or Path.cwd()
        self._manifest = manifest.load(out_dir)
        self._text: dict[Path, list[str]] = {}

    def locate(self, path: str, line: int, column: int) -> Location | None:
        """Return the template position for a stub position, or ``None`` if it is not a stub."""
        key = self._key(path)
        if key is None:
            return None
        template = self._manifest.template_for(key)
        if template is None:
            return None
        fixed = self._manifest.fixed_line(key)
        if fixed is not None:
            return Location(path=template, line=fixed, column=1)
        stub_lines = self._lines(self._out_dir / key)
        template_line = line if self._manifest.aligned(key) else _marked_line(stub_lines, line)
        if template_line is None:
            return None
        return Location(
            path=template,
            line=template_line,
            column=_recover_column(_at(stub_lines, line), self.template_line(template, template_line), column),
        )

    def template_line(self, template: Path, line: int) -> str:
        """The text of one template line, empty when it cannot be read."""
        return _at(self._lines(template), line)

    def _key(self, path: str) -> PurePosixPath | None:
        """The manifest key for a reported path, whatever it was reported relative to.

        A checker invoked from the project root names ``_jinja_stubs/pages/x.py`` while one
        invoked inside the tree names ``pages/x.py``, and both have to resolve.
        """
        candidate = Path(path)
        bases = [self._root] if candidate.is_absolute() else [self._root, self._out_dir]
        out_dir = self._out_dir.resolve()
        for base in bases:
            resolved = (base / candidate).resolve()
            if resolved.is_relative_to(out_dir):
                key = PurePosixPath(resolved.relative_to(out_dir))
                if key in self._manifest.entries:
                    return key
        return None

    def _lines(self, path: Path) -> list[str]:
        if path not in self._text:
            try:
                self._text[path] = path.read_text(encoding='utf-8').splitlines()
            except OSError:
                self._text[path] = []
        return self._text[path]


def _at(lines: list[str], one_based: int) -> str:
    return lines[one_based - 1] if 0 < one_based <= len(lines) else ''


def _recover_column(stub_line: str, template_line: str, column: int) -> int:
    """Find the identifier the checker pointed at again on the template line.

    The stub column is kept when the token cannot be read or cannot be found, because a
    column that is merely stale beats one that is invented.
    """
    token = _token_at(stub_line, column)
    if not token:
        return column
    found = _nearest(template_line, token, column)
    return column if found is None else found


def _token_at(text: str, column: int) -> str:
    match = _IDENTIFIER.match(text, max(column - 1, 0))
    return match.group(0) if match else ''


def _nearest(text: str, token: str, column: int) -> int | None:
    """The one-based column of the occurrence of ``token`` closest to where the stub put it."""
    starts = [match.start() for match in re.finditer(rf'\b{re.escape(token)}\b', text)]
    if not starts:
        return None
    return min(starts, key=lambda start: abs(start - (column - 1))) + 1


def _marked_line(stub_lines: list[str], line: int) -> int | None:
    """Read the template line from the nearest ``# L<n>`` marker at or above ``line``."""
    for index in range(min(line, len(stub_lines)) - 1, -1, -1):
        match = _MARKER_RE.search(stub_lines[index])
        if match:
            return int(match.group(1))
    return None


def detect(payload: str) -> str:
    """Guess which shape ``payload`` is, falling back to the line-oriented text formats."""
    stripped = payload.lstrip()
    if stripped.startswith('['):
        return 'ty-gitlab'
    if stripped.startswith('::'):
        return 'github'
    if not stripped.startswith('{'):
        return 'text'
    try:
        parsed = json.loads(payload)
    except ValueError:
        return 'mypy-json'
    if not isinstance(parsed, dict):
        return 'text'
    return 'pyright-json' if 'generalDiagnostics' in parsed else 'mypy-json'


def remap(payload: str, remapper: Remapper, fmt: str = 'auto') -> str:
    """Rewrite every stub location in ``payload``, leaving everything else alone."""
    chosen = detect(payload) if fmt == 'auto' else fmt
    return _HANDLERS[chosen](payload, remapper)


@dataclass(frozen=True)
class _Snippet:
    """What a remapped location tells us about the source excerpt printed under it."""

    stub_line: int
    template_line: int
    template_text: str
    shift: int


def _remap_text(payload: str, remapper: Remapper) -> str:
    lines: list[str] = []
    snippet: _Snippet | None = None
    for line in payload.split('\n'):
        rewritten, snippet = _text_line(line, remapper, snippet)
        lines.append(rewritten)
    return '\n'.join(lines)


def _text_line(line: str, remapper: Remapper, snippet: _Snippet | None) -> tuple[str, _Snippet | None]:
    match = _LOCATION_RE.match(line)
    if match is not None:
        return _location_line(line, match, remapper)
    if snippet is not None:
        return _snippet_line(line, snippet)
    return _bare_path_line(line, remapper), None


def _location_line(line: str, match: re.Match[str], remapper: Remapper) -> tuple[str, _Snippet | None]:
    raw_column = match.group('column')
    stub_line, stub_column = int(match.group('line')), int(raw_column or 1)
    located = remapper.locate(match.group('path'), stub_line, stub_column)
    if located is None:
        return line, None
    position = f'{located.line}' if raw_column is None else f'{located.line}:{located.column}'
    rewritten = f'{match.group("indent")}{located.path}:{position}{line[match.end() :]}'
    snippet = _Snippet(
        stub_line=stub_line,
        template_line=located.line,
        template_text=remapper.template_line(located.path, located.line),
        shift=located.column - stub_column,
    )
    return rewritten, snippet


def _snippet_line(line: str, snippet: _Snippet) -> tuple[str, _Snippet | None]:
    """Swap ty's excerpt of the stub for the template line, and slide the caret to match."""
    source = _SOURCE_RE.match(line)
    if source is not None and int(source.group('number')) == snippet.stub_line:
        number = str(snippet.template_line).rjust(len(source.group('number')))
        return f'{source.group("gutter")}{number}{source.group("bar")}{snippet.template_text}', snippet
    caret = _CARET_RE.match(line)
    if caret is None:
        return line, snippet
    gutter = caret.group('gutter') + ' ' * max(snippet.shift, 0)
    return f'{gutter}{caret.group("carets")}{caret.group("rest")}', None


def _bare_path_line(line: str, remapper: Remapper) -> str:
    """Pyright's text output heads each file's diagnostics with the path on its own line."""
    match = _BARE_PATH_RE.match(line)
    if match is None:
        return line
    located = remapper.locate(match.group('path'), 1, 1)
    return line if located is None else f'{match.group("indent")}{located.path}'


def _remap_github(payload: str, remapper: Remapper) -> str:
    """GitHub Actions annotations, which is how a template error lands on the PR diff."""
    return '\n'.join(_annotation_line(line, remapper) for line in payload.split('\n'))


def _annotation_line(line: str, remapper: Remapper) -> str:
    match = _ANNOTATION_RE.match(line)
    if match is None:
        return _remap_text(line, remapper)
    attrs = dict(pair.split('=', 1) for pair in match.group('attrs').split(',') if '=' in pair)
    if 'file' not in attrs:
        return line
    stub_line, stub_column = int(attrs.get('line', 1)), int(attrs.get('col', 1))
    located = remapper.locate(attrs['file'], stub_line, stub_column)
    if located is None:
        return line
    attrs.update(file=str(located.path), line=str(located.line), col=str(located.column))
    if 'endLine' in attrs:
        attrs['endLine'] = str(int(attrs['endLine']) + located.line - stub_line)
    if 'endColumn' in attrs:
        attrs['endColumn'] = str(int(attrs['endColumn']) + located.column - stub_column)
    rendered = ','.join(f'{key}={value}' for key, value in attrs.items())
    return f'::{match.group("level")} {rendered}::{_remap_text(match.group("message"), remapper)}'


def _remap_pyright_json(payload: str, remapper: Remapper) -> str:
    parsed = json.loads(payload)
    for entry in parsed.get('generalDiagnostics', []):
        _apply_pyright(entry, remapper)
    return json.dumps(parsed, indent=4) + '\n'


def _apply_pyright(entry: dict[str, Any], remapper: Remapper) -> None:
    """Pyright counts lines and characters from zero in JSON but from one in text."""
    start = entry.get('range', {}).get('start')
    if not isinstance(start, dict) or 'file' not in entry:
        return
    stub_line, stub_character = int(start.get('line', 0)), int(start.get('character', 0))
    located = remapper.locate(str(entry['file']), stub_line + 1, stub_character + 1)
    if located is None:
        return
    entry['file'] = str(located.path)
    line_shift, character_shift = located.line - 1 - stub_line, located.column - 1 - stub_character
    for position in (start, entry['range'].get('end')):
        if not isinstance(position, dict):
            continue
        position['line'] = int(position.get('line', stub_line)) + line_shift
        position['character'] = int(position.get('character', stub_character)) + character_shift


def _remap_mypy_json(payload: str, remapper: Remapper) -> str:
    """Mypy writes one JSON object per line, so a blank or partial line is not an error."""
    return '\n'.join(_mypy_line(line, remapper) for line in payload.split('\n'))


def _mypy_line(line: str, remapper: Remapper) -> str:
    if not line.strip():
        return line
    try:
        entry = json.loads(line)
    except ValueError:
        return line
    if not isinstance(entry, dict) or 'file' not in entry:
        return line
    located = remapper.locate(str(entry['file']), int(entry.get('line', 1)), int(entry.get('column', 0)) + 1)
    if located is None:
        return line
    entry['file'] = str(located.path)
    shift = located.line - int(entry.get('line', 1))
    entry['line'] = located.line
    if 'column' in entry:
        entry['column'] = located.column - 1
    if 'end_line' in entry:
        entry['end_line'] = int(entry['end_line']) + shift
    return json.dumps(entry)


def _remap_ty_gitlab(payload: str, remapper: Remapper) -> str:
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        return payload
    for entry in parsed:
        _apply_gitlab(entry, remapper)
    return json.dumps(parsed, indent=2) + '\n'


def _apply_gitlab(entry: Any, remapper: Remapper) -> None:
    """GitLab allows either a bare line range or full positions, and ty emits positions."""
    location = entry.get('location') if isinstance(entry, dict) else None
    if not isinstance(location, dict) or 'path' not in location:
        return
    positions = _table(location.get('positions'))
    begin = _table(positions.get('begin'))
    lines = _table(location.get('lines'))
    stub_line = int(begin.get('line', lines.get('begin', 1)))
    stub_column = int(begin.get('column', 1))
    located = remapper.locate(str(location['path']), stub_line, stub_column)
    if located is None:
        return
    location['path'] = str(located.path)
    if lines:
        lines['begin'] = located.line
        if 'end' in lines:
            lines['end'] = int(lines['end']) + located.line - stub_line
    if begin:
        _shift_positions(positions, located, stub_line, stub_column)


def _table(value: Any) -> dict[str, Any]:
    """A JSON sub-object as a mapping, empty when the payload put something else there."""
    return value if isinstance(value, dict) else {}


def _shift_positions(positions: dict[str, Any], located: Location, stub_line: int, stub_column: int) -> None:
    for key in ('begin', 'end'):
        position = _table(positions.get(key))
        if not position:
            continue
        position['line'] = int(position.get('line', stub_line)) + located.line - stub_line
        if 'column' in position:
            position['column'] = int(position['column']) + located.column - stub_column


_HANDLERS = {
    'github': _remap_github,
    'mypy-json': _remap_mypy_json,
    'pyright-json': _remap_pyright_json,
    'text': _remap_text,
    'ty-gitlab': _remap_ty_gitlab,
}
