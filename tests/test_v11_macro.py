"""Macro body and macro-call checking."""

from pathlib import Path

from types_for_jinja.check import check_file

from .configuration import requires_pyright

pytestmark = requires_pyright

_BAD_BODY = """{#def
title: str
#}
{% macro card(name, count) %}{{ name }} {{ missing_var }}{% endmacro %}
{{ card(title, 1) }}
"""

_WRONG_ARITY = """{#def
title: str
#}
{% macro card(name, count) %}{{ name }}{{ count }}{% endmacro %}
{{ card(title) }}
"""

_OK = """{#def
title: str
#}
{% macro card(name, count) %}{{ name }}{{ count }}{% endmacro %}
{{ card(title, 2) }}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'macro.html.jinja'
    path.write_text(text, encoding='utf-8')
    return path


def test_macro_body_undefined_var_errors(tmp_path):
    diags = check_file(_write(tmp_path, _BAD_BODY), cache_dir=tmp_path)

    assert any(d.rule == 'reportUndefinedVariable' and 'missing_var' in d.message for d in diags)


def test_macro_call_missing_arg_errors(tmp_path):
    diags = check_file(_write(tmp_path, _WRONG_ARITY), cache_dir=tmp_path)

    assert any(d.rule == 'reportCallIssue' for d in diags)


def test_macro_correct_usage_clean(tmp_path):
    assert check_file(_write(tmp_path, _OK), cache_dir=tmp_path) == []
