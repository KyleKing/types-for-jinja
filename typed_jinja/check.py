"""Check Jinja templates by transpiling them and running pyright over the result."""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typed_jinja.config import load_config
from typed_jinja.header import parse_header
from typed_jinja.transpile import transpile

_MARKER_RE = re.compile(r'#\s*L(\d+)\s*$')
_CACHE_DIR = Path('.typed_jinja_cache')


@dataclass(frozen=True)
class Diagnostic:
    """A type error located back in the original template."""

    path: Path
    line: int
    column: int
    severity: str
    message: str
    rule: str


class PyrightNotFoundError(RuntimeError):
    """pyright is required to run the checker but was not found on PATH."""


def check_file(path: Path, cache_dir: Path = _CACHE_DIR) -> list[Diagnostic]:
    """Type-check one template, returning diagnostics mapped to its own line numbers."""
    source = path.read_text(encoding='utf-8')
    header = parse_header(source)
    if header is None:
        return [Diagnostic(path, 1, 0, 'warning', 'no {#def ... #} type header; skipped', 'no-header')]
    module = transpile(source, header, load_config(Path.cwd()))
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_pyright_config(cache_dir)
    generated = cache_dir / f'{_safe_name(path)}.py'
    generated.write_text(module.code, encoding='utf-8')
    generated_lines = module.code.splitlines()
    return [
        Diagnostic(
            path=path,
            line=_template_line(generated_lines, raw['range']['start']['line']),
            column=raw['range']['start']['character'] + 1,
            severity=raw['severity'],
            message=raw['message'].replace('\n', ' '),
            rule=raw.get('rule', ''),
        )
        for raw in _run_pyright(generated)
        if raw['severity'] == 'error'
    ]


def _safe_name(path: Path) -> str:
    return re.sub(r'[^0-9A-Za-z]+', '_', str(path)).strip('_')


def _write_pyright_config(cache_dir: Path) -> None:
    config = {'include': ['.'], 'exclude': [], 'extraPaths': [str(Path.cwd().resolve())]}
    (cache_dir / 'pyrightconfig.json').write_text(json.dumps(config), encoding='utf-8')


def _template_line(generated_lines: list[str], zero_based: int) -> int:
    for idx in range(min(zero_based, len(generated_lines) - 1), -1, -1):
        match = _MARKER_RE.search(generated_lines[idx])
        if match:
            return int(match.group(1))
    return 1


def _run_pyright(generated: Path) -> list[dict[str, Any]]:
    pyright = shutil.which('pyright')
    if pyright is None:
        raise PyrightNotFoundError
    result = subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true]
        [pyright, '--outputjson', generated.name],
        cwd=generated.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    return payload.get('generalDiagnostics', [])
