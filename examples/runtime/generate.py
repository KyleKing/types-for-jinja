"""Regenerate the typed wrappers in this directory from the template header.

Run with ``uv run python -m examples.runtime.generate``. The output files
(``wrapper_beartype.py`` and ``wrapper_pydantic.py``) are committed so the example
reads without a build step.

``types-for-jinja wrapper`` is the supported way to do this in a project. This script
exists to show both validators side by side, which one CLI run cannot.
"""

from __future__ import annotations

import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
from pathlib import Path

from types_for_jinja.header import parse_header
from types_for_jinja.wrapper import Validator, generate_wrapper

_HERE = Path(__file__).parent
_TEMPLATE = _HERE / 'templates' / 'profile.html.jinja'
_ENV_IMPORT = 'from examples.runtime.env import env as _env'


def _write(validator: Validator) -> Path:
    header = parse_header(_TEMPLATE.read_text(encoding='utf-8'))
    if header is None:
        message = 'profile template is missing its {#def #} header'
        raise ValueError(message)
    source = generate_wrapper(header, _TEMPLATE.name, validator=validator, env_import=_ENV_IMPORT)
    out = _HERE / f'wrapper_{validator}.py'
    out.write_text(source, encoding='utf-8')
    return out


def _format(paths: list[Path]) -> None:
    ruff = shutil.which('ruff')
    if ruff is None:
        return
    args = [str(path) for path in paths]
    subprocess.run([ruff, 'check', '--fix', '--quiet', *args], check=False)  # ruff:ignore[subprocess-without-shell-equals-true]
    subprocess.run([ruff, 'format', '--quiet', *args], check=False)  # ruff:ignore[subprocess-without-shell-equals-true]


def main() -> None:
    """Write one wrapper module per runtime validator, then format the output."""
    _format([_write(validator) for validator in ('beartype', 'pydantic')])


if __name__ == '__main__':
    main()
