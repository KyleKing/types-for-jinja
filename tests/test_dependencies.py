"""Guard the runtime import surface.

Installing types-for-jinja must pull in jinja2 and nothing else. Anything heavier belongs
behind an optional extra, so a project that only wants ``generate`` in CI does not pay for
the language server. This walks the package's own imports rather than trusting the
declared dependency list, because an undeclared import is the failure that actually
reaches a user.
"""

import ast
import sys
import tomllib
from pathlib import Path

import pytest

_PACKAGE = Path('types_for_jinja')
_RUNTIME = {'jinja2'}
"""Distributions a plain ``pip install types-for-jinja`` is allowed to require."""

_EXTRAS = {
    'beartype': 'runtime',
    'lsprotocol': 'lsp',
    'pygls': 'lsp',
}
"""Third-party root package to the optional extra that provides it."""


def _third_party_roots(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding='utf-8'))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split('.', 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split('.', 1)[0])
    return {
        root
        for root in roots
        if root not in sys.stdlib_module_names and root not in {'types_for_jinja', '__future__'}
    }


@pytest.mark.parametrize('module', sorted(_PACKAGE.glob('*.py')), ids=lambda path: path.name)
def test_module_only_imports_declared_dependencies(module):
    """An import outside jinja2 and the declared extras would break a minimal install."""
    unexpected = _third_party_roots(module) - _RUNTIME - set(_EXTRAS)

    assert not unexpected, f'{module} imports undeclared {sorted(unexpected)}'


def test_declared_runtime_dependencies_are_jinja2_only():
    table = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']

    declared = {requirement.split('>')[0].split('=')[0].split('[')[0].strip() for requirement in table['dependencies']}

    assert declared == _RUNTIME


def test_every_extra_import_is_provided_by_its_extra():
    """A module importing an extra's package is useless unless that extra declares it."""
    table = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']
    optional = table['optional-dependencies']

    missing = {extra for extra in set(_EXTRAS.values()) if extra not in optional}

    assert not missing
