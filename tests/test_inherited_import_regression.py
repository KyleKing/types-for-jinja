from pathlib import Path
from textwrap import dedent

import pytest

from types_for_jinja.config import Config
from types_for_jinja.header import parse_header
from types_for_jinja.layout import layout
from types_for_jinja.transpile import transpile

from .backends import STUB_DIR
from .checked import DEFAULT_BACKEND, Reported, reported, write_template
from .configuration import requires_checker


@pytest.mark.parametrize(
    ('directive', 'call', 'expected'),
    [
        (
            '{% import "macros.html" as navigation with context %}',
            '{{ navigation.link("hello") }}',
            'navigation = _TJNS_navigation',
        ),
        (
            '{% from "macros.html" import link with context %}',
            '{{ link("hello") }}',
            'def link(',
        ),
        (
            '{% if true %}{% import "macros.html" as navigation %}{{ navigation.link("hello") }}{% endif %}',
            '',
            'navigation = _TJNS_navigation',
        ),
        (
            '{% macro show(text) %}{% import "macros.html" as navigation %}{{ navigation.link(text) }}{% endmacro %}',
            '{{ show("hello") }}',
            'navigation = _TJNS_navigation',
        ),
    ],
)
def test_inherited_macro_import(
    tmp_path: Path,
    directive: str,
    call: str,
    expected: str,
):
    (tmp_path / 'macros.html').write_text('{% macro link(text) %}{{ text }}{% endmacro %}')
    (tmp_path / 'base.html').write_text(f'{directive}\n{call}\n{{% block content %}}{{% endblock %}}')

    source = dedent(
        """{#def
        title: str
        #}
        {% extends "base.html" %}
        {% block content %}{{ title }}{% endblock %}
        """
    )
    child = tmp_path / 'child.html'
    child.write_text(source)

    header = parse_header(source)
    assert header is not None

    generated = transpile(source, header, template_path=child)

    assert expected in generated.code


_IMPORT_SCOPES = [
    (
        dedent("""\
            {% import "lib.html" as ns %}
            {{ ns.f(x) }}
            """),
        'ns = _TJNS_ns',
    ),
    (
        dedent("""\
            {% block body %}
            {% import "lib.html" as ns %}
            {{ ns.f(x) }}
            {% endblock %}
            """),
        'ns = _TJNS_ns',
    ),
    (
        dedent("""\
            {% if x %}
            {% import "lib.html" as ns %}
            {{ ns.f(x) }}
            {% endif %}
            """),
        'ns = _TJNS_ns',
    ),
    (
        dedent("""\
            {% macro g(x) %}
            {% import "lib.html" as ns %}
            {{ ns.f(x) }}
            {% endmacro %}
            {{ g(x) }}
            """),
        'ns = _TJNS_ns',
    ),
    (
        dedent("""\
            {% extends "base.html" %}
            {% block body %}
            {% import "lib.html" as ns %}
            {{ ns.f(x) }}
            {% endblock %}
            """),
        'ns = _TJNS_ns',
    ),
    (
        dedent("""\
            {% block body %}
            {% from "lib.html" import f %}
            {{ f(x) }}
            {% endblock %}
            """),
        'def f(',
    ),
]


@pytest.mark.parametrize(('body', 'binding'), _IMPORT_SCOPES)
def test_imported_macro_is_bound_in_any_scope(tmp_path: Path, body: str, binding: str):
    """``{% import %}`` and ``{% from %}`` bind their names inside a block, branch, or macro.

    A direct child of the template already became a class or a def. Nested, the stub kept
    only the call and the checker reported the alias as undefined.
    """
    (tmp_path / 'lib.html').write_text('{% macro f(value) %}{{ value }}{% endmacro %}\n')
    (tmp_path / 'base.html').write_text('{% block body %}{% endblock %}\n')
    source = '{#def\nx: str\n#}\n' + body
    page = tmp_path / 'page.html'
    page.write_text(source)
    header = parse_header(source)
    assert header is not None

    generated = transpile(source, header, template_path=page)

    assert generated.code.count(binding) == 1
    assert 'f(' in generated.code


_MACRO = """{% macro f(value) %}
{#def
value: str
#}
{{ value }}
{% endmacro %}
"""

_CALL = """{#def
x: str
#}
{% block body %}
{% import "lib.html" as ns %}
{{ ns.f(x) }}
{% endblock %}
"""


def _check_import(project: Path, call: str) -> list[Reported]:
    (project / 'templates' / 'lib.html').write_text(_MACRO)
    template = write_template('templates/page.html', _CALL.replace('ns.f(x)', call))
    return reported(template, Config(template_dirs=['templates'], out_dir=STUB_DIR))


@requires_checker(DEFAULT_BACKEND)
def test_import_inside_a_block_typechecks(project: Path):
    assert _check_import(project, 'ns.f(x)') == []


@requires_checker(DEFAULT_BACKEND)
def test_import_inside_a_block_still_checks_the_argument(project: Path):
    """A bad argument is a type error on the call."""
    found = _check_import(project, 'ns.f(1)')

    assert found
    assert {entry.line for entry in found} == {6}
    assert not any(entry.mentions('not defined') for entry in found)


_LIB = """{% macro f(value) %}
{#def
value: str
#}
{{ value }}
{% endmacro %}
"""

