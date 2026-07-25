"""Command-line entry point: ``typed-jinja check <paths>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from typed_jinja.check import Diagnostic, check_file


def _iter_templates(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob('*.html')))
            found.extend(sorted(path.rglob('*.jinja')))
        else:
            found.append(path)
    return found


def _format(diagnostic: Diagnostic) -> str:
    rule = f' ({diagnostic.rule})' if diagnostic.rule else ''
    return f'{diagnostic.path}:{diagnostic.line}:{diagnostic.column} {diagnostic.severity}: {diagnostic.message}{rule}'


def main(argv: list[str] | None = None) -> int:
    """Run the checker over the given paths; return a non-zero exit code on errors."""
    parser = argparse.ArgumentParser(prog='typed-jinja')
    subparsers = parser.add_subparsers(dest='command', required=True)
    check_parser = subparsers.add_parser('check', help='type-check Jinja templates')
    check_parser.add_argument('paths', nargs='+', type=Path, help='template files or directories')
    args = parser.parse_args(argv)

    templates = _iter_templates(args.paths)
    error_count = 0
    for template in templates:
        for diagnostic in check_file(template):
            print(_format(diagnostic))  # ruff:ignore[print]
            if diagnostic.severity == 'error':
                error_count += 1

    sys.stdout.flush()
    summary = f'Checked {len(templates)} template(s): {error_count} error(s)'
    print(summary, file=sys.stderr)  # ruff:ignore[print]
    return 1 if error_count else 0


if __name__ == '__main__':
    raise SystemExit(main())
