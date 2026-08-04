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


_TYPED_BAD_ATTR = """{#def
from examples.models import User
user: User
#}
{% macro card(owner) %}
  {#def
  from examples.models import User
  owner: User
  #}
  <p>{{ owner.naem }}</p>
{% endmacro %}
{{ card(user) }}
"""

_TYPED_OK = _TYPED_BAD_ATTR.replace('owner.naem', 'owner.name')

_TYPED_WRONG_ARG = """{#def
from examples.models import User
user: User
#}
{% macro card(owner) %}
  {#def
  from examples.models import User
  owner: User
  #}
  <p>{{ owner.name }}</p>
{% endmacro %}
{{ card('a string') }}
"""

_TYPED_DEFAULT = """{#def
title: str
#}
{% macro card(name, count=3) %}
  {#def
  name: str
  count: int
  #}
  {{ name }}{{ count + 1 }}
{% endmacro %}
{{ card(title) }}
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


def test_declared_macro_param_catches_a_bad_attribute_in_the_body(tmp_path):
    diags = check_file(_write(tmp_path, _TYPED_BAD_ATTR), cache_dir=tmp_path)

    assert any(d.rule == 'reportAttributeAccessIssue' and 'naem' in d.message for d in diags)


def test_declared_macro_param_is_clean_when_the_attribute_exists(tmp_path):
    assert check_file(_write(tmp_path, _TYPED_OK), cache_dir=tmp_path) == []


def test_declared_macro_param_checks_the_call_argument_type(tmp_path):
    diags = check_file(_write(tmp_path, _TYPED_WRONG_ARG), cache_dir=tmp_path)

    assert any(d.rule == 'reportArgumentType' for d in diags)


def test_declared_macro_param_with_a_default_stays_typed(tmp_path):
    assert check_file(_write(tmp_path, _TYPED_DEFAULT), cache_dir=tmp_path) == []


def test_undeclared_macro_params_still_check_the_body(tmp_path):
    """Without a macro {#def #} block nothing regresses; the params are simply untyped."""
    assert check_file(_write(tmp_path, _OK), cache_dir=tmp_path) == []
