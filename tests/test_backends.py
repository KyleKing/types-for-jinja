"""Every checker must read the generated stubs the same way.

The bring-your-own-checker path only works if pyright, ty, and mypy agree on which template
lines are wrong. These tests run whichever of the three are installed over the same generated
tree and compare them against each other.

Invocations come from ``tests/backends.py`` and are all rooted at the project root, which is
where a real project runs its checker. An earlier version of this file ran the checkers from
inside the stub tree with an explicit ``extraPaths``, and that configuration hid a real
failure: the generated imports did not resolve under a plainly configured checker.
"""

import shutil
from pathlib import Path

import pytest

from types_for_jinja.config import Config, load_config
from types_for_jinja.generate import generate, write
from types_for_jinja.remap import Remapper, remap
from types_for_jinja.suppress import STYLES

from . import backends
from .backends import INVOCATIONS, STUB_DIR, TEMPLATE_PATH, capture
from .configuration import requires_checker

_EXAMPLES = Path('examples')
_BAD = 'examples/templates/greeting_bad.html.jinja'
_EXPECTED_EXAMPLE_ERRORS = ((_BAD, 5), (_BAD, 11), (_BAD, 11))
"""The three errors ``examples/`` is written to contain: ``naem``, ``titel``, and ``author``."""

_SUPPRESSED = """\
{#def
name: str
#}
<p>{{ name.bad }}</p>{# type: ignore #}
<p>{{ name.worse }}</p>
"""

_ONE_PER_BACKEND = tuple({entry.backend: entry for entry in INVOCATIONS}.values())
"""One invocation per checker, for the tests that compare checkers rather than formats."""


def _params(invocations):
    return [pytest.param(entry, marks=requires_checker(entry.backend), id=entry.id) for entry in invocations]


def _template_errors(invocation, root: Path, stub_dir: Path | None = None) -> list[tuple[str, int]]:
    """Every reported template location, as ``(template path, line)`` pairs."""
    stubs = stub_dir if stub_dir is not None else Path(STUB_DIR)
    remapper = Remapper(stubs, root=root)
    found = invocation.locations(remap(capture(invocation, root), remapper))
    return sorted(
        (Path(path).as_posix(), line) for path, line, _, _ in found if Path(path).as_posix().endswith('.jinja')
    )


@pytest.fixture
def fixture_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    backends.write_project(tmp_path)
    write(generate(sorted(Path('templates').glob('*.jinja')), Path(STUB_DIR)))
    return tmp_path


@pytest.mark.parametrize('invocation', _params(INVOCATIONS))
def test_every_invocation_finds_the_same_template_errors(invocation, fixture_project):
    """Any disagreement means switching checkers or output formats changes what a project sees."""
    expected = [(TEMPLATE_PATH, line) for line in backends.EXPECTED_LINES]

    assert _template_errors(invocation, fixture_project) == expected


@pytest.fixture
def examples_project(tmp_path, monkeypatch):
    """The repo's own ``examples/`` copied out, so a checker can run over it without polluting it.

    The project's ``[tool.types_for_jinja]`` globals come along, because without them
    ``static_url()`` reads as an undefined variable and the examples grow errors they are not
    written to have.
    """
    config = load_config(Path.cwd())
    shutil.copytree(_EXAMPLES, tmp_path / 'examples', ignore=shutil.ignore_patterns('__pycache__'))
    (tmp_path / 'pyrightconfig.json').write_text('{"include": ["."], "extraPaths": ["."]}', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    write(generate(sorted(Path('examples').rglob('*.html.jinja')), Path(STUB_DIR), config))
    return tmp_path


@pytest.mark.parametrize('invocation', _params(_ONE_PER_BACKEND))
def test_the_shipped_examples_report_their_three_known_errors(invocation, examples_project):
    """Runs the repo's own ``examples/``, so the templates users are shown stay honest."""
    assert _template_errors(invocation, examples_project) == sorted(_EXPECTED_EXAMPLE_ERRORS)


@pytest.mark.parametrize('style', sorted(STYLES))
def test_every_style_suppresses_in_the_checker_it_names(style, tmp_path, monkeypatch):
    """A style emitting a comment its own checker ignores would report a suppressed line."""
    backend = 'pyright' if style == 'portable' else style
    if shutil.which(backend) is None:
        pytest.skip(f'{backend} is required')
    monkeypatch.chdir(tmp_path)
    backends.write_project(tmp_path)
    template = Path('templates/suppressed.html.jinja')
    template.write_text(_SUPPRESSED, encoding='utf-8')
    write(generate([template], Path(STUB_DIR), Config(suppression=style)))
    invocation = next(entry for entry in _ONE_PER_BACKEND if entry.backend == backend)

    lines = {line for path, line in _template_errors(invocation, tmp_path) if 'suppressed' in path}

    assert lines == {5}


@requires_checker('mypy')
def test_a_checker_specific_style_only_suppresses_for_that_checker(tmp_path, monkeypatch):
    """Proves the styles differ: `# pyright: ignore` means nothing to mypy, so pinning a checker matters."""
    monkeypatch.chdir(tmp_path)
    backends.write_project(tmp_path)
    template = Path('templates/suppressed.html.jinja')
    template.write_text(_SUPPRESSED, encoding='utf-8')
    write(generate([template], Path(STUB_DIR), Config(suppression='pyright')))
    invocation = next(entry for entry in _ONE_PER_BACKEND if entry.backend == 'mypy')

    lines = {line for path, line in _template_errors(invocation, tmp_path) if 'suppressed' in path}

    assert lines == {4, 5}
