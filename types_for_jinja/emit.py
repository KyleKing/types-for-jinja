"""Lay generated Python modules out under an output directory and write them idempotently.

Both the type-checking stubs and the typed render wrappers mirror the template tree, so
a generated path reads back as the template it came from.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ['flat_name', 'mirrored_path', 'package_markers', 'stale_files', 'write_files']


def mirrored_path(template: Path, out_dir: Path) -> Path:
    """Mirror the template's own directories under ``out_dir``.

    Only the filename is mangled, because a module name cannot carry the template's
    extension: ``templates/greeting.html`` becomes ``templates/greeting_html.py``.
    """
    relative = template.relative_to(Path.cwd()) if template.is_absolute() else template
    return out_dir / relative.with_name(flat_name(Path(relative.name)) + '.py')


def flat_name(template: Path) -> str:
    """Collapse a path into a single Python-safe identifier."""
    return ''.join(char if char.isalnum() else '_' for char in str(template)).strip('_')


def package_markers(out_dir: Path, generated: Path) -> dict[Path, str]:
    """Mark mirrored directories as packages so same-named modules in sibling trees coexist."""
    markers: dict[Path, str] = {}
    parent = generated.parent
    while parent != out_dir and out_dir in parent.parents:
        markers[parent / '__init__.py'] = ''
        parent = parent.parent
    return markers


def write_files(files: dict[Path, str]) -> list[Path]:
    """Write every file whose contents differ, returning the paths that changed."""
    changed: list[Path] = []
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
            changed.append(path)
    return changed


def stale_files(files: dict[Path, str]) -> list[Path]:
    """Return the paths that are missing or no longer match what would be generated."""
    return [path for path, text in files.items() if not path.is_file() or path.read_text(encoding='utf-8') != text]
