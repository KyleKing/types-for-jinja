"""Graceful handling of malformed templates and a missing pyright."""

import shutil

import pytest

from typed_jinja.check import PyrightNotFoundError, check_file
from typed_jinja.cli import main

_EXIT_MISSING_PYRIGHT = 2


def test_no_header_returns_warning(tmp_path):
    template = tmp_path / 'x.html'
    template.write_text('<h1>no header</h1>', encoding='utf-8')

    diags = check_file(template, cache_dir=tmp_path / 'c')

    assert len(diags) == 1
    assert diags[0].rule == 'no-header'
    assert diags[0].severity == 'warning'


def test_malformed_template_is_a_diagnostic(tmp_path):
    template = tmp_path / 'bad.html'
    template.write_text('{#def x: int #}\n{% if %}{% endif %}', encoding='utf-8')

    diags = check_file(template, cache_dir=tmp_path / 'c')

    assert len(diags) == 1
    assert diags[0].rule == 'syntax-error'
    assert diags[0].severity == 'error'


def test_check_file_raises_when_pyright_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    template = tmp_path / 'ok.html'
    template.write_text('{#def x: int #}\n{{ x }}', encoding='utf-8')

    with pytest.raises(PyrightNotFoundError):
        check_file(template, cache_dir=tmp_path / 'c')


def test_cli_reports_missing_pyright(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    template = tmp_path / 'ok.html'
    template.write_text('{#def x: int #}\n{{ x }}', encoding='utf-8')

    code = main(['check', str(template)])

    assert code == _EXIT_MISSING_PYRIGHT
    assert 'pyright not found' in capsys.readouterr().err
