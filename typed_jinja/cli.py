"""Command-line entry point: ``typed-jinja check <paths> [--format ...]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from typed_jinja.check import Diagnostic, check_file
from typed_jinja.report import format_json, format_sarif, format_text

_FORMATTERS = {'text': format_text, 'json': format_json, 'sarif': format_sarif}


def _iter_templates(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob('*.html')))
            found.extend(sorted(path.rglob('*.jinja')))
        else:
            found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    """Run the checker over the given paths; return a non-zero exit code on errors."""
    parser = argparse.ArgumentParser(prog='typed-jinja')
    subparsers = parser.add_subparsers(dest='command', required=True)
    check_parser = subparsers.add_parser('check', help='type-check Jinja templates')
    check_parser.add_argument('paths', nargs='+', type=Path, help='template files or directories')
    check_parser.add_argument('--format', choices=list(_FORMATTERS), default='text', help='output format')
    args = parser.parse_args(argv)

    templates = _iter_templates(args.paths)
    diagnostics: list[Diagnostic] = [diag for template in templates for diag in check_file(template)]
    error_count = sum(diag.severity == 'error' for diag in diagnostics)

    rendered = _FORMATTERS[args.format](diagnostics)
    if rendered:
        print(rendered)  # ruff:ignore[print]
    if args.format == 'text':
        sys.stdout.flush()
        summary = f'Checked {len(templates)} template(s): {error_count} error(s)'
        print(summary, file=sys.stderr)  # ruff:ignore[print]
    return 1 if error_count else 0


if __name__ == '__main__':
    raise SystemExit(main())
