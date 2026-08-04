"""Graceful handling of malformed templates.

types-for-jinja no longer runs a checker, so there is no missing-pyright path left to
handle. What remains is that a template it cannot turn into a stub is reported and skipped
rather than taking the whole run down.
"""

from pathlib import Path

import pytest

from types_for_jinja.cli import main
from types_for_jinja.config import DEFAULT_OUT_DIR, Config, load_config

from .backends import STUB_DIR
from .checked import skipped, write_template

_STUB_DIR = STUB_DIR


def test_no_header_is_a_warning():
    diagnostics = skipped('<h1>no header</h1>', Path('x.html'))

    assert [d.severity for d in diagnostics] == ['warning']
    assert 'no {#def ... #} type header' in diagnostics[0].message


def test_a_jinja_syntax_error_is_an_error():
    diagnostics = skipped('{#def x: int #}\n{% if %}{% endif %}\n', Path('bad.html'))

    assert [d.severity for d in diagnostics] == ['error']
    assert 'syntax error' in diagnostics[0].message


def test_an_unsupported_construct_is_a_warning():
    """One template the transpiler cannot model must not stop the others being generated."""
    source = '{#def x: int #}\n{% set ns = namespace(n=0) %}\n{% set ns.n = 1 %}\n'

    diagnostics = skipped(source, Path('ns.html'))

    assert [d.severity for d in diagnostics] == ['warning']
    assert 'unsupported template construct' in diagnostics[0].message


def test_generate_skips_a_broken_template_and_keeps_going(project, capsys):
    write_template('templates/broken.html.jinja', '{#def x: int #}\n{% if %}{% endif %}\n')

    code = main(['generate', 'templates', '-o', _STUB_DIR])

    assert code == 0
    assert 'skipped' in capsys.readouterr().err
    assert (Path(_STUB_DIR) / 'templates/page_html_jinja.py').is_file()


def test_generate_check_reports_a_missing_stub(project):
    assert main(['generate', 'templates', '-o', _STUB_DIR, '--check']) == 1


def test_generate_check_is_quiet_once_the_stubs_are_written(project):
    main(['generate', 'templates', '-o', _STUB_DIR])

    assert main(['generate', 'templates', '-o', _STUB_DIR, '--check']) == 0


def test_a_dot_prefixed_out_dir_is_rejected(tmp_path):
    """Pyright excludes ``**/.*`` by default and would report a clean run over zero files."""
    (tmp_path / 'pyproject.toml').write_text('[tool.types_for_jinja]\nout_dir = ".hidden"\n', encoding='utf-8')

    with pytest.raises(ValueError, match='out_dir'):
        load_config(tmp_path)


def test_config_defaults_when_no_table_is_present(tmp_path):
    assert load_config(tmp_path) == Config()
    assert Config().out_dir == DEFAULT_OUT_DIR