_INCLUDED_IMPORTS = [
    '{% import "lib.html" as ns %}\n{{ ns.f(x) }}\n',
    '{% macro g(value) %}{% import "lib.html" as ns %}{{ ns.f(value) }}{% endmacro %}\n{{ g(x) }}\n',
    '{#def\nx: str\n#}\n{% import "lib.html" as ns %}\n{{ ns.f(x) }}\n',
]


@pytest.mark.parametrize('included', _INCLUDED_IMPORTS)
def test_include_binds_an_import_from_the_included_template(tmp_path: Path, included: str):
    """``{% include %}`` copies the other template's body, so its ``{% import %}`` has to bind too."""
    (tmp_path / 'lib.html').write_text(_LIB)
    (tmp_path / 'a1.html').write_text(included)
    source = '{#def\nx: str\n#}\n{% include "a1.html" %}\n'
    page = tmp_path / 'a.html'
    page.write_text(source)
    header = parse_header(source)
    assert header is not None

    generated = transpile(source, header, template_path=page)

    assert generated.code.count('ns = _TJNS_ns') == 1
    assert 'ns.f(' in generated.code


def _check_include(project: Path, call: str) -> list[Reported]:
    (project / 'templates' / 'lib.html').write_text(_LIB)
    (project / 'templates' / 'a1.html').write_text(f'{{% import "lib.html" as ns %}}\n{{{{ {call} }}}}\n')
    template = write_template('templates/a.html', '{#def\nx: str\n#}\n{% include "a1.html" %}\n')
    return reported(template, Config(template_dirs=['templates'], out_dir=STUB_DIR))


@requires_checker(DEFAULT_BACKEND)
def test_include_of_an_import_typechecks(project: Path):
    assert _check_include(project, 'ns.f(x)') == []


@requires_checker(DEFAULT_BACKEND)
def test_include_of_an_import_still_checks_the_argument(project: Path):
    """A bad argument is a type error on the include, where the other file's lines are reported."""
    found = _check_include(project, 'ns.f(1)')

    assert found
    assert {entry.line for entry in found} == {4}
    assert not any(entry.mentions('not defined') for entry in found)


@pytest.mark.parametrize('set_first', [False, True])
def test_child_assignment_visible_to_parent(tmp_path: Path, *, set_first: bool):
    """Top-level `{% set %}`s should be visible to a parent template, on either side of extends."""
    (tmp_path / 'base.html').write_text('{{ page_title }}')
    extends = '{% extends "base.html" %}'
    assignment = '{% set page_title = "Hello" %}'
    body = f'{assignment}\n{extends}' if set_first else f'{extends}\n{assignment}'
    source = f'{{#def\nuser_id: int\n#}}\n{body}\n'
    header = parse_header(source)
    assert header is not None

    generated = transpile(source, header, template_path=tmp_path / 'child.html')

    assert generated.code.index('page_title = ') < generated.code.index('_ = page_title')
    aligned = layout(generated, header, 'child_tj_shared')
    assert aligned is not None
    # The parent is checked from the sidecar, which has to keep the literal so the type is str.
    assert aligned.sidecar.index("page_title = 'Hello'") < aligned.sidecar.index('_ = page_title')
    assert 'page_title: _TJAny' not in aligned.sidecar
    assignment_line = source.splitlines().index(assignment)
    assert aligned.code.splitlines()[assignment_line] == "page_title = 'Hello'"


@pytest.mark.parametrize('set_first', [False, True])
@requires_checker('mypy')
def test_parent_sees_the_assigned_type(project: Path, *, set_first: bool):
    """A parent expression is checked against the inferred type, so a bad use is still an error."""
    extends = '{% extends "base.html" %}'
    assignment = '{% set page_title = "Hello" %}'
    body = f'{assignment}\n{extends}' if set_first else f'{extends}\n{assignment}'
    child = f'{{#def\nuser_id: int\n#}}\n{body}\n'
    (project / 'templates' / 'base.html').write_text('{{ page_title + 1 }}\n', encoding='utf-8')
    template = write_template('templates/child.html', child)

    found = reported(template, Config(template_dirs=['templates'], out_dir=STUB_DIR), backend='mypy')

    extends_line = child.splitlines().index(extends) + 1
    assert found
    assert all(entry.line == extends_line for entry in found)
    assert any('str' in entry.message and 'int' in entry.message for entry in found)
    assert not any(entry.mentions('not defined') for entry in found)


@pytest.mark.parametrize('set_first', [False, True])
@requires_checker('mypy')
def test_parent_accepts_a_well_typed_child_assignment(project: Path, *, set_first: bool):
    """A parent may read the assigned name once the child has given it a type."""
    extends = '{% extends "base.html" %}'
    assignment = '{% set page_title = "Hello" %}'
    body = f'{assignment}\n{extends}' if set_first else f'{extends}\n{assignment}'
    child = f'{{#def\nuser_id: int\n#}}\n{body}\n'
    (project / 'templates' / 'base.html').write_text('{{ page_title }}\n', encoding='utf-8')
    template = write_template('templates/child.html', child)

    assert reported(template, Config(template_dirs=['templates'], out_dir=STUB_DIR), backend='mypy') == []
