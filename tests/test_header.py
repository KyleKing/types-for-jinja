"""Tests for header validation, which runs before any checker backend."""

from pathlib import Path

from types_for_jinja.config import Config
from types_for_jinja.generate import diagnose
from types_for_jinja.header import header_errors, parse_defs, parse_header

_COLLAPSED = '{#def from examples.models import User user: User #}\n<h1>{{ user.name }}</h1>\n'


def test_sound_header_has_no_errors():
    header = parse_header('{#def\nfrom examples.models import User\nuser: User\n#}\n')

    assert header is not None
    assert header_errors(header) == []


def test_collapsed_header_is_reported_as_malformed():
    header = parse_header(_COLLAPSED)

    assert header is not None
    assert 'malformed import' in header_errors(header)[0]


def test_non_identifier_param_is_reported():
    header = parse_header('{#def\nuser name: str\n#}\n')

    assert header is not None
    assert 'is not an identifier' in header_errors(header)[0]


def test_unparsable_annotation_is_reported():
    header = parse_header('{#def\nuser: list[\n#}\n')

    assert header is not None
    assert 'malformed annotation' in header_errors(header)[0]


def test_malformed_header_is_reported_before_any_stub_is_written():
    """A collapsed header still matches the pattern but no longer parses, so nothing downstream runs."""
    diagnostics = diagnose(_COLLAPSED, Path('t.html.jinja'), Config())

    assert [(d.line, d.severity) for d in diagnostics] == [(1, 'error')]
    assert 'malformed' in diagnostics[0].message


def test_macros_only_file_has_no_template_header():
    """A block after the first {% macro %} types that macro, not the file."""
    source = '{% macro field(label) %}\n{#def\nlabel: str\n#}\n{{ label }}\n{% endmacro %}\n'

    assert parse_header(source) is None
    assert len(parse_defs(source)) == 1


def test_template_header_still_wins_when_it_comes_first():
    source = '{#def\nname: str\n#}\n{% macro field(label) %}\n{#def\nlabel: str\n#}\n{% endmacro %}\n'

    header = parse_header(source)

    assert header is not None
    assert header.params == [('name', 'str')]
