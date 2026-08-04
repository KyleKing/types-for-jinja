"""Command-line entry point: ``types-for-jinja check <paths> [--format ...]``."""

from __future__ import annotations

import argparse
import subprocess  # ruff:ignore[suspicious-subprocess-import]
import sys
from dataclasses import replace
from pathlib import Path

from types_for_jinja.check import Diagnostic, PyrightNotFoundError, check_file
from types_for_jinja.config import Config, load_config
from types_for_jinja.emit import stale_files, write_files
from types_for_jinja.generate import generate, stale, write
from types_for_jinja.remap import FORMATS, Remapper, remap
from types_for_jinja.report import format_json, format_sarif, format_text
from types_for_jinja.wrapper import VALIDATORS, build_wrappers

_FORMATTERS = {'text': format_text, 'json': format_json, 'sarif': format_sarif}


def _warn(message: str) -> None:
    print(f'types-for-jinja: {message}', file=sys.stderr)  # ruff:ignore[print]


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
        _warn(f'skipped {template}: {reason}')
    for template in generated.unaligned:
        _warn(f'{template} has no line-aligned form; its stub uses # L markers instead')
    if check_only:
        outdated = stale(generated)
        for path in outdated:
            _warn(f'out of date: {path}')
        return 1 if outdated else 0
    changed = write(generated)
    _warn(f'Wrote {len(changed)} file(s) for {len(generated.stubs)} template(s)')
    return 0


def _wrapper(templates: list[Path], config: Config, out_dir: Path, *, check_only: bool) -> int:
    wrappers = build_wrappers(templates, out_dir, config)
    for template, reason in wrappers.skipped:
        _warn(f'skipped {template}: {reason}')
    if check_only:
        outdated = stale_files(wrappers.files)
        for path in outdated:
            _warn(f'out of date: {path}')
        return 1 if outdated else 0
    changed = write_files(wrappers.files)
    _warn(f'Wrote {len(changed)} of {len(wrappers.files)} wrapper file(s)')
    return 0


def _remap(args: argparse.Namespace) -> int:
    """Rewrite a checker's output to name templates, either as a filter or around a command.

    The wrapped form exists because a pipeline hands back the filter's exit code, not the
    checker's, so ``ty check | types-for-jinja remap`` reports success on a failing run
    unless the shell is configured for it.
    """
    remapper = Remapper(args.out_dir)
    if not args.command_argv:
        print(remap(sys.stdin.read(), remapper, args.format), end='')  # ruff:ignore[print]
        return 0
    result = subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true]
        args.command_argv,
        capture_output=True,
        text=True,
        check=False,
    )
    print(remap(result.stdout, remapper, args.format), end='')  # ruff:ignore[print]
    print(result.stderr, end='', file=sys.stderr)  # ruff:ignore[print]
    return result.returncode


def _wrapper_config(args: argparse.Namespace, config: Config) -> Config:
    """Let explicit flags win over ``[tool.types_for_jinja.wrapper]``."""
    overrides = {
        key: value
        for key, value in (
            ('env_import', args.env_import),
            ('return_import', args.return_import),
            ('return_type', args.return_type),
            ('validator', args.validator),
        )
        if value is not None
    }
    return replace(config, wrapper=replace(config.wrapper, **overrides))


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
    remap_parser = subparsers.add_parser(
        'remap',
        help="rewrite a type checker's output so it names templates instead of generated stubs",
    )
    remap_parser.add_argument('-o', '--out-dir', type=Path, default=Path('_jinja_stubs'), help='the stub directory')
    remap_parser.add_argument(
        '--format',
        choices=list(FORMATS),
        default='auto',
        help="shape of the checker's output; auto detects text, pyright JSON, mypy JSON, or ty gitlab",
    )
    remap_parser.add_argument(
        'command_argv',
        nargs='*',
        metavar='-- CHECKER ...',
        help='checker to run and remap; with no command, filters stdin and always exits 0',
    )
    wrapper_parser = subparsers.add_parser(
        'wrapper',
        help='write a typed render function per template, so the render call site is checked too',
    )
    wrapper_parser.add_argument('paths', nargs='+', type=Path, help='template files or directories')
    wrapper_parser.add_argument('-o', '--out-dir', type=Path, default=None, help='output directory')
    wrapper_parser.add_argument(
        '--validator',
        choices=list(VALIDATORS),
        default=None,
        help='runtime enforcement to apply to the context (default: none, static only)',
    )
    wrapper_parser.add_argument(
        '--env-import',
        default=None,
        help="import binding your Jinja Environment to _env, e.g. 'from myapp.templating import env as _env'",
    )
    wrapper_parser.add_argument('--return-type', default=None, help='type the wrapper returns (default: Markup)')
    wrapper_parser.add_argument('--return-import', default=None, help='import that names --return-type')
    wrapper_parser.add_argument(
        '--check',
        action='store_true',
        help='exit non-zero if any wrapper is missing or out of date instead of writing',
    )
    args = parser.parse_args(argv)

    if args.command == 'remap':
        return _remap(args)
    templates = _iter_templates(args.paths)
    if args.command == 'generate':
        return _generate(templates, args.out_dir, check_only=args.check)
    if args.command == 'wrapper':
        config = _wrapper_config(args, load_config(Path.cwd()))
        out_dir = args.out_dir or Path(config.wrapper.out_dir)
        return _wrapper(templates, config, out_dir, check_only=args.check)
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
