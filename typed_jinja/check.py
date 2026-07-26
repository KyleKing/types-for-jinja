"""Check Jinja templates by transpiling them and running pyright over the result."""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
from pathlib import Path
from typing import Any

from jinja2 import TemplateSyntaxError

from typed_jinja.codes import apply_codes
from typed_jinja.config import Config, load_config
from typed_jinja.diagnostic import Diagnostic
from typed_jinja.header import parse_header
from typed_jinja.suppress import apply_suppressions
from typed_jinja.transpile import transpile

_MARKER_RE = re.compile(r'#\s*L(\d+)\s*$')
_CACHE_DIR = Path('.typed_jinja_cache')

__all__ = ['Diagnostic', 'PyrightNotFoundError', 'check_file', 'check_source']


class PyrightNotFoundError(RuntimeError):
    """pyright is required to run the checker but was not found on PATH."""


def check_file(path: Path, cache_dir: Path = _CACHE_DIR) -> list[Diagnostic]:
    """Type-check one template on disk, returning diagnostics mapped to its own lines."""
    return check_source(path.read_text(encoding='utf-8'), path, cache_dir=cache_dir)


def check_source(
    source: str,
    path: Path,
    *,
    cache_dir: Path = _CACHE_DIR,
    config: Config | None = None,
) -> list[Diagnostic]:
    """Type-check template ``source`` labelled as ``path`` (used for on-disk and live buffers)."""
    diags = _raw_diagnostics(source, path, cache_dir, config)
    return apply_suppressions(source, apply_codes(diags))


def _raw_diagnostics(source: str, path: Path, cache_dir: Path, config: Config | None) -> list[Diagnostic]:
    header = parse_header(source)
    if header is None:
        return [Diagnostic(path, 1, 1, 'warning', 'no {#def ... #} type header; skipped', 'no-header')]
    try:
        module = transpile(source, header, config or load_config(Path.cwd()), template_path=path)
    except TemplateSyntaxError as err:
        return [Diagnostic(path, err.lineno or 1, 1, 'error', f'template syntax error: {err.message}', 'syntax-error')]
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
