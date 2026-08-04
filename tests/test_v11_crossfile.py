"""Cross-file checking: extends context flow and imported macros."""

from pathlib import Path

from types_for_jinja.check import check_file, check_source
from types_for_jinja.config import Config

from .configuration import requires_pyright

pytestmark = requires_pyright

_CROSSFILE = Path('examples/crossfile')
_CONFIG = Config(
    imports=['from collections.abc import Callable'],
    globals=[('static_url', 'Callable[[str], str]'), ('current_route', 'str')],
    template_dirs=['examples/crossfile'],
)


def test_extends_child_clean(tmp_path):
    assert check_file(_CROSSFILE / 'child.html.jinja', cache_dir=tmp_path) == []


def test_extends_missing_base_context_errors(tmp_path):
    child = """{#def
message: str
#}
{% extends "base.html.jinja" %}
{% block content %}<p>{{ message }}</p>{% endblock %}
"""
    diags = check_source(child, Path('bad.html.jinja'), cache_dir=tmp_path, config=_CONFIG)

    assert any(d.rule == 'reportUndefinedVariable' and 'page_heading' in d.message for d in diags)


def test_multi_level_extends_chain_is_clean(tmp_path):
    assert check_file(_CROSSFILE / 'deep_child.html.jinja', cache_dir=tmp_path) == []


def test_multi_level_extends_reaches_the_grandparent_context(tmp_path):
    """`page_heading` is declared two templates up, in base, not in mid."""
    child = """{#def
message: str
#}
{% extends "mid.html.jinja" %}
"""
    diags = check_source(child, Path('deep_bad.html.jinja'), cache_dir=tmp_path, config=_CONFIG)

    assert any(d.rule == 'reportUndefinedVariable' and 'page_heading' in d.message for d in diags)


def test_include_clean(tmp_path):
    assert check_file(_CROSSFILE / 'uses_include.html.jinja', cache_dir=tmp_path) == []


def test_include_missing_context_errors(tmp_path):
    template = """{#def
message: str
#}
<main>{% include "_sidebar.html.jinja" %}</main>
"""
    diags = check_source(template, Path('bad.html.jinja'), cache_dir=tmp_path, config=_CONFIG)

    assert any(d.rule == 'reportUndefinedVariable' and 'page_heading' in d.message for d in diags)


def test_cross_file_error_points_at_the_local_tag(tmp_path):
    """The included file's own line numbers mean nothing in the file being checked."""
    template = """{#def
message: str
#}
<p>{{ message }}</p>
<main>{% include "_sidebar.html.jinja" %}</main>
"""
    diags = check_source(template, Path('bad.html.jinja'), cache_dir=tmp_path, config=_CONFIG)

    assert [d.line for d in diags] == [5]


def test_include_cycle_terminates(tmp_path):
    template = tmp_path / 'loop.html.jinja'
    template.write_text('{#def\nx: str\n#}\n{{ x }}{% include "loop.html.jinja" %}\n', encoding='utf-8')

    assert check_file(template, cache_dir=tmp_path) == []


def test_from_import_clean(tmp_path):
    assert check_file(_CROSSFILE / 'uses_macros.html.jinja', cache_dir=tmp_path) == []


def test_from_import_wrong_arity_errors(tmp_path):
    template = """{#def
name: str
#}
{% from "macros.html.jinja" import field %}
{{ field('only-one') }}
"""
    diags = check_source(template, Path('bad.html.jinja'), cache_dir=tmp_path, config=_CONFIG)

    assert any(d.rule == 'reportCallIssue' for d in diags)
