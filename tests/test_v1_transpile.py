"""Transpiler resilience on real-world Jinja constructs (no pyright needed)."""

from typed_jinja.header import parse_header
from typed_jinja.transpile import transpile


def _code(source):
    header = parse_header(source)
    assert header is not None
    return transpile(source, header).code


def test_macro_is_modeled_with_params():
    src = '{#def x: int #}\n{% macro card(title) %}{{ title }}{% endmacro %}\n{{ card(x) }}'

    code = _code(src)

    assert 'def _render(x: int)' in code
    assert 'def card(title)' in code


def test_with_block_binds_local():
    code = _code('{#def x: int #}\n{% with y = x %}{{ y }}{% endwith %}')

    assert 'y = x' in code


def test_extends_and_block_do_not_crash():
    code = _code('{#def x: int #}\n{% extends "base.html" %}{% block body %}{{ x }}{% endblock %}')

    assert '_ = x' in code


def test_include_does_not_crash():
    assert '_render' in _code('{#def x: int #}\n{% include "other.html" %}{{ x }}')


def test_filter_result_is_any():
    assert '_tj_any(items)' in _code('{#def items: list[int] #}\n{{ items | length }}')


def test_slice_is_emitted():
    assert 's[:4]' in _code('{#def s: str #}\n{{ s[:4] }}')
