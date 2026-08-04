"""One table of every checker invocation the project supports, and how to read it back.

Adding a checker, or a new output format for one already here, means adding an
``Invocation`` and nothing else: ``test_remap`` and ``test_backends`` both drive off this
table. The ``locations`` callable is what makes that work, because it turns each backend's
output shape into the same ``(path, line, column, message)`` tuples.

The fixture project is defined here too, so the templates, the types they import, and the
errors the tests expect stay in one place.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

_TEXT_RE = re.compile(r'^\s*(?:-->\s*)?(?P<path>.+?):(?P<line>\d+):(?P<column>\d+)(?:[\s:]|$)(?P<message>.*)$')
"""The path may contain spaces: Copier and Cookiecutter put Jinja expressions in directory
names, so ``template/{{ module_name }}/__init__.py.jinja`` is a real reported path."""
_ANNOTATION_RE = re.compile(r'^::(?:error|warning)\s+(?P<attrs>[^:]*)::(?P<message>.*)$')

Location = tuple[str, int, int, str]
"""A diagnostic as ``(path, one-based line, one-based column, message)``."""

STUB_DIR = '_jinja_stubs'

MODELS = """\
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    title: str
    done: bool


@dataclass(frozen=True)
class User:
    name: str
    items: list[Item]
"""

TEMPLATE = """\
{#def
from app.models import User
user: User
#}
<h1>Hello {{ user.naem }}</h1>
<ul>
{% for item in user.items %}
  <li>{{ item.titel }} by {{ author }}</li>
{% endfor %}
</ul>
"""

TEMPLATE_PATH = 'templates/page.html.jinja'

MACROS = """\
{% macro row(item) %}
{#def
from app.models import Item
item: Item
#}
<td>{{ item.title }}</td>
{% endmacro %}
"""

IMPORTS_AND_FILTERS = """\
{#def
from app.models import User
user: User
#}
{% from 'macros.html.jinja' import row %}
<p>{{ user.items | length }}</p>
<p>{{ user.name | upper }}</p>
{% for item in user.items | sort %}{{ row(item) }}{% endfor %}
"""
"""Exercises the two generated imports a stub can carry: the filter module and a sidecar.

Both are bare top-level module names, so this is the regression test for the claim that a
project needs no search-path configuration beyond pointing its checker at the tree.
"""

FILTERS_PATH = 'templates/filtered.html.jinja'

PROJECT_ERROR = """\
def broken() -> int:
    return 'not an int'
"""
"""A real type error in real project code, which ``remap`` must leave exactly as it found it."""

PROJECT_ERROR_PATH = 'app/broken.py'

EXPECTED_LINES = (5, 8, 8)
"""Template lines the fixture is built to fail on: ``naem``, ``titel``, and ``author``."""


def write_project(root: Path) -> None:
    """Lay the fixture project out under ``root``."""
    (root / 'app').mkdir(parents=True, exist_ok=True)
    (root / 'templates').mkdir(parents=True, exist_ok=True)
    (root / 'app/__init__.py').write_text('', encoding='utf-8')
    (root / 'app/models.py').write_text(MODELS, encoding='utf-8')
    (root / PROJECT_ERROR_PATH).write_text(PROJECT_ERROR, encoding='utf-8')
    (root / TEMPLATE_PATH).write_text(TEMPLATE, encoding='utf-8')
    (root / FILTERS_PATH).write_text(IMPORTS_AND_FILTERS, encoding='utf-8')
    (root / 'templates/macros.html.jinja').write_text(MACROS, encoding='utf-8')
    (root / 'pyrightconfig.json').write_text(json.dumps({'include': ['.'], 'extraPaths': ['.']}), encoding='utf-8')


@dataclass(frozen=True)
class Invocation:
    """One checker, run one way, plus how to pull locations out of what it prints."""

    backend: str
    label: str
    argv: tuple[str, ...]
    locations: Callable[[str], list[Location]]
    env: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Test id, so a failure names the backend and the format that broke."""
        return f'{self.backend}-{self.label}'


def _text_locations(payload: str) -> list[Location]:
    matches = (_TEXT_RE.match(line) for line in payload.splitlines())
    return [
        (match.group('path'), int(match.group('line')), int(match.group('column')), match.group('message'))
        for match in matches
        if match
    ]


def _pyright_json_locations(payload: str) -> list[Location]:
    entries = json.loads(payload)['generalDiagnostics']
    return [
        (
            entry['file'],
            entry['range']['start']['line'] + 1,
            entry['range']['start']['character'] + 1,
            entry['message'],
        )
        for entry in entries
        if entry['severity'] == 'error'
    ]


def _mypy_json_locations(payload: str) -> list[Location]:
    entries = (json.loads(line) for line in payload.splitlines() if line.strip())
    return [(entry['file'], entry['line'], entry['column'] + 1, entry['message']) for entry in entries]


def _gitlab_locations(payload: str) -> list[Location]:
    return [
        (
            entry['location']['path'],
            entry['location']['positions']['begin']['line'],
            entry['location']['positions']['begin']['column'],
            entry['description'],
        )
        for entry in json.loads(payload)
    ]


def _github_locations(payload: str) -> list[Location]:
    found: list[Location] = []
    for line in payload.splitlines():
        match = _ANNOTATION_RE.match(line)
        if match is None:
            continue
        attrs = dict(pair.split('=', 1) for pair in match.group('attrs').split(',') if '=' in pair)
        found.append((attrs['file'], int(attrs['line']), int(attrs['col']), match.group('message')))
    return found


INVOCATIONS: tuple[Invocation, ...] = (
    Invocation('pyright', 'text', ('pyright',), _text_locations),
    Invocation('pyright', 'json', ('pyright', '--outputjson'), _pyright_json_locations),
    Invocation('ty', 'full', ('ty', 'check', '--extra-search-path', '.', '.'), _text_locations),
    Invocation(
        'ty',
        'concise',
        ('ty', 'check', '--output-format', 'concise', '--extra-search-path', '.', '.'),
        _text_locations,
    ),
    Invocation(
        'ty',
        'gitlab',
        ('ty', 'check', '--output-format', 'gitlab', '--extra-search-path', '.', '.'),
        _gitlab_locations,
    ),
    Invocation(
        'ty',
        'github',
        ('ty', 'check', '--output-format', 'github', '--extra-search-path', '.', '.'),
        _github_locations,
    ),
    Invocation(
        'mypy',
        'text',
        ('mypy', '--no-error-summary', '--ignore-missing-imports', '--no-color-output', '--show-column-numbers', '.'),
        _text_locations,
        env={'MYPYPATH': '.'},
    ),
    Invocation(
        'mypy',
        'json',
        ('mypy', '--output', 'json', '--ignore-missing-imports', '.'),
        _mypy_json_locations,
        env={'MYPYPATH': '.'},
    ),
)


def capture(invocation: Invocation, cwd: Path) -> str:
    """Run ``invocation`` in ``cwd`` and return its stdout."""
    result = subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true]
        [shutil.which(invocation.argv[0]) or invocation.argv[0], *invocation.argv[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **invocation.env},
    )
    return result.stdout


def template_locations(found: list[Location], template: str) -> Iterator[Location]:
    """Only the locations naming ``template``, however the backend spelled the path."""
    return (entry for entry in found if Path(entry[0]).as_posix().endswith(template))
