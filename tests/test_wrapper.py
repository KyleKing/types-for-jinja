"""Tests for the typed render wrapper: codegen shape plus Level-2 enforcement."""

import ast
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation
from pydantic import ValidationError

from examples.runtime import wrapper_beartype, wrapper_pydantic
from examples.runtime.models import Profile
from typed_jinja.header import parse_header
from typed_jinja.wrapper import generate_wrapper

_TEMPLATE = Path('examples/runtime/templates/profile.html.jinja')


def _header():
    header = parse_header(_TEMPLATE.read_text(encoding='utf-8'))
    assert header is not None
    return header


@pytest.mark.parametrize('validator', ['none', 'beartype', 'pydantic'])
def test_generated_source_is_well_formed(validator):
    source = generate_wrapper(_header(), 'profile.html.jinja', validator=validator)

    ast.parse(source)
    assert 'def render_profile(*, profile: Profile) -> Markup:' in source


def test_beartype_wrapper_renders_and_guards():
    rendered = wrapper_beartype.render_profile(profile=Profile('Ada', 'ada@x.io', 36))
    assert 'Ada' in rendered

    with pytest.raises(BeartypeCallHintParamViolation):
        wrapper_beartype.render_profile(profile='not-a-profile')


def test_pydantic_wrapper_coerces_and_rejects():
    rendered = wrapper_pydantic.render_profile(profile={'name': 'Bo', 'email': 'bo@x.io', 'age': '40'})
    assert 'Bo' in rendered
    assert 'Age: 40' in rendered

    with pytest.raises(ValidationError):
        wrapper_pydantic.render_profile(profile={'name': 'Bo', 'email': 'bo@x.io'})
