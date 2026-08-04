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


@requires_checker(checked.DEFAULT_BACKEND)
def test_jinjas_own_globals_are_declared_when_a_template_names_one(project):
    """``namespace`` and friends come from the Environment, so a template never declares them."""
    template = checked.write_template(
        'templates/ns.html.jinja',
        '{#def\nitems: list[str]\n#}\n{% set ns = namespace(total=0) %}\n'
        '{% for i in items %}{% set ns.total = ns.total + 1 %}{% endfor %}\n'
        '<p>{{ ns.total }}{{ cycler("a").next() }}{{ lipsum() }}{{ joiner() }}</p>\n',
    )

    assert reported(template, Config(out_dir=STUB_DIR)) == []


def test_a_jinja_global_is_only_declared_when_it_is_used():
    """Declaring all of them always would fight a project that declares its own ``namespace``."""
    from types_for_jinja.transpile import transpile  # ruff:ignore[import-outside-top-level]

    source = '{#def\nx: str\n#}\n<p>{{ x }}</p>\n'
    header = parse_header(source)
    assert header is not None

    assert 'namespace' not in transpile(source, header).code


def test_a_project_declaration_replaces_the_injected_jinja_global():
    from types_for_jinja.transpile import transpile  # ruff:ignore[import-outside-top-level]

    source = '{#def\nx: str\n#}\n{% set ns = namespace(n=1) %}\n'
    header = parse_header(source)
    assert header is not None
    config = Config(imports=['from collections.abc import Callable'], globals=[('namespace', 'Callable[..., object]')])

    code = transpile(source, header, config).code

    assert 'namespace: Callable[..., object]' in code
    assert 'namespace: _TJAny' not in code
