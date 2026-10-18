"""Checks of the real yak-shears templates and filter handling.

These are the templates the README shows, so a regression here is one a reader would hit.
"""

from pathlib import Path
from textwrap import dedent

import pytest

from types_for_jinja.config import Config
from types_for_jinja.header import parse_header
from types_for_jinja.transpile import transpile

from . import checked
from .backends import STUB_DIR
from .checked import reported, write_template
from .configuration import requires_checker

pytestmark = requires_checker(checked.DEFAULT_BACKEND)

_RW = Path('examples/realworld')
_CONFIG = Config(
    imports=['from collections.abc import Callable'],
    globals=[('static_url', 'Callable[[str], str]'), ('current_route', 'str')],
    out_dir=STUB_DIR,
)


@pytest.mark.parametrize('name', ['error.html.jinja', 'login.html.jinja', 'yaks_index.html.jinja'])
def test_realworld_template_clean(name, examples_project):
    assert reported(_RW / name, _CONFIG) == []


def test_filter_chain_no_false_positive(project):
    """A filtered arithmetic expression keeps a real type rather than reporting on correct code."""
    template = write_template(
        'templates/f.html.jinja',
        '{#def count: int #}\n{% set fill = ([count, 500] | min) / 500 %}\n<p>{{ fill }}</p>\n',
    )

    assert reported(template, Config(out_dir=STUB_DIR)) == []


def test_default_filter_accepts_an_undefined_name(project):
    """``| default`` substitutes a missing name, which is valid even under StrictUndefined.

    The result is the default value, so ``default("bar") + 1`` is a type error. A name the
    template does declare is still accepted.
    """
    header = '{#def\ntitle: str\n#}\n'
    clean = write_template('templates/defaulted.html.jinja', header + '{{ foo | default("bar") }}\n')
    known = write_template('templates/defaulted_known.html.jinja', header + '{{ title | default("bar") }}\n')
    bad = write_template('templates/defaulted_bad.html.jinja', header + '{{ foo | default("bar") + 1 }}\n')

    assert reported(clean, Config(out_dir=STUB_DIR)) == []
    assert reported(known, Config(out_dir=STUB_DIR)) == []
    found = reported(bad, Config(out_dir=STUB_DIR))
    assert any('+' in entry.message and entry.mentions('bar') for entry in found)
    assert not any(entry.mentions('not defined') for entry in found)


def test_default_acceptance(project):
    """Scope rules around ``default``: only a name the template never binds is replaced."""
    config = Config(out_dir=STUB_DIR)

    declared = write_template(
        'templates/default_declared.html.jinja',
        dedent(
            """\
            {#def
            count: int
            #}
            {{ count | default("no") + 1 }}
            """
        ),
    )
    assert reported(declared, config) == []

    bound = write_template(
        'templates/default_bound.html.jinja',
        dedent(
            """\
            {#def
            items: list[int]
            #}
            {% set n = 1 %}
            {{ n | default("no") + 1 }}
            {% for item in items %}
            {{ item | default("no") + 1 }}
            {% endfor %}
            {% macro card(name) %}
            {{ name | default("no") + 1 }}
            {% endmacro %}
            """
        ),
    )
    assert reported(bound, config) == []
    assert "_tj_f_default(name, 'no')" in _stub(bound.read_text(encoding='utf-8'))

    literals = dedent(
        """\
        {#def
        title: str
        #}
        {{ foo | d(1) }}
        {{ foo | default }}
        """
    )
    assert reported(write_template('templates/default_literals.html.jinja', literals), config) == []
    literal_code = _stub(literals)
    assert '_ = 1' in literal_code
    assert "_ = ''" in literal_code

    attribute = write_template(
        'templates/default_attribute.html.jinja',
        dedent(
            """\
            {#def
            title: str
            #}
            {{ foo.bar | default("x") }}
            """
        ),
    )
    attribute_errors = reported(attribute, config)
    assert any(entry.mentions('foo') for entry in attribute_errors)

    extra = write_template(
        'templates/default_extra.html.jinja',
        dedent(
            """\
            {#def
            title: str
            #}
            {{ foo | default("bar", bogus) }}
            """
        ),
    )
    extra_errors = reported(extra, config)
    assert any(entry.mentions('bogus') for entry in extra_errors)
    assert not any(entry.mentions('foo') for entry in extra_errors)

    write_template(
        'templates/default_base.html',
        dedent(
            """\
            {% set n = 1 %}
            {{ n | default("no") + 1 }}
            """
        ),
    )
    child = write_template(
        'templates/default_child.html.jinja',
        dedent(
            """\
            {#def
            title: str
            #}
            {% extends "default_base.html" %}
            """
        ),
    )
    assert reported(child, config) == []

    write_template(
        'templates/default_card.html',
        dedent(
            """\
            {#def
            xs: list[int]
            #}
            {{ xs | default("no") + 1 }}
            {{ secret | default("no") }}
            """
        ),
    )
    page = write_template(
        'templates/default_page.html.jinja',
        dedent(
            """\
            {#def
            title: str
            xs: list[int]
            #}
            {% set secret = 1 %}
            {% include "default_card.html" %}
            """
        ),
    )
    assert reported(page, config) == []


def _stub(source: str) -> str:
    header = parse_header(source)
    assert header is not None
    return transpile(source, header).code


def test_typo_still_caught_in_realworld(examples_project):
    source = (Path('examples/realworld/yaks_index.html.jinja')).read_text(encoding='utf-8')
    template = write_template('examples/realworld/typo.html.jinja', source.replace('info.preview', 'info.prevew', 1))

    found = reported(template, _CONFIG)

    assert any(entry.mentions('prevew') for entry in found)
