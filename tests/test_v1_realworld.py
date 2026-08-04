"""Checks of the real yak-shears templates and filter handling.

These are the templates the README shows, so a regression here is one a reader would hit.
"""

from pathlib import Path

import pytest

from types_for_jinja.config import Config

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


def test_typo_still_caught_in_realworld(examples_project):
    source = (Path('examples/realworld/yaks_index.html.jinja')).read_text(encoding='utf-8')
    template = write_template('examples/realworld/typo.html.jinja', source.replace('info.preview', 'info.prevew', 1))

    found = reported(template, _CONFIG)

    assert any(entry.mentions('prevew') for entry in found)
