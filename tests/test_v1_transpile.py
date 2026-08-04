"""Transpiler resilience on real-world Jinja constructs (no pyright needed)."""

from types_for_jinja.header import parse_header
from types_for_jinja.transpile import transpile


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


def test_known_filter_uses_its_declared_signature():
    code = _code('{#def items: list[int] #}\n{{ items | length }}')

    assert 'from ._tj_filters import _tj_f_length' in code
    assert '_tj_f_length(items)' in code


def test_unknown_filter_still_falls_back_to_any():
    code = _code('{#def items: list[int] #}\n{{ items | my_custom_filter }}')

    assert '_tj_any(items)' in code
    assert '_tj_filters' not in code


def test_test_expression_uses_the_boolean_signature():
    code = _code('{#def x: int #}\n{% if x is divisibleby 3 %}y{% endif %}')

    assert 'from ._tj_filters import _tj_test' in code
    assert '_tj_test(x, 3)' in code


def test_slice_is_emitted():
    assert 's[:4]' in _code('{#def s: str #}\n{{ s[:4] }}')
