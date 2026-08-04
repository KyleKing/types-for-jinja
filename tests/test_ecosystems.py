"""Copier and Cookiecutter template sets, which the scope claims need only existing settings.

Both put Jinja expressions in directory names, which is what makes them worth a test of their
own. A directory called ``{{cookiecutter.project_slug}}`` cannot be a Python package, and mypy
refuses an entire run when it finds an ``__init__.py`` inside one, so the stub tree has to
mangle directory names and not just filenames.

Copier's bracket-delimiter style is here too, since a template that generates Jinja needs
different delimiters and that is the setting's whole purpose.
"""

from pathlib import Path

import pytest

from types_for_jinja.config import Config, Syntax
from types_for_jinja.emit import mirrored_path

from . import checked
from .backends import STUB_DIR
from .checked import reported, write_template
from .configuration import requires_checker

_ANSWERS = """\
from dataclasses import dataclass


@dataclass(frozen=True)
class Answers:
    project_name: str
    module_name: str
    python_version: str
    use_ci: bool
"""

_COPIER_README = """\
{#def
from ctx.answers import Answers
answers: Answers
#}
# {{ answers.project_name }}

Requires Python {{ answers.python_verison }}.
{% if answers.use_ci %}CI is enabled.{% endif %}
"""

_COPIER_INIT = """\
{#def
from ctx.answers import Answers
answers: Answers
#}
\"\"\"{{ answers.projct_name }}.\"\"\"
"""

_BRACKET_README = """\
[#def
from ctx.answers import Answers
answers: Answers
#]
# [[ answers.project_name ]]
[% if answers.use_ci %]Requires [[ answers.python_verison ]].[% endif %]
"""

_COOKIECUTTER_CONTEXT = """\
from dataclasses import dataclass


@dataclass(frozen=True)
class Cookiecutter:
    project_name: str
    project_slug: str
    open_source_license: str
"""

_COOKIECUTTER_README = """\
{#def
from ctx.context import Cookiecutter
cookiecutter: Cookiecutter
#}
# {{ cookiecutter.project_name }}

Licensed under {{ cookiecutter.open_source_licence }}.
"""

_BRACKETS = Syntax(
    block_start_string='[%',
    block_end_string='%]',
    variable_start_string='[[',
    variable_end_string=']]',
    comment_start_string='[#',
    comment_end_string='#]',
)


@pytest.fixture
def context_package(project):
    """A package holding the answers type, which the templates import by name."""
    write_template('ctx/__init__.py', '')
    return project


def test_a_templated_directory_becomes_a_usable_package_name(context_package):
    """Mypy refuses the whole run on ``{{ module_name }}/__init__.py``, so it cannot reach disk."""
    write_template('ctx/answers.py', _ANSWERS)
    template = write_template('template/{{ module_name }}/__init__.py.jinja', _COPIER_INIT)

    mirrored = mirrored_path(template, Path(STUB_DIR))

    assert all(part.isidentifier() for part in mirrored.parent.parts)
    assert mirrored.stem.isidentifier()


def test_a_leading_underscore_does_not_collide_with_its_bare_neighbour(context_package):
    """Stripping leading underscores would make both templates write the same stub."""
    private = mirrored_path(Path('t/_draft.jinja'), Path(STUB_DIR))
    public = mirrored_path(Path('t/draft.jinja'), Path(STUB_DIR))

    assert private != public


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_copier_layout_is_checked_including_templated_directories(context_package):
    write_template('ctx/answers.py', _ANSWERS)
    readme = write_template('template/README.md.jinja', _COPIER_README)
    init = write_template('template/{{ module_name }}/__init__.py.jinja', _COPIER_INIT)
    config = Config(template_dirs=['template'], template_globs=['*.jinja'], out_dir=STUB_DIR)

    assert [entry.line for entry in reported(readme, config)] == [7]
    assert reported(readme, config)[0].mentions('python_verison')
    assert [entry.line for entry in reported(init, config)] == [5]
    assert reported(init, config)[0].mentions('projct_name')


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_copier_template_with_bracket_delimiters_is_checked(context_package):
    """A template that itself generates Jinja moves the delimiters, which is what syntax is for."""
    write_template('ctx/answers.py', _ANSWERS)
    template = write_template('template/README.md.jinja', _BRACKET_README)
    config = Config(
        template_dirs=['template'],
        template_globs=['*.jinja'],
        out_dir=STUB_DIR,
        syntax=_BRACKETS,
    )

    found = reported(template, config)

    assert [entry.line for entry in found] == [6]
    assert found[0].mentions('python_verison')


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_cookiecutter_layout_is_checked(context_package):
    """Cookiecutter puts the whole project inside one templated directory."""
    write_template('ctx/context.py', _COOKIECUTTER_CONTEXT)
    template = write_template('{{cookiecutter.project_slug}}/README.md', _COOKIECUTTER_README)
    config = Config(
        template_dirs=['{{cookiecutter.project_slug}}'],
        template_globs=['*.md'],
        out_dir=STUB_DIR,
    )

    found = reported(template, config)

    assert [entry.line for entry in found] == [7]
    assert found[0].mentions('open_source_licence')


@requires_checker(checked.DEFAULT_BACKEND)
def test_a_correct_cookiecutter_template_is_clean(context_package):
    write_template('ctx/context.py', _COOKIECUTTER_CONTEXT)
    template = write_template(
        '{{cookiecutter.project_slug}}/docs/index.md',
        '{#def\nfrom ctx.context import Cookiecutter\ncookiecutter: Cookiecutter\n#}\n'
        '# {{ cookiecutter.project_name }}\n',
    )
    config = Config(
        template_dirs=['{{cookiecutter.project_slug}}'],
        template_globs=['*.md'],
        out_dir=STUB_DIR,
    )

    assert reported(template, config) == []
