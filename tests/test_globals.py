"""Tests for Environment-globals configuration."""

from pathlib import Path

from types_for_jinja.check import check_file
from types_for_jinja.config import Config, load_config
from types_for_jinja.header import parse_header
from types_for_jinja.transpile import transpile

from .configuration import requires_pyright

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


@requires_pyright
def test_check_globals_template_is_clean(tmp_path):
    assert check_file(_USES_GLOBALS, cache_dir=tmp_path) == []
