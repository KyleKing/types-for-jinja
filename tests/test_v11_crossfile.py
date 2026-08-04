"""Cross-file checking: extends context flow and imported macros."""

import shutil
from pathlib import Path

import pytest

from types_for_jinja.check import check_file, check_source
from types_for_jinja.config import Config

pytestmark = pytest.mark.skipif(shutil.which('pyright') is None, reason='pyright is required')

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
