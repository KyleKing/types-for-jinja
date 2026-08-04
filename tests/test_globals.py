"""Tests for Environment-globals configuration.

Without a declaration, a template calling ``static_url()`` is a false positive, and a tool
that cries wolf gets uninstalled.
"""

from pathlib import Path

from types_for_jinja.config import Config, load_config
from types_for_jinja.header import parse_header
from types_for_jinja.transpile import transpile

from . import checked
from .backends import STUB_DIR
from .checked import reported
from .configuration import requires_checker

_USES_GLOBALS = Path('examples/templates/uses_globals.html.jinja')


def test_load_config_reads_project_globals():
    config = load_config(Path.cwd())

    assert 'from collections.abc import Callable' in config.imports
    assert ('static_url', 'Callable[[str], str]') in config.globals
    assert ('current_route', 'str') in config.globals


def test_transpile_without_config_omits_globals():
    source = _USES_GLOBALS.read_text(encoding='utf-8')
    header = parse_header(source)
    assert header is not None

    code = transpile(source, header, config=Config()).code

    assert 'static_url' not in code.split('def _render')[0]


def test_transpile_with_config_declares_globals():
    source = _USES_GLOBALS.read_text(encoding='utf-8')
    header = parse_header(source)
    assert header is not None

    code = transpile(source, header, load_config(Path.cwd())).code

    assert 'static_url: Callable[[str], str]' in code


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_declared_global_is_not_a_false_positive(examples_project):
    config = Config(
        imports=['from collections.abc import Callable'],
        globals=[('static_url', 'Callable[[str], str]'), ('current_route', 'str')],
        out_dir=STUB_DIR,
    )

    assert reported(_USES_GLOBALS, config) == []


@requires_checker(checked.DEFAULT_BACKEND)
def test_an_undeclared_global_is_reported(examples_project):
    """Proves the declaration is what silences it, rather than the checker never looking."""
    found = reported(_USES_GLOBALS, Config(out_dir=STUB_DIR))

    assert any(entry.mentions('static_url') for entry in found)
