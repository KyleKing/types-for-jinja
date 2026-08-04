"""Tests for context-name completion and hover."""

from types_for_jinja.complete import context_names, cursor_context, describe, word_at
from types_for_jinja.config import Config
from types_for_jinja.header import parse_header
from types_for_jinja.lsp import complete, hover_text

_SOURCE = """{#def
from examples.models import User
user: User
#}
{% set greeting = 'hi' %}
{% for item in user.items %}
  <li>{{ item.title }}</li>
{% endfor %}
<p>{{ greeting }}</p>
"""


def _names(line, config=None):
    header = parse_header(_SOURCE)
    assert header is not None
    return {entry.name: entry for entry in context_names(_SOURCE, header, config, line=line)}


def test_header_parameter_is_always_visible():
    assert _names(9)['user'].type_str == 'User'


def test_loop_target_is_visible_inside_the_loop_only():
    assert 'item' in _names(7)
    assert 'item' not in _names(9)


def test_loop_helper_is_offered_inside_the_loop():
    assert _names(7)['loop'].origin == 'loop helper'


def test_set_target_is_visible_after_its_line():
    assert 'greeting' in _names(9)
    assert 'greeting' not in _names(4)


def test_configured_globals_are_offered():
    config = Config(globals=[('static_url', 'Callable[[str], str]')])

    assert _names(9, config)['static_url'].origin == 'global'


def test_macro_parameters_are_visible_in_the_macro_body():
    source = '{#def\nx: int\n#}\n{% macro card(title, href) %}\n  {{ title }}\n{% endmacro %}\n'
    header = parse_header(source)
    assert header is not None

    inside = {entry.name for entry in context_names(source, header, line=5)}
    outside = {entry.name for entry in context_names(source, header, line=7)}

    assert {'card', 'title', 'href'} <= inside
    assert 'title' not in outside
    assert 'card' in outside


def test_describe_includes_the_declared_type():
    assert describe(_names(9)['user']) == 'user: User (parameter)'


def test_cursor_inside_an_output_tag_is_an_expression():
    assert cursor_context('<p>{{ us', 8).in_expression


def test_cursor_outside_a_tag_is_not_an_expression():
    assert not cursor_context('<p>{{ user }}</p', 15).in_expression


def test_cursor_in_a_comment_is_not_an_expression():
    assert not cursor_context('{# user ', 8).in_expression


def test_cursor_after_a_dot_reports_the_base_expression():
    context = cursor_context('{{ user.address.ci', 18)

    assert context.attribute_of == 'user.address'
    assert context.prefix == 'ci'


def test_word_at_finds_the_identifier_under_the_cursor():
    assert word_at('<p>{{ greeting }}</p>', 8) == 'greeting'
    assert word_at('<p>plain</p>', 1) == 'p'


def test_complete_offers_names_and_details():
    items = complete(_SOURCE, 6, 10)

    assert 'item' in {item.label for item in items}
    assert 'user: User (parameter)' in {item.detail for item in items}


def test_complete_is_silent_outside_an_expression():
    assert complete(_SOURCE, 6, 2) == []


def test_complete_defers_attribute_access_to_the_checker():
    assert complete('{#def\nuser: str\n#}\n{{ user. }}\n', 3, 8) == []


def test_hover_reports_the_declared_type():
    assert hover_text(_SOURCE, 8, 8) == 'greeting (set)'


def test_hover_is_none_off_a_name():
    assert hover_text(_SOURCE, 8, 0) is None


def test_names_are_empty_without_a_header():
    assert complete('<p>{{ user }}</p>\n', 0, 9) == []


def test_half_typed_expression_still_completes():
    """The delimiter is open, so the template does not parse; completion must still work."""
    typed = _SOURCE.replace('  <li>{{ item.title }}</li>\n', '  <li>{{ item.title }}</li>\n  <p>{{ it\n')

    labels = {item.label for item in complete(typed, 7, 9)}

    assert {'item', 'loop', 'user'} <= labels


def test_half_typed_tag_falls_back_to_the_header():
    """`{% fo` closes to an unknown tag, so only header and globals survive."""
    typed = _SOURCE + '{% fo\n'

    labels = {item.label for item in complete(typed, 9, 5)}

    assert 'user' in labels


def test_unparsable_template_still_offers_header_names():
    broken = '{#def\nuser: str\n#}\n{% for %}\n{{ us\n'

    assert 'user' in {item.label for item in complete(broken, 4, 5)}
