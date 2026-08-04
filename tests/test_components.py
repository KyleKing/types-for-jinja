"""JinjaX component tags, checked against the component's own ``{#def #}`` header.

The attribute grammar here is JinjaX's, read from jinjax 0.65's own preprocessor rather than
from its docs. Two properties matter more than the rest. An undeclared attribute must stay
legal, because JinjaX forwards it to the component as ``attrs`` and nearly every real use
passes ``class`` or ``id``. And a tag that cannot be resolved must be silent, because a project
registering components through a catalog prefix would otherwise be flooded.
"""

from pathlib import Path

from types_for_jinja.components import find_uses, resolve_component, signature
from types_for_jinja.config import Config
from types_for_jinja.header import TemplateHeader, parse_header

from . import checked
from .backends import STUB_DIR
from .checked import reported, write_template
from .configuration import requires_checker

_CARD = '{#def title: str, count: int = 0 #}\n<div>{{ title }}{{ count }}</div>\n'
_DANGER = '{#def msg: str #}\n<p>{{ msg }}</p>\n'
_CONFIG = Config(template_dirs=['components'], out_dir=STUB_DIR)


def _components(root: Path) -> None:
    write_template('components/Card.jinja', _CARD)
    write_template('components/Alert/Danger.jinja', _DANGER)


def test_a_tag_and_its_attributes_are_found():
    """``count=3`` is unquoted and ``class`` is a keyword, so only ``title`` survives."""
    uses = find_uses('<Card title={{ user.name }} count=3 class="wide" />\n')

    assert [use.tag for use in uses] == ['Card']
    assert [(attr.name, attr.expression) for attr in uses[0].attributes] == [('title', 'user.name')]


def test_a_quoted_value_is_a_string_literal():
    uses = find_uses('<Card title="hello" />\n')

    assert [(attr.name, attr.expression) for attr in uses[0].attributes] == [('title', '"hello"')]


def test_an_unquoted_value_is_dropped_the_way_jinjax_drops_it():
    """Jinjax's own attribute pattern only matches quoted or braced values."""
    uses = find_uses('<Card count=3 />\n')

    assert [attr.name for attr in uses[0].attributes] == []


def test_a_bare_attribute_is_true():
    uses = find_uses('<Card open />\n')

    assert [(attr.name, attr.expression) for attr in uses[0].attributes] == [('open', 'True')]


def test_the_vue_like_colon_prefix_makes_a_quoted_value_an_expression():
    uses = find_uses('<Card :count="n + 1" />\n')

    assert [(attr.name, attr.expression) for attr in uses[0].attributes] == [('count', 'n + 1')]


def test_a_hyphenated_name_becomes_an_identifier():
    uses = find_uses('<Card data-id={{ x }} />\n')

    assert [attr.name for attr in uses[0].attributes] == ['data_id']


def test_a_dotted_tag_and_its_line_are_recorded():
    uses = find_uses('<p>one</p>\n<p>two</p>\n<Alert.Danger msg="x" />\n')

    assert [(use.tag, use.lineno) for use in uses] == [('Alert.Danger', 3)]


def test_a_tag_inside_raw_is_not_a_use():
    """A component shown as example markup in docs must not be checked as a call."""
    assert find_uses('{% raw %}<Card title="shown, not used" />{% endraw %}\n') == []


def test_a_greater_than_inside_an_attribute_does_not_end_the_tag():
    uses = find_uses('<Card title={{ a > b }} label="x" />\n')

    assert [attr.name for attr in uses[0].attributes] == ['title', 'label']


def test_a_block_form_component_is_a_use():
    uses = find_uses('<Card title="x">\n  <p>slot content</p>\n</Card>\n')

    assert [(use.tag, use.lineno) for use in uses] == [('Card', 1)]


def test_a_keyword_named_attribute_is_dropped_from_the_call():
    """``class`` is not a legal keyword argument, and it could never be a declared parameter."""
    uses = find_uses('<Card class="wide" id="a" />\n')

    assert 'class=' not in uses[0].call
    assert 'id="a"' in uses[0].call


def test_resolution_finds_a_dotted_component_in_a_subdirectory(project):
    _components(project)

    header = resolve_component('Alert.Danger', [Path('components')])

    assert header is not None
    assert [param.name for param in header.params] == ['msg']


def test_resolution_accepts_the_kebab_case_filename(project):
    """Jinjax looks for both spellings, so a project using kebab filenames still resolves."""
    write_template('components/alert-danger.jinja', _DANGER)

    assert resolve_component('AlertDanger', [Path('components')]) is not None


def test_resolution_accepts_an_index_file_in_a_named_directory(project):
    write_template('components/Card/index.jinja', _CARD)

    assert resolve_component('Card', [Path('components')]) is not None


def test_an_unresolvable_component_reports_nothing(project):
    assert resolve_component('NotAComponent', [Path('components')]) is None


def test_the_signature_ends_in_attrs_so_undeclared_names_stay_legal():
    header = parse_header(_CARD)
    assert header is not None
    use = find_uses('<Card />')[0]

    assert signature(use, header, '_TJAny') == (
        'def tj_component_Card(*, title: str, count: int = 0, **attrs: _TJAny) -> None: ...'
    )


def test_a_component_declaring_nothing_still_accepts_attributes():
    use = find_uses('<Card />')[0]

    assert signature(use, TemplateHeader([], [], 1), '_TJAny') == (
        'def tj_component_Card(**attrs: _TJAny) -> None: ...'
    )


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_missing_required_attribute_is_reported(project):
    _components(project)
    template = write_template('templates/use.html.jinja', '{#def x: str #}\n<Card count={{ 1 }} />\n')

    found = reported(template, _CONFIG)

    assert [entry.line for entry in found] == [2]
    assert found[0].mentions('title')


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_declared_attribute_given_the_wrong_type_is_reported(project):
    _components(project)
    template = write_template('templates/use.html.jinja', '{#def x: str #}\n<Card title="a" count={{ x }} />\n')

    found = reported(template, _CONFIG)

    assert [entry.line for entry in found] == [2]


@requires_checker(checked.DEFAULT_BACKEND)
def test_an_undeclared_attribute_is_not_an_error(project):
    """JinjaX forwards it as an HTML attribute, so reporting it would cry wolf on real templates."""
    _components(project)
    template = write_template(
        'templates/use.html.jinja',
        '{#def x: str #}\n<Card title="a" class="wide" id="main" data-x={{ x }} />\n',
    )

    assert reported(template, _CONFIG) == []


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_correct_use_is_clean(project):
    _components(project)
    template = write_template(
        'templates/use.html.jinja',
        '{#def x: str #}\n<Card title={{ x }} count={{ 2 }} />\n<Alert.Danger msg={{ x }} />\n',
    )

    assert reported(template, _CONFIG) == []


@requires_checker(checked.DEFAULT_BACKEND)
def test_an_unresolvable_tag_leaves_the_rest_of_the_template_checked(project):
    """A catalog-prefixed or unknown tag must not stop the template's own errors being found."""
    _components(project)
    template = write_template(
        'templates/use.html.jinja',
        '{#def x: str #}\n<ui:Button label="a" />\n<Unknown foo="b" />\n<p>{{ x.nope }}</p>\n',
    )

    found = reported(template, _CONFIG)

    assert [entry.line for entry in found] == [4]
    assert found[0].mentions('nope')
