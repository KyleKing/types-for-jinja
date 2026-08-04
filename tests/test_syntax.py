"""Non-standard delimiters and package-relative template directories."""

from pathlib import Path

from types_for_jinja.complete import cursor_context
from types_for_jinja.config import Config, Syntax, load_config
from types_for_jinja.header import Param, parse_header
from types_for_jinja.resolve import search_paths

from . import checked
from .backends import STUB_DIR
from .checked import reported, write_template
from .configuration import requires_checker

_SQUARE = Syntax(
    block_start_string='[%',
    block_end_string='%]',
    variable_start_string='[[',
    variable_end_string=']]',
    comment_start_string='[#',
    comment_end_string='#]',
)
_TEMPLATE = """[#def
from examples.models import User
user: User
#]
<h1>[[ user.naem ]]</h1>
[% for item in user.items %][[ item.title ]][% endfor %]
"""


def test_header_is_read_through_custom_comment_delimiters():
    header = parse_header(_TEMPLATE, _SQUARE)

    assert header is not None
    assert header.params == [Param('user', 'User')]


def test_standard_delimiters_do_not_match_a_custom_header():
    assert parse_header(_TEMPLATE) is None


def test_cursor_context_follows_custom_delimiters():
    assert cursor_context('<p>[[ us', 8, _SQUARE).in_expression
    assert not cursor_context('<p>{{ us', 8, _SQUARE).in_expression


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_template_with_custom_delimiters_is_checked(examples_project):
    """A Jinja superset that moves the delimiters still gets its expressions checked."""
    template = write_template('templates/sq.html.jinja', _TEMPLATE)

    found = reported(template, Config(syntax=_SQUARE, out_dir=STUB_DIR))

    assert [entry.line for entry in found] == [5]
    assert found[0].mentions('naem')


def test_load_config_reads_the_syntax_table(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja.syntax]\nvariable_start_string = "[["\nvariable_end_string = "]]"\n',
        encoding='utf-8',
    )

    syntax = load_config(tmp_path).syntax

    assert syntax.variable_start_string == '[['
    assert syntax.block_start_string == '{%'


def test_unknown_syntax_key_is_ignored(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja.syntax]\nnot_a_delimiter = "x"\n',
        encoding='utf-8',
    )

    assert load_config(tmp_path).syntax == Syntax()


def test_search_paths_resolves_a_package_relative_directory():
    found = search_paths(['examples:templates'])

    assert found == [Path('examples/templates').resolve()]


def test_search_paths_drops_an_unimportable_package():
    assert search_paths(['no_such_package_anywhere:templates']) == []


def test_search_paths_keeps_plain_directories():
    assert search_paths(['examples/crossfile', 'does/not/exist']) == [Path('examples/crossfile')]
