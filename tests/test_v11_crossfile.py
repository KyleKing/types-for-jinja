"""Cross-file checking: extends context flow and imported macros.

A cross-file error is reported at the ``{% extends %}`` or ``{% include %}`` line of the file
being checked, because the other file's own line numbers mean nothing here.
"""

from pathlib import Path

from types_for_jinja.config import Config

from . import checked
from .backends import STUB_DIR
from .checked import reported, write_template
from .configuration import requires_checker

pytestmark = requires_checker(checked.DEFAULT_BACKEND)

_CROSSFILE = Path('examples/crossfile')
_CONFIG = Config(
    imports=['from collections.abc import Callable'],
    globals=[('static_url', 'Callable[[str], str]'), ('current_route', 'str')],
    template_dirs=['examples/crossfile'],
    out_dir=STUB_DIR,
)


def test_extends_child_clean(examples_project):
    assert reported(_CROSSFILE / 'child.html.jinja', _CONFIG) == []


def test_extends_missing_base_context_errors(examples_project):
    template = write_template(
        'examples/crossfile/bad_child.html.jinja',
        '{#def\nmessage: str\n#}\n{% extends "base.html.jinja" %}\n'
        '{% block content %}<p>{{ message }}</p>{% endblock %}\n',
    )

    found = reported(template, _CONFIG)

    assert any(entry.mentions('page_heading') for entry in found)


def test_multi_level_extends_chain_is_clean(examples_project):
    assert reported(_CROSSFILE / 'deep_child.html.jinja', _CONFIG) == []


def test_multi_level_extends_reaches_the_grandparent_context(examples_project):
    """``page_heading`` is declared two templates up, in base, not in mid."""
    template = write_template(
        'examples/crossfile/deep_bad.html.jinja',
        '{#def\nmessage: str\n#}\n{% extends "mid.html.jinja" %}\n',
    )

    found = reported(template, _CONFIG)

    assert any(entry.mentions('page_heading') for entry in found)


def test_include_clean(examples_project):
    assert reported(_CROSSFILE / 'uses_include.html.jinja', _CONFIG) == []


def test_include_missing_context_errors(examples_project):
    template = write_template(
        'examples/crossfile/bad_include.html.jinja',
        '{#def\nmessage: str\n#}\n<main>{% include "_sidebar.html.jinja" %}</main>\n',
    )

    found = reported(template, _CONFIG)

    assert any(entry.mentions('page_heading') for entry in found)


def test_cross_file_error_points_at_the_local_tag(examples_project):
    """The included file's own line numbers mean nothing in the file being checked."""
    template = write_template(
        'examples/crossfile/bad_line.html.jinja',
        '{#def\nmessage: str\n#}\n<p>{{ message }}</p>\n<main>{% include "_sidebar.html.jinja" %}</main>\n',
    )

    found = reported(template, _CONFIG)

    assert [entry.line for entry in found] == [5]


def test_include_cycle_terminates(project):
    template = write_template(
        'templates/loop.html.jinja',
        '{#def\nx: str\n#}\n{{ x }}{% include "loop.html.jinja" %}\n',
    )

    assert reported(template, Config(template_dirs=['templates'], out_dir=STUB_DIR)) == []


def test_from_import_clean(examples_project):
    assert reported(_CROSSFILE / 'uses_macros.html.jinja', _CONFIG) == []


def test_from_import_wrong_arity_errors(examples_project):
    """A macro called with too few arguments is a call error wherever the macro lives."""
    template = write_template(
        'examples/crossfile/bad_arity.html.jinja',
        '{#def\nname: str\n#}\n{% from "macros.html.jinja" import field %}\n{{ field(\'only-one\') }}\n',
    )

    found = reported(template, _CONFIG)

    assert [entry.line for entry in found] == [5]
