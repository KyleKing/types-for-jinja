"""Every checker must read the generated stubs the same way `types-for-jinja check` does.

The bring-your-own-checker path only works if pyright, ty, and mypy agree on which
template lines are wrong. These tests run whichever of the three are installed over the
same generated tree and compare them against each other and against the checker's own
diagnostics.
"""

import json
import os
import re
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
from pathlib import Path

import pytest

from types_for_jinja.check import check_file
from types_for_jinja.config import Config
from types_for_jinja.generate import generate, write
from types_for_jinja.suppress import STYLES

from .configuration import requires_checker

_EXAMPLES = Path('examples')
_BAD = _EXAMPLES / 'templates' / 'greeting_bad.html.jinja'
_CONCISE_RE = re.compile(r'^(?P<file>\S+?):(?P<line>\d+):(?:\d+:)?\s*error')
"""ty reports ``file:line:column: error[rule]``; mypy omits the column unless asked for it."""
_BACKENDS = [pytest.param(name, marks=requires_checker(name)) for name in ('pyright', 'ty', 'mypy')]

_SUPPRESSED = """\
{#def
name: str
#}
<p>{{ name.bad }}</p>{# type: ignore #}
<p>{{ name.worse }}</p>
"""


def _run(backend: str, out_dir: Path, root: str) -> list[tuple[str, int]]:
    """Errors ``backend`` reports over ``out_dir``, as (stub filename, template line) pairs."""
    if backend == 'pyright':
        return _run_pyright(out_dir, root)
    argv = {
        'mypy': ['mypy', '--no-error-summary', '--ignore-missing-imports', '--no-color-output', '.'],
        'ty': ['ty', 'check', '--output-format', 'concise', '--extra-search-path', root, '.'],
    }[backend]
    env = {'MYPYPATH': f'{root}:.'} if backend == 'mypy' else None
    matches = (_CONCISE_RE.match(line) for line in _capture(argv, out_dir, env).splitlines())
    return sorted((Path(m.group('file')).name, int(m.group('line'))) for m in matches if m)


def _run_pyright(out_dir: Path, root: str) -> list[tuple[str, int]]:
    (out_dir / 'pyrightconfig.json').write_text(
        json.dumps({'include': ['.'], 'extraPaths': [root, '.']}),
        encoding='utf-8',
    )
    raw = json.loads(_capture(['pyright', '--outputjson'], out_dir))['generalDiagnostics']
    return sorted(
        (Path(entry['file']).name, entry['range']['start']['line'] + 1) for entry in raw if entry['severity'] == 'error'
    )


def _capture(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true]
        [shutil.which(argv[0]) or argv[0], *argv[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return result.stdout


def _example_stubs(out_dir: Path) -> Path:
    write(generate(sorted(_EXAMPLES.rglob('*.html.jinja')), out_dir))
    return out_dir


@pytest.mark.parametrize('backend', _BACKENDS)
def test_backend_reports_what_the_checker_reports(backend, tmp_path):
    root = str(Path.cwd().resolve())
    reported = _run(backend, _example_stubs(tmp_path / 'stubs'), root)
    expected = sorted(('greeting_bad_html_jinja.py', diag.line) for diag in check_file(_BAD, cache_dir=tmp_path / 'c'))

    assert reported == expected


@requires_checker('ty')
@requires_checker('mypy')
def test_ty_and_mypy_agree(tmp_path):
    """One disagreement means a project switching checkers sees different template errors."""
    root = str(Path.cwd().resolve())
    out_dir = _example_stubs(tmp_path / 'stubs')

    assert _run('ty', out_dir, root) == _run('mypy', out_dir, root)


@pytest.mark.parametrize('style', sorted(STYLES))
def test_every_style_suppresses_in_the_checker_it_names(style, tmp_path, monkeypatch):
    """A style emitting a comment its own checker ignores would report a suppressed line."""
    backend = 'pyright' if style == 'portable' else style
    if shutil.which(backend) is None:
        pytest.skip(f'{backend} is required')
    monkeypatch.chdir(tmp_path)
    template = Path('page.html.jinja')
    template.write_text(_SUPPRESSED, encoding='utf-8')
    write(generate([template], Path('stubs'), Config(suppression=style)))

    lines = {line for _, line in _run(backend, tmp_path / 'stubs', str(tmp_path))}

    assert lines == {5}


@requires_checker('mypy')
def test_a_checker_specific_style_only_suppresses_for_that_checker(tmp_path, monkeypatch):
    """Proves the styles differ: `# pyright: ignore` means nothing to mypy, so pinning a checker matters."""
    monkeypatch.chdir(tmp_path)
    template = Path('page.html.jinja')
    template.write_text(_SUPPRESSED, encoding='utf-8')
    write(generate([template], Path('stubs'), Config(suppression='pyright')))

    lines = {line for _, line in _run('mypy', tmp_path / 'stubs', str(tmp_path))}

    assert lines == {4, 5}
