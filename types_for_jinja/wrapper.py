"""Generate a typed Python wrapper that delegates rendering to Jinja.

The wrapper is the Level-1 codegen from the plan: a typed function whose call site
the project's checker checks, whose body calls ``_env.get_template(name).render(...)`` unchanged.
Jinja still renders. An optional ``validator`` adds Level-2 runtime enforcement,
either a ``@beartype`` guard (check, non-transforming) or a Pydantic ``TypeAdapter``
(parse and transform) applied to each parameter before the render call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from types_for_jinja import manifest
from types_for_jinja.config import Config, WrapperConfig, load_config
from types_for_jinja.emit import mirrored_path, package_markers, stale_files, write_files
from types_for_jinja.header import Param, TemplateHeader, header_errors, parse_header
from types_for_jinja.resolve import search_paths

Validator = Literal['none', 'beartype', 'pydantic']
VALIDATORS: tuple[Validator, ...] = ('none', 'beartype', 'pydantic')


@dataclass(frozen=True)
class ReturnStyle:
    """What the generated function returns, and the import that names it."""

    type_name: str = 'Markup'
    import_line: str = 'from markupsafe import Markup'


@dataclass(frozen=True)
class Wrappers:
    """The wrapper modules a run would write, plus the templates that produced none."""

    files: dict[Path, str]
    skipped: list[tuple[Path, str]]
    out_dir: Path = Path()
    entries: dict[PurePosixPath, manifest.Entry] = field(default_factory=dict)
    decided: set[PurePosixPath] = field(default_factory=set)


def build_wrappers(templates: list[Path], out_dir: Path, config: Config | None = None) -> Wrappers:
    """Generate a typed render wrapper per template, laid out under ``out_dir``."""
    resolved = config or load_config(Path.cwd())
    root = Path.cwd()
    files: dict[Path, str] = {}
    skipped: list[tuple[Path, str]] = []
    entries: dict[PurePosixPath, manifest.Entry] = {}
    decided: set[PurePosixPath] = set()
    for template in templates:
        decided.add(manifest.relative(template, root))
        source = template.read_text(encoding='utf-8')
        header = parse_header(source, resolved.syntax)
        if header is None:
            skipped.append((template, 'no {#def ... #} type header'))
            continue
        malformed = header_errors(header)
        if malformed:
            skipped.append((template, malformed[0]))
            continue
        path = mirrored_path(template, out_dir)
        files[path] = generate_wrapper(
            header,
            template_name(template, resolved),
            validator=_validator(resolved.wrapper),
            env_import=resolved.wrapper.env_import,
            returns=ReturnStyle(resolved.wrapper.return_type, resolved.wrapper.return_import),
        )
        markers = package_markers(out_dir, path)
        files.update(markers)
        entries[manifest.relative(path, out_dir)] = manifest.Entry(
            template=manifest.relative(template, root),
            aligned=False,
            support=tuple(sorted(manifest.relative(marker, out_dir) for marker in markers)),
        )
    return Wrappers(files=files, skipped=skipped, out_dir=out_dir, entries=entries, decided=decided)


def plan(wrappers: Wrappers) -> tuple[dict[Path, str], list[Path]]:
    """Return the files this run writes and the wrappers it removes.

    A renamed or deleted template otherwise leaves its wrapper importable, so application
    code keeps rendering a template that no longer exists. The manifest joins the write set
    so ``--check`` also fails on a tree whose bookkeeping has drifted.
    """
    out_dir = wrappers.out_dir
    previous = manifest.load(out_dir)
    merged = manifest.merge(previous, manifest.Manifest(entries=wrappers.entries), wrappers.decided)
    files = {**wrappers.files, out_dir / manifest.MANIFEST_NAME: manifest.dumps(merged)}
    return files, manifest.orphans(previous, merged, out_dir)


def write(wrappers: Wrappers) -> list[Path]:
    """Write every wrapper and delete orphaned ones, returning the paths that changed."""
    files, removed = plan(wrappers)
    for path in removed:
        path.unlink(missing_ok=True)
    changed = write_files(files)
    _prune_empty_dirs({path.parent for path in removed}, wrappers.out_dir)
    return changed + [path for path in removed if not path.is_file()]


def stale(wrappers: Wrappers) -> list[Path]:
    """Return the paths whose on-disk state no longer matches what this run would produce."""
    files, removed = plan(wrappers)
    return stale_files(files) + [path for path in removed if path.is_file()]


def _prune_empty_dirs(candidates: set[Path], out_dir: Path) -> None:
    for directory in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        current = directory
        while current != out_dir and out_dir in current.parents and current.is_dir() and not any(current.iterdir()):
            current.rmdir()
            current = current.parent


def template_name(template: Path, config: Config) -> str:
    """Return the name Jinja's loader uses, relative to the first configured template dir."""
    candidate = template.resolve()
    for directory in search_paths(config.template_dirs):
        root = directory.resolve()
        if root in candidate.parents:
            return candidate.relative_to(root).as_posix()
    return template.name


