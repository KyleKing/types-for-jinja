"""Pyright-backed checks of the real yak-shears templates and filter handling."""

import shutil
from pathlib import Path

import pytest

from types_for_jinja.check import check_file

pytestmark = pytest.mark.skipif(shutil.which('pyright') is None, reason='pyright is required')

_RW = Path('examples/realworld')


@pytest.mark.parametrize('name', ['error.html.jinja', 'login.html.jinja', 'yaks_index.html.jinja'])
def test_realworld_template_clean(name, tmp_path):
    assert check_file(_RW / name, cache_dir=tmp_path) == []


def test_filter_chain_no_false_positive(tmp_path):
    source = '{#def count: int #}\n{% set fill = ([count, 500] | min) / 500 %}\n<p>{{ fill }}</p>'
    template = tmp_path / 'f.html'
    template.write_text(source, encoding='utf-8')

    assert check_file(template, cache_dir=tmp_path / 'c') == []


def test_typo_still_caught_in_realworld(tmp_path):
    source = (_RW / 'yaks_index.html.jinja').read_text(encoding='utf-8').replace('info.preview', 'info.prevew', 1)
    template = tmp_path / 'typo.html.jinja'
    template.write_text(source, encoding='utf-8')

    diags = check_file(template, cache_dir=tmp_path / 'c')

    assert any(diag.rule == 'reportAttributeAccessIssue' for diag in diags)
