"""Macro body and macro-call checking."""


from types_for_jinja.config import Config

from . import checked
from .backends import STUB_DIR
from .checked import reported, write_template
from .configuration import requires_checker

pytestmark = requires_checker(checked.DEFAULT_BACKEND)

_CONFIG = Config(out_dir=STUB_DIR)

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


def _checked(text: str) -> list[checked.Reported]:
    """Write the macro template into the current project and report what the checker says."""
    return reported(write_template('templates/macro.html.jinja', text), _CONFIG)


def test_macro_body_undefined_var_errors(examples_project):
    assert any(entry.mentions('missing_var') for entry in _checked(_BAD_BODY))


def test_macro_call_missing_arg_errors(examples_project):
    assert [entry.line for entry in _checked(_WRONG_ARITY)] == [5]


def test_macro_correct_usage_clean(examples_project):
    assert _checked(_OK) == []


def test_declared_macro_param_catches_a_bad_attribute_in_the_body(examples_project):
    assert any(entry.mentions('naem') for entry in _checked(_TYPED_BAD_ATTR))


def test_declared_macro_param_is_clean_when_the_attribute_exists(examples_project):
    assert _checked(_TYPED_OK) == []


def test_declared_macro_param_checks_the_call_argument_type(examples_project):
    """A declared parameter type is what makes the call site checkable, not just the body."""
    assert [entry.line for entry in _checked(_TYPED_WRONG_ARG)] == [12]


def test_declared_macro_param_with_a_default_stays_typed(examples_project):
    assert _checked(_TYPED_DEFAULT) == []


def test_undeclared_macro_params_still_check_the_body(examples_project):
    """Without a macro {#def #} block nothing regresses; the params are simply untyped."""
    assert _checked(_OK) == []