def _validator(wrapper: WrapperConfig) -> Validator:
    if wrapper.validator not in VALIDATORS:
        message = f'unknown validator {wrapper.validator!r}; expected one of {", ".join(VALIDATORS)}'
        raise ValueError(message)
    return wrapper.validator


def generate_wrapper(
    header: TemplateHeader,
    template_name: str,
    *,
    validator: Validator = 'none',
    env_import: str | None = None,
    func_name: str | None = None,
    returns: ReturnStyle | None = None,
) -> str:
    """Return Python source for a typed render wrapper around ``template_name``.

    ``env_import`` supplies the Jinja Environment as ``_env`` (for example
    ``from myapp.templating import env as _env``). When omitted, the module declares
    ``_env: Environment`` for the caller to assign. ``validator`` selects Level-2
    runtime enforcement. ``returns`` swaps the default ``Markup`` for a framework
    response class. Imports are emitted in a stable order; run a formatter over the
    output if your project sorts imports.
    """
    style = returns or ReturnStyle()
    name = func_name or _slug(template_name)
    # A bare ``*`` with nothing after it is a syntax error, and a header declaring no
    # parameters is ordinary: a layout other templates extend takes its context from them.
    signature = ', '.join(['*', *(_declaration(param) for param in header.params)]) if header.params else ''
    call_kwargs = ', '.join(f'{param.name}={param.name}' for param in header.params)

    lines = [
        f'"""Generated by types-for-jinja from {template_name}. Do not edit by hand."""',
        '',
        'from __future__ import annotations',
        '',
        *_module_imports(header, validator, env_import, style),
    ]
    lines.extend(_module_globals(header, validator, env_import))
    lines.extend(['', ''])
    if validator == 'beartype':
        lines.append('@beartype')
    lines.extend(
        [
            f'def render_{name}({signature}) -> {style.type_name}:',
            f'    """Render {template_name} with a checked context."""',
        ]
    )
    if validator == 'pydantic':
        lines.extend(
            f'    {param.name} = _ta_{param.name}.validate_python({param.name})  # validate and transform'
            for param in header.params
        )
    render = f'_env.get_template({template_name!r}).render({call_kwargs})'
    suppress = '  # ruff:ignore[unsafe-markup-use]' if style.type_name == 'Markup' else ''
    lines.append(f'    return {style.type_name}({render}){suppress}')
    return '\n'.join(lines) + '\n'


_ANY = 'Any'
"""What an untyped header name becomes in a wrapper, which is user-facing code."""


def _declaration(param: Param) -> str:
    """One wrapper parameter, carrying the default the header declared.

    Every parameter is keyword-only, so a defaulted one may appear before an undefaulted one
    without Python objecting, and the template's own declaration order is preserved.
    """
    declared = param.annotated(_ANY)
    return declared if param.default is None else f'{declared} = {param.default}'


def _module_imports(
    header: TemplateHeader,
    validator: Validator,
    env_import: str | None,
    style: ReturnStyle,
) -> list[str]:
    imports = list(header.imports)
    env_line = env_import if env_import is not None else 'from jinja2 import Environment'
    imports.extend([style.import_line, env_line])
    if any(param.annotation is None for param in header.params):
        imports.append(f'from typing import {_ANY}')
    if validator == 'beartype':
        imports.append('from beartype import beartype')
    if validator == 'pydantic':
        imports.append('from pydantic import TypeAdapter')
    return imports


def _module_globals(header: TemplateHeader, validator: Validator, env_import: str | None) -> list[str]:
    globals_: list[str] = []
    if env_import is None:
        globals_.extend(['', '_env: Environment'])
    if validator == 'pydantic':
        globals_.append('')
        globals_.extend(f'_ta_{param.name} = TypeAdapter({param.annotation or "Any"})' for param in header.params)
    return globals_


def _slug(template_name: str) -> str:
    stem = Path(template_name).name.split('.', 1)[0]
    return ''.join(char if char.isalnum() else '_' for char in stem).strip('_')
