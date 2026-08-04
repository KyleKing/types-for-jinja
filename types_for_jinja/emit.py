"""Lay generated Python modules out under an output directory and write them idempotently.

Both the type-checking stubs and the typed render wrappers mirror the template tree, so
a generated path reads back as the template it came from.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    'depth_of',
    'flat_name',
    'mirrored_path',
    'package_markers',
    'relative_module',
    'stale_files',
    'write_files',
]


def mirrored_path(template: Path, out_dir: Path) -> Path:
    """Mirror the template's own directories under ``out_dir``.

    Only the filename is mangled, because a module name cannot carry the template's
    extension: ``templates/greeting.html`` becomes ``templates/greeting_html.py``.
    """
    relative = _project_relative(template)
    return out_dir / relative.with_name(flat_name(Path(relative.name)) + '.py')


def _project_relative(template: Path) -> Path:
    """Where the template sits relative to the project, with the anchor dropped if it is outside.

    A template outside the project still needs a unique mirrored path rather than an error,
    because a caller may hand over an absolute path from anywhere.
    """
    if not template.is_absolute():
        return template
    root, resolved = Path.cwd().resolve(), template.resolve()
    return resolved.relative_to(root) if resolved.is_relative_to(root) else Path(*resolved.parts[1:])


def flat_name(template: Path) -> str:
    """Collapse a path into a single Python-safe identifier."""
    return ''.join(char if char.isalnum() else '_' for char in str(template)).strip('_')


def package_markers(out_dir: Path, generated: Path) -> dict[Path, str]:
    """Mark the output tree as a package, from ``out_dir`` down to ``generated``'s directory.

    Two reasons the root marker matters. Same-named modules in sibling trees coexist, and the
    generated stub-to-stub imports are relative, which a checker only resolves for a module it
    can see is inside a package.
    """
    markers: dict[Path, str] = {out_dir / '__init__.py': ''}
    parent = generated.parent
    while parent != out_dir and out_dir in parent.parents:
        markers[parent / '__init__.py'] = ''
        parent = parent.parent
    return markers


def depth_of(generated: Path, out_dir: Path) -> int:
    """How many directories separate ``generated`` from the root of ``out_dir``."""
    return len(generated.parent.relative_to(out_dir).parts) if generated.parent != out_dir else 0


def relative_module(name: str, depth: int) -> str:
    """Reference a module at the root of the output tree from ``depth`` directories down.

    Relative because an absolute dotted name would have to assume where the checker puts its
    root, which changes when the output directory moves.
    """
    return '.' * (depth + 1) + name


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
