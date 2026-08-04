"""Command-line entry point.

Three subcommands, and none of them runs a type checker. ``generate`` writes the stubs the
project's own checker picks up, ``remap`` rewrites that checker's output to name templates,
and ``wrapper`` writes a typed render function per template.
"""

from __future__ import annotations

import argparse
import subprocess  # ruff:ignore[suspicious-subprocess-import]
import sys
from dataclasses import replace
from pathlib import Path

from types_for_jinja.config import Config, load_config
from types_for_jinja.emit import stale_files, write_files
from types_for_jinja.generate import generate, stale, write
from types_for_jinja.remap import FORMATS, Remapper, remap
from types_for_jinja.wrapper import VALIDATORS, build_wrappers


def _warn(message: str) -> None:
    print(f'types-for-jinja: {message}', file=sys.stderr)  # ruff:ignore[print]


def _iter_templates(paths: list[Path], config: Config) -> list[Path]:
    """Expand directory arguments into template files, deduplicated and in a stable order.

    A pattern may match a file another already matched (``page.html.jinja`` is both ``*.html``
    and ``*.jinja``), so the same template must not be generated twice.
    """
    found: list[Path] = []
    for path in paths:
        if not path.is_dir():
            found.append(path)
            continue
        found.extend(sorted({match for glob in config.template_globs for match in path.rglob(glob)}))
    return list(dict.fromkeys(found))


def _default_paths(config: Config) -> list[Path]:
    """Where to look when the command was given no paths: the configured template directories.

    A ``package:subdirectory`` entry contributes only its subdirectory, since that is the part
    that exists as a path in the project being checked.
    """
    entries = (Path(entry.partition(':')[2] or entry) for entry in config.template_dirs)
    return [path for path in entries if path.is_dir()]


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


_EXIT_BAD_CONFIG = 2


def main(argv: list[str] | None = None) -> int:
    """Dispatch a subcommand; return a non-zero exit code when it reports a problem."""
    try:
        return _dispatch(argv)
    except ValueError as err:
        _warn(f'{err} (in [tool.types_for_jinja] of pyproject.toml)')
        return _EXIT_BAD_CONFIG


def _dispatch(argv: list[str] | None) -> int:
    config = load_config(Path.cwd())
    default_out_dir = Path(config.out_dir)
    parser = argparse.ArgumentParser(prog='types-for-jinja')
    subparsers = parser.add_subparsers(dest='command', required=True)
    generate_parser = subparsers.add_parser(
        'generate',
        help='write type-checking stubs for your own type checker to pick up',
    )
    generate_parser.add_argument(
        'paths',
        nargs='*',
        type=Path,
        help='template files or directories; defaults to the configured template_dirs',
    )
    generate_parser.add_argument(
        '-o',
        '--out-dir',
        type=Path,
        default=default_out_dir,
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
    remap_parser.add_argument('-o', '--out-dir', type=Path, default=default_out_dir, help='the stub directory')
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
    wrapper_parser.add_argument(
        'paths',
        nargs='*',
        type=Path,
        help='template files or directories; defaults to the configured template_dirs',
    )
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
    paths = args.paths or _default_paths(config)
    if not paths:
        _warn('no paths given and no template_dirs configured')
        return _EXIT_BAD_CONFIG
    templates = _iter_templates(paths, config)
    if args.command == 'generate':
        return _generate(templates, args.out_dir, check_only=args.check)
    wrapper_config = _wrapper_config(args, config)
    out_dir = args.out_dir or Path(wrapper_config.wrapper.out_dir)
    return _wrapper(templates, wrapper_config, out_dir, check_only=args.check)


if __name__ == '__main__':
    raise SystemExit(main())
