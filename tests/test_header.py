"""Tests for header validation, which runs before any checker backend."""

from pathlib import Path

from types_for_jinja.config import Config
from types_for_jinja.generate import diagnose
from types_for_jinja.header import Param, header_errors, parse_defs, parse_header

_COLLAPSED = '{#def from examples.models import User user: User #}\n<h1>{{ user.name }}</h1>\n'


def test_sound_header_has_no_errors():
    header = parse_header('{#def\nfrom examples.models import User\nuser: User\n#}\n')

    assert header is not None
    assert header_errors(header) == []


def test_collapsed_header_is_reported_as_malformed():
    header = parse_header(_COLLAPSED)

    assert header is not None
    assert 'malformed import' in header_errors(header)[0]


def test_a_declaration_python_would_reject_is_reported():
    header = parse_header('{#def\nuser name: str\n#}\n')

    assert header is not None
    assert 'not a valid parameter list' in header_errors(header)[0]
    assert header.params == []


def test_unparsable_annotation_is_reported():
    header = parse_header('{#def\nuser: list[\n#}\n')

    assert header is not None
    assert 'not a valid parameter list' in header_errors(header)[0]


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
    assert header.params == [Param('name', 'str')]


def test_jinjax_one_line_form_with_defaults_and_untyped_names():
    """JinjaX writes the whole context on one line, commas between, defaults allowed."""
    header = parse_header('{#def action, method: str = "post", count: int = 0 #}\n')

    assert header is not None
    assert header_errors(header) == []
    assert header.params == [
        Param('action', None, None),
        Param('method', 'str', "'post'"),
        Param('count', 'int', '0'),
    ]


def test_a_declaration_per_line_still_reads_the_same():
    header = parse_header('{#def\nfrom myapp.models import User\nuser: User\nitems: list[str]\n#}\n')

    assert header is not None
    assert header.imports == ['from myapp.models import User']
    assert header.params == [Param('user', 'User'), Param('items', 'list[str]')]


def test_the_two_forms_mix():
    """A project midway through adopting either spelling must not be punished for it."""
    header = parse_header('{#def\nuser: User\naction, method: str = "post"\n#}\n')

    assert header is not None
    assert [param.name for param in header.params] == ['user', 'action', 'method']
    assert header.params[2].default == "'post'"


def test_a_defaulted_declaration_may_precede_an_undefaulted_one():
    """Generated parameters are keyword-only, so the template orders them however it reads best."""
    header = parse_header('{#def\ncurrent_route: str = "habits"\nhabits: list[HabitInfo]\n#}\n')

    assert header is not None
    assert header_errors(header) == []
    assert header.params == [Param('current_route', 'str', "'habits'"), Param('habits', 'list[HabitInfo]')]


def test_a_trailing_comma_per_line_is_tolerated():
    header = parse_header('{#def\nuser: User,\nitems: list[str],\n#}\n')

    assert header is not None
    assert [param.name for param in header.params] == ['user', 'items']


def test_an_untyped_name_reports_no_annotation_rather_than_guessing():
    """Each emitter picks its own stand-in, so the parser must not bake one in."""
    header = parse_header('{#def action #}\n')

    assert header is not None
    assert header.params == [Param('action')]
    assert header.params[0].annotated('_TJAny') == 'action: _TJAny'
    assert header.params[0].annotated('Any') == 'action: Any'
