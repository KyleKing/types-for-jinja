"""Tests for header validation, which runs before any checker backend."""

from pathlib import Path

from types_for_jinja.check import check_source
from types_for_jinja.header import header_errors, parse_header

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


def test_malformed_header_short_circuits_the_checker(tmp_path):
    diagnostics = check_source(_COLLAPSED, Path('t.html.jinja'), cache_dir=tmp_path)

    assert [(d.line, d.code) for d in diagnostics] == [(1, 'TJ011')]
