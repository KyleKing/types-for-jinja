"""Which files a directory argument expands to, and what happens with no argument at all."""

from pathlib import Path

from types_for_jinja.cli import _EXIT_BAD_CONFIG, _default_paths, _iter_templates, main
from types_for_jinja.config import DEFAULT_TEMPLATE_GLOBS, Config, load_config

from .backends import STUB_DIR
from .checked import write_template

_BODY = '{#def\nname: str\n#}\n<p>{{ name }}</p>\n'


def test_the_default_globs_cover_the_three_common_extensions():
    assert set(DEFAULT_TEMPLATE_GLOBS) == {'*.html', '*.jinja', '*.j2'}


def test_a_directory_expands_to_every_matching_template(project):
    for name in ('a.html', 'b.jinja', 'c.j2', 'd.html.jinja', 'ignored.txt'):
        write_template(f'pages/{name}', _BODY)

    found = _iter_templates([Path('pages')], Config())

    assert [path.name for path in found] == ['a.html', 'b.jinja', 'c.j2', 'd.html.jinja']


def test_a_template_matching_two_globs_is_only_generated_once(project):
    """``page.html.jinja`` matches both ``*.html`` and ``*.jinja``."""
    write_template('pages/page.html.jinja', _BODY)

    assert len(_iter_templates([Path('pages')], Config())) == 1


def test_a_j2_template_is_found(project):
    """Ansible-style ``.j2`` is the common third spelling, and it used to be invisible."""
    write_template('pages/one.j2', _BODY)

    assert [path.name for path in _iter_templates([Path('pages')], Config())] == ['one.j2']


def test_the_globs_can_be_narrowed(project):
    for name in ('a.html', 'b.jinja'):
        write_template(f'pages/{name}', _BODY)

    found = _iter_templates([Path('pages')], Config(template_globs=['*.jinja']))

    assert [path.name for path in found] == ['b.jinja']


def test_a_named_file_is_taken_whatever_its_extension(project):
    """An explicit path is a decision the caller already made, so the globs do not apply."""
    template = write_template('pages/odd.tmpl', _BODY)

    assert _iter_templates([template], Config()) == [template]


def test_nested_directories_are_searched(project):
    write_template('pages/deep/nested/one.jinja', _BODY)

    assert [path.name for path in _iter_templates([Path('pages')], Config())] == ['one.jinja']


def test_load_config_reads_template_globs(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja]\ntemplate_globs = ["*.tmpl"]\n',
        encoding='utf-8',
    )

    assert load_config(tmp_path).template_globs == ['*.tmpl']


def test_the_default_paths_are_the_configured_template_dirs(project):
    (project / 'components').mkdir()

    assert _default_paths(Config(template_dirs=['templates', 'components'])) == [
        Path('templates'),
        Path('components'),
    ]


def test_a_package_relative_template_dir_contributes_its_subdirectory(project):
    """``package:subdirectory`` is what PackageLoader reads, so only the subdirectory is a path."""
    (project / 'templates').mkdir(exist_ok=True)

    assert _default_paths(Config(template_dirs=['somepackage:templates'])) == [Path('templates')]


def test_a_template_dir_that_does_not_exist_is_dropped(project):
    assert _default_paths(Config(template_dirs=['nope'])) == []


def test_generate_with_no_paths_uses_template_dirs(project):
    (project / 'pyproject.toml').write_text(
        f'[tool.types_for_jinja]\ntemplate_dirs = ["templates"]\nout_dir = "{STUB_DIR}"\n',
        encoding='utf-8',
    )

    assert main(['generate']) == 0
    assert (project / STUB_DIR / 'templates/page_html_jinja.py').is_file()


def test_generate_with_no_paths_and_no_template_dirs_says_so(project, capsys):
    (project / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "0"\n', encoding='utf-8')

    code = main(['generate'])

    assert code == _EXIT_BAD_CONFIG
    assert 'no template_dirs configured' in capsys.readouterr().err
