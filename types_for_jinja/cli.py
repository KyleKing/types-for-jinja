"""Command-line entry point: ``types-for-jinja check <paths> [--format ...]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from types_for_jinja.check import Diagnostic, PyrightNotFoundError, check_file
from types_for_jinja.generate import generate, stale, write
from types_for_jinja.report import format_json, format_sarif, format_text

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


def _generate(templates: list[Path], out_dir: Path, *, check_only: bool) -> int:
    generated = generate(templates, out_dir)
    for template, reason in generated.skipped:
        print(f'types-for-jinja: skipped {template}: {reason}', file=sys.stderr)  # ruff:ignore[print]
    for template in generated.unaligned:
        message = f'types-for-jinja: {template} has no line-aligned form; its stub uses # L markers instead'
        print(message, file=sys.stderr)  # ruff:ignore[print]
    if check_only:
        outdated = stale(generated)
        for path in outdated:
            print(f'types-for-jinja: out of date: {path}', file=sys.stderr)  # ruff:ignore[print]
        return 1 if outdated else 0
    changed = write(generated, out_dir)
    summary = f'Wrote {len(changed)} of {len(generated.files)} stub(s) for {len(generated.stubs)} template(s)'
    print(summary, file=sys.stderr)  # ruff:ignore[print]
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the checker over the given paths; return a non-zero exit code on errors."""
    parser = argparse.ArgumentParser(prog='types-for-jinja')
    subparsers = parser.add_subparsers(dest='command', required=True)
    check_parser = subparsers.add_parser('check', help='type-check Jinja templates')
    check_parser.add_argument('paths', nargs='+', type=Path, help='template files or directories')
    check_parser.add_argument('--format', choices=list(_FORMATTERS), default='text', help='output format')
    generate_parser = subparsers.add_parser(
        'generate',
        help='write type-checking stubs for your own type checker to pick up',
    )
    generate_parser.add_argument('paths', nargs='+', type=Path, help='template files or directories')
    generate_parser.add_argument(
        '-o',
        '--out-dir',
        type=Path,
        default=Path('_jinja_stubs'),
        help='output directory; must not start with a dot, which pyright excludes by default',
    )
    generate_parser.add_argument(
        '--check',
        action='store_true',
        help='exit non-zero if any stub is missing or out of date instead of writing',
    )
    args = parser.parse_args(argv)

    templates = _iter_templates(args.paths)
    if args.command == 'generate':
        return _generate(templates, args.out_dir, check_only=args.check)
    try:
        diagnostics: list[Diagnostic] = [diag for template in templates for diag in check_file(template)]
    except PyrightNotFoundError:
        message = 'types-for-jinja: pyright not found on PATH; install it (for example `uv tool install pyright`)'
        print(message, file=sys.stderr)  # ruff:ignore[print]
        return 2
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
