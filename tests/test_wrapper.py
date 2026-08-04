"""Tests for the typed render wrapper: codegen shape plus Level-2 enforcement."""

import ast
from pathlib import Path
from typing import cast

import pytest
from beartype.roar import BeartypeCallHintParamViolation
from pydantic import ValidationError

from examples.runtime import wrapper_beartype, wrapper_pydantic
from examples.runtime.models import Profile
from types_for_jinja.config import Config, WrapperConfig
from types_for_jinja.header import parse_header
from types_for_jinja.wrapper import ReturnStyle, build_wrappers, generate_wrapper, template_name

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


def test_return_type_swaps_the_annotation_and_the_call():
    style = ReturnStyle('HTMLResponse', 'from starlette.responses import HTMLResponse')

    source = generate_wrapper(_header(), 'profile.html.jinja', returns=style)

    ast.parse(source)
    assert 'from starlette.responses import HTMLResponse' in source
    assert 'def render_profile(*, profile: Profile) -> HTMLResponse:' in source
    assert 'return HTMLResponse(_env.get_template' in source
    assert 'Markup' not in source


def test_build_wrappers_mirrors_the_template_tree(tmp_path):
    wrappers = build_wrappers([_TEMPLATE], tmp_path, Config())

    generated = tmp_path / 'examples/runtime/templates/profile_html_jinja.py'
    assert wrappers.skipped == []
    assert generated in wrappers.files
    assert tmp_path / 'examples/runtime/__init__.py' in wrappers.files


def test_build_wrappers_reads_the_project_config(tmp_path):
    config = Config(
        template_dirs=['examples/runtime/templates'],
        wrapper=WrapperConfig(
            env_import='from examples.runtime.env import env as _env',
            validator='beartype',
        ),
    )

    source = next(text for path, text in build_wrappers([_TEMPLATE], tmp_path, config).files.items() if path.suffix)

    assert '@beartype' in source
    assert 'from examples.runtime.env import env as _env' in source


def test_template_name_is_relative_to_the_configured_template_dir():
    config = Config(template_dirs=['examples/runtime/templates'])

    assert template_name(_TEMPLATE, config) == 'profile.html.jinja'


def test_headerless_template_is_skipped(tmp_path):
    template = tmp_path / 'plain.html.jinja'
    template.write_text('<p>no header</p>\n', encoding='utf-8')

    wrappers = build_wrappers([template], tmp_path / 'out', Config())

    assert wrappers.files == {}
    assert 'no {#def ... #} type header' in wrappers.skipped[0][1]


def test_unknown_validator_is_rejected(tmp_path):
    config = Config(wrapper=WrapperConfig(validator='mypy'))

    with pytest.raises(ValueError, match='unknown validator'):
        build_wrappers([_TEMPLATE], tmp_path, config)


def test_beartype_wrapper_renders_and_guards():
    rendered = wrapper_beartype.render_profile(profile=Profile('Ada', 'ada@x.io', 36))
    assert 'Ada' in rendered

    with pytest.raises(BeartypeCallHintParamViolation):
        wrapper_beartype.render_profile(profile=cast('Profile', 'not-a-profile'))


def test_pydantic_wrapper_coerces_and_rejects():
    rendered = wrapper_pydantic.render_profile(profile=cast('Profile', {'name': 'Bo', 'email': 'bo@x.io', 'age': '40'}))
    assert 'Bo' in rendered
    assert 'Age: 40' in rendered

    with pytest.raises(ValidationError):
        wrapper_pydantic.render_profile(profile=cast('Profile', {'name': 'Bo', 'email': 'bo@x.io'}))


_JINJAX = '{#def action, method: str = "post", count: int = 0 #}\n<form>{{ action }}</form>\n'


def _jinjax_header():
    header = parse_header(_JINJAX)
    assert header is not None
    return header


def test_a_jinjax_header_carries_its_defaults_into_the_signature():
    """A default declared in the template belongs in the wrapper, or every call must repeat it."""
    source = generate_wrapper(_jinjax_header(), 'form.html.jinja')

    ast.parse(source)
    assert "def render_form(*, action: Any, method: str = 'post', count: int = 0) -> Markup:" in source


def test_an_untyped_name_becomes_Any_with_the_import_it_needs():  # noqa: N802
    source = generate_wrapper(_jinjax_header(), 'form.html.jinja')

    assert 'from typing import Any' in source
    ast.parse(source)


def test_a_fully_typed_header_does_not_import_Any():  # noqa: N802
    """The import is only correct when something needs it, and an unused one is a lint failure."""
    source = generate_wrapper(_header(), 'profile.html.jinja')

    assert 'from typing import Any' not in source


def test_a_default_survives_the_pydantic_validator():
    source = generate_wrapper(_jinjax_header(), 'form.html.jinja', validator='pydantic')

    ast.parse(source)
    assert '_ta_method = TypeAdapter(str)' in source
    assert '_ta_action = TypeAdapter(Any)' in source
