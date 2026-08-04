"""Write type-checking stubs for templates so an existing type checker run covers them.

The stubs are ordinary Python modules. Point mypy, pyright, ty, or anything else at the
output directory and template errors appear in that one run, reported against the
template's own file and line. types-for-jinja never invokes a type checker in this mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import TemplateSyntaxError

from types_for_jinja import filters
from types_for_jinja.config import Config, load_config
from types_for_jinja.emit import flat_name, mirrored_path, package_markers, stale_files, write_files
from types_for_jinja.header import parse_header
from types_for_jinja.layout import layout
from types_for_jinja.transpile import transpile

_SIDECAR_SUFFIX = '_tj_shared'


@dataclass(frozen=True)
class Stub:
    """One template's generated stub and how faithfully it maps back to the template."""

    template: Path
    files: dict[Path, str]
    aligned: bool


@dataclass(frozen=True)
class Generated:
    """The full set of stubs for a run, plus the templates that produced none."""

    stubs: list[Stub]
    skipped: list[tuple[Path, str]]

    @property
    def files(self) -> dict[Path, str]:
        """Every file the run would write: stubs, package markers, and the filter signatures."""
        return {path: text for stub in self.stubs for path, text in stub.files.items()}

    @property
    def unaligned(self) -> list[Path]:
        """Templates whose stub kept ``# L`` markers because no aligned form exists."""
        return [stub.template for stub in self.stubs if not stub.aligned]


def generate(templates: list[Path], out_dir: Path, config: Config | None = None) -> Generated:
    """Build stubs for ``templates``, laid out under ``out_dir``."""
    resolved = config or load_config(Path.cwd())
    stubs: list[Stub] = []
    skipped: list[tuple[Path, str]] = []
    for template in templates:
        outcome = _stub_for(template, out_dir, resolved)
        if isinstance(outcome, str):
            skipped.append((template, outcome))
        else:
            stubs.append(outcome)
    if stubs:
        stubs.append(_filter_stub(out_dir))
    return Generated(stubs=stubs, skipped=skipped)


def _filter_stub(out_dir: Path) -> Stub:
    """The filter signatures every generated stub imports from."""
    path = out_dir / f'{filters.MODULE_NAME}.py'
    return Stub(template=path, files={path: filters.module_source()}, aligned=True)


def write(generated: Generated) -> list[Path]:
    """Write every generated file, returning the paths that changed on disk."""
    return write_files(generated.files)


def stale(generated: Generated) -> list[Path]:
    """Return the stubs whose on-disk contents no longer match their template."""
    return stale_files(generated.files)


def _stub_for(template: Path, out_dir: Path, config: Config) -> Stub | str:
    source = template.read_text(encoding='utf-8')
    header = parse_header(source, config.syntax)
    if header is None:
        return 'no {#def ... #} type header'
    try:
        module = transpile(source, header, config, template_path=template)
    except TemplateSyntaxError as err:
        return f'template syntax error: {err.message}'
    stub_path = mirrored_path(template, out_dir)
    shared = f'{flat_name(template)}{_SIDECAR_SUFFIX}'
    aligned = layout(module, header, shared)
    if aligned is None:
        return Stub(template=template, files={stub_path: module.code}, aligned=False)
    files = {stub_path: aligned.code, **package_markers(out_dir, stub_path)}
    if aligned.sidecar:
        files[out_dir / f'{shared}.py'] = aligned.sidecar
    return Stub(template=template, files=files, aligned=True)
