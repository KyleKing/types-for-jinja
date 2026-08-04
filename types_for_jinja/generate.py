"""Write type-checking stubs for templates so an existing type checker run covers them.

The stubs are ordinary Python modules. Point mypy, pyright, ty, or anything else at the
output directory and template errors appear in that one run. types-for-jinja never invokes
a type checker in this mode; ``remap`` and the editor mirror carry the diagnostics back to
the template's own path through the manifest each run writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from jinja2 import TemplateSyntaxError

from types_for_jinja import filters, manifest
from types_for_jinja.config import Config, load_config
from types_for_jinja.diagnostic import Diagnostic
from types_for_jinja.emit import (
    depth_of,
    flat_name,
    mirrored_path,
    package_markers,
    relative_module,
    stale_files,
    write_files,
)
from types_for_jinja.header import header_errors, parse_header
from types_for_jinja.layout import layout
from types_for_jinja.suppress import annotate
from types_for_jinja.transpile import UnsupportedTemplateError, build_environment, transpile

_SIDECAR_SUFFIX = '_tj_shared'


@dataclass(frozen=True)
class Stub:
    """One template's generated stub and how faithfully it maps back to the template.

    ``sidecar`` names the module holding definitions this template pulled in from another
    file, with ``sidecar_line`` the local ``{% extends %}`` or ``{% include %}`` tag those
    definitions are attributed to. Without that pairing, a cross-file error would report
    against a generated path with no template attached to it at all.
    """

    template: Path
    path: Path
    files: dict[Path, str]
    aligned: bool
    sidecar: Path | None = None
    sidecar_line: int = 1


@dataclass(frozen=True)
class Generated:
    """The full set of stubs for a run, plus the templates that produced none."""

    out_dir: Path
    stubs: list[Stub]
    skipped: list[tuple[Path, str]]

    @property
    def files(self) -> dict[Path, str]:
        """Every file the run would write bar the manifest: stubs, markers, and signatures."""
        written = {path: text for stub in self.stubs for path, text in stub.files.items()}
        return {**written, **({_filter_module(self.out_dir): filters.module_source()} if self.stubs else {})}

    @property
    def unaligned(self) -> list[Path]:
        """Templates whose stub kept ``# L`` markers because no aligned form exists."""
        return [stub.template for stub in self.stubs if not stub.aligned]

    @property
    def decided(self) -> set[PurePosixPath]:
        """Templates this run reached a verdict on, whether it produced a stub or skipped one."""
        root = Path.cwd()
        looked_at = [stub.template for stub in self.stubs] + [template for template, _ in self.skipped]
        return {manifest.relative(template, root) for template in looked_at}


def generate(
    templates: list[Path],
    out_dir: Path,
    config: Config | None = None,
    sources: dict[Path, str] | None = None,
) -> Generated:
    """Build stubs for ``templates``, laid out under ``out_dir``.

    ``sources`` overrides what a template's text is taken to be, which is how the language
    server checks an unsaved buffer against the same code path as the CLI.
    """
    resolved = config or load_config(Path.cwd())
    stubs: list[Stub] = []
    skipped: list[tuple[Path, str]] = []
    for template in templates:
        outcome = _stub_for(template, out_dir, resolved, (sources or {}).get(template))
        if isinstance(outcome, str):
            skipped.append((template, outcome))
        else:
            stubs.append(outcome)
    return Generated(out_dir=out_dir, stubs=stubs, skipped=skipped)


def diagnose(source: str, template: Path, config: Config) -> list[Diagnostic]:
    """Report what stops ``template`` producing a checkable stub, empty when nothing does.

    These are the only diagnostics types-for-jinja raises itself. Everything about the types
    inside the template comes from the project's own checker reading the generated stub.
    """
    header = parse_header(source, config.syntax)
    if header is None:
        return [Diagnostic(template, 1, 1, 'warning', 'no {#def ... #} type header; skipped', 'no-header')]
    malformed = header_errors(header)
    if malformed:
        return [Diagnostic(template, header.lineno, 1, 'error', message, 'bad-header') for message in malformed]
    outcome = _stub_for(template, Path(config.out_dir), config, source)
    if not isinstance(outcome, str):
        return []
    line = _syntax_error_line(source, config) if outcome.startswith('template syntax') else header.lineno
    severity = 'error' if outcome.startswith('template syntax') else 'warning'
    return [Diagnostic(template, line, 1, severity, outcome, 'skipped')]


