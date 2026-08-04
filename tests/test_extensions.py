"""Jinja extension tags, which need their extension loaded before Jinja will parse them.

Without the declaration the template does not parse at all, so it is skipped and none of its
real errors are found. That makes this a coverage feature rather than a convenience: declaring
the extension is what lets the rest of the template be checked.
"""

from pathlib import Path

import pytest

from types_for_jinja.cli import _EXIT_BAD_CONFIG, main
from types_for_jinja.config import EXTENSIONS, Config, load_config

from . import checked
from .backends import STUB_DIR
from .checked import reported, skipped, write_template
from .configuration import requires_checker

_TAGS = {
    'do': '{% do items.append(1) %}\n',
    'i18n': '{% trans %}Hello{% endtrans %}\n',
    'loopcontrols': '{% for i in items %}{% break %}{% endfor %}\n',
}


def _template(body: str) -> str:
    return f'{{#def\nitems: list[int]\n#}}\n{body}'


@pytest.mark.parametrize('extension', sorted(_TAGS))
def test_the_tag_does_not_parse_until_the_extension_is_declared(extension):
    source = _template(_TAGS[extension])

    assert 'syntax error' in skipped(source, Path('t.html.jinja'), Config())[0].message


@pytest.mark.parametrize('extension', sorted(_TAGS))
def test_declaring_the_extension_makes_the_tag_parse(extension):
    source = _template(_TAGS[extension])

    config = Config(extensions=[extension], out_dir=STUB_DIR)

    assert skipped(source, Path('t.html.jinja'), config) == []


def test_an_unknown_extension_is_rejected_at_config_load(tmp_path):
    """Accepting the name would leave the template failing to parse with no hint why."""
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja]\nextensions = ["nope"]\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='unknown extensions'):
        load_config(tmp_path)


def test_only_jinja2s_own_extensions_are_offered():
    """A project-defined extension would mean importing project code to parse a template."""
    assert set(EXTENSIONS) == {'debug', 'do', 'i18n', 'loopcontrols'}


def test_the_cli_reports_a_bad_setting_without_a_traceback(project, capsys):
    (project / 'pyproject.toml').write_text(
        '[tool.types_for_jinja]\nextensions = ["nope"]\n',
        encoding='utf-8',
    )

    code = main(['generate', 'templates'])

    assert code == _EXIT_BAD_CONFIG
    assert 'unknown extensions' in capsys.readouterr().err


@requires_checker(checked.DEFAULT_BACKEND)
def test_i18n_injects_the_names_it_gives_a_template(project):
    """A template gets ``_`` and ``gettext`` from the extension without ever declaring them."""
    template = write_template(
        'templates/i18n.html.jinja',
        '{#def\nname: str\n#}\n<p>{{ _("hi") }}{{ gettext("x") }}{{ ngettext("a", "b", 1) }}</p>\n',
    )

    assert reported(template, Config(extensions=['i18n'], out_dir=STUB_DIR)) == []


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_declared_global_wins_over_the_injected_one(project):
    """Declaring ``_`` yourself must not produce a duplicate binding, and your type must hold."""
    template = write_template('templates/i18n.html.jinja', '{#def\nname: str\n#}\n<p>{{ _("hi").nope }}</p>\n')
    config = Config(
        extensions=['i18n'],
        imports=['from collections.abc import Callable'],
        globals=[('_', 'Callable[[str], str]')],
        out_dir=STUB_DIR,
    )

    found = reported(template, config)

    assert [entry.line for entry in found] == [4]
    assert found[0].mentions('str')


@requires_checker(checked.DEFAULT_BACKEND)
def test_the_rest_of_the_template_is_checked_once_the_tag_parses(project):
    """The point of the setting: the template's own errors were invisible while it was skipped."""
    template = write_template(
        'templates/i18n.html.jinja',
        '{#def\nname: str\n#}\n{% trans %}Hello{% endtrans %}\n<p>{{ name.nope }}</p>\n',
    )

    found = reported(template, Config(extensions=['i18n'], out_dir=STUB_DIR))

    assert [entry.line for entry in found] == [5]
    assert found[0].mentions('nope')