def _syntax_error_line(source: str, config: Config) -> int:
    """Where Jinja's own parser gave up, so the diagnostic lands on the broken tag."""
    try:
        build_environment(config.syntax).parse(source)
    except TemplateSyntaxError as err:
        return err.lineno or 1
    return 1


def plan(generated: Generated) -> tuple[dict[Path, str], list[Path]]:
    """Return the files this run writes and the stale ones it removes.

    The manifest is part of the write set, so ``--check`` fails on a tree whose bookkeeping
    no longer matches even when every stub body happens to be current.
    """
    out_dir = generated.out_dir
    previous = manifest.load(out_dir)
    merged = manifest.merge(previous, _manifest(generated), generated.decided)
    files = {**generated.files, out_dir / manifest.MANIFEST_NAME: manifest.dumps(merged)}
    return files, manifest.orphans(previous, merged, out_dir)


def write(generated: Generated) -> list[Path]:
    """Write every generated file and delete orphaned stubs, returning the paths that changed."""
    files, removed = plan(generated)
    for path in removed:
        path.unlink(missing_ok=True)
    changed = write_files(files)
    _prune_empty_dirs({path.parent for path in removed}, generated.out_dir)
    return changed + [path for path in removed if not path.is_file()]


def stale(generated: Generated) -> list[Path]:
    """Return the paths whose on-disk state no longer matches what this run would produce."""
    files, removed = plan(generated)
    return stale_files(files) + [path for path in removed if path.is_file()]


def _manifest(generated: Generated) -> manifest.Manifest:
    root = Path.cwd()
    out_dir = generated.out_dir
    shared = manifest.relative(_filter_module(out_dir), out_dir)
    entries: dict[PurePosixPath, manifest.Entry] = {}
    for stub in generated.stubs:
        template = manifest.relative(stub.template, root)
        support = sorted(manifest.relative(path, out_dir) for path in stub.files if path != stub.path)
        entries[manifest.relative(stub.path, out_dir)] = manifest.Entry(
            template=template,
            aligned=stub.aligned,
            support=(shared, *support),
        )
        if stub.sidecar is not None:
            entries[manifest.relative(stub.sidecar, out_dir)] = manifest.Entry(
                template=template,
                aligned=False,
                support=(shared,),
                fixed_line=stub.sidecar_line,
            )
    return manifest.Manifest(entries=entries)


def _filter_module(out_dir: Path) -> Path:
    return out_dir / f'{filters.MODULE_NAME}.py'


def _prune_empty_dirs(candidates: set[Path], out_dir: Path) -> None:
    """Remove mirrored directories left empty once their last stub was deleted."""
    for directory in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        current = directory
        while current != out_dir and out_dir in current.parents and current.is_dir() and not any(current.iterdir()):
            current.rmdir()
            current = current.parent


def _stub_for(template: Path, out_dir: Path, config: Config, override: str | None = None) -> Stub | str:
    source = template.read_text(encoding='utf-8') if override is None else override
    header = parse_header(source, config.syntax)
    if header is None:
        return 'no {#def ... #} type header'
    stub_path = mirrored_path(template, out_dir)
    depth = depth_of(stub_path, out_dir)
    try:
        module = transpile(source, header, config, template_path=template, depth=depth)
    except TemplateSyntaxError as err:
        return f'template syntax error: {err.message}'
    except UnsupportedTemplateError as err:
        return f'unsupported template construct: {err}'
    shared = f'{flat_name(template)}{_SIDECAR_SUFFIX}'
    aligned = layout(module, header, relative_module(shared, depth))
    if aligned is None:
        marked = annotate(module.code, source, config.suppression, aligned=False)
        marker_files = {stub_path: marked, **package_markers(out_dir, stub_path)}
        return Stub(template=template, path=stub_path, files=marker_files, aligned=False)
    code = annotate(aligned.code, source, config.suppression, aligned=True)
    files = {stub_path: code, **package_markers(out_dir, stub_path)}
    sidecar = out_dir / f'{shared}.py' if aligned.sidecar else None
    if sidecar is not None:
        files[sidecar] = aligned.sidecar
    return Stub(
        template=template,
        path=stub_path,
        files=files,
        aligned=True,
        sidecar=sidecar,
        sidecar_line=aligned.sidecar_line,
    )
