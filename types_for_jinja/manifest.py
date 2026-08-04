"""Record which generated stub came from which template.

``generate`` writes the manifest beside the stubs. ``remap`` reads it to name the template
instead of the stub in a checker's output, editor mirroring reads it to republish stub
diagnostics onto the template buffer, and ``generate`` itself reads the previous one so a
renamed or deleted template does not leave a stub behind reporting phantom errors against
a file nobody can open.

Stub paths are stored relative to the output directory and template paths relative to the
project root, both with forward slashes, so a manifest written on one platform reads on
another.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = '.manifest.json'
"""Named with a leading dot so a checker pointed at the stub tree never tries to read it."""

_VERSION = 1


@dataclass(frozen=True)
class Entry:
    """One stub, the template it came from, and the files that stub needs beside it.

    ``support`` holds the package markers, sidecar, and filter signatures the stub imports
    or sits inside. Tracking them per stub is what lets a later run work out that removing
    the last stub in a directory also makes its ``__init__.py`` dead.
    """

    template: PurePosixPath
    aligned: bool
    support: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class Manifest:
    """Every stub an output directory holds, keyed by the stub's path within it."""

    entries: dict[PurePosixPath, Entry]

    @property
    def files(self) -> set[PurePosixPath]:
        """Every file the manifest accounts for, stubs and support alike."""
        return {*self.entries, *(path for entry in self.entries.values() for path in entry.support)}

    def template_for(self, stub: PurePosixPath) -> Path | None:
        """The template a stub came from, or ``None`` for a path the manifest does not know."""
        entry = self.entries.get(stub)
        return None if entry is None else Path(entry.template)

    def aligned(self, stub: PurePosixPath) -> bool:
        """Whether the stub is line-aligned; an unknown stub is treated as marker-based."""
        entry = self.entries.get(stub)
        return entry is not None and entry.aligned

    def stub_for(self, template: PurePosixPath) -> PurePosixPath | None:
        """The stub a template generates, or ``None`` if it generates none."""
        return next((stub for stub, entry in self.entries.items() if entry.template == template), None)


def relative(path: Path, base: Path) -> PurePosixPath:
    """Express ``path`` under ``base`` as a portable relative path."""
    resolved = path.resolve()
    root = base.resolve()
    return PurePosixPath(resolved.relative_to(root) if resolved.is_relative_to(root) else path)


def load(out_dir: Path) -> Manifest:
    """Read the manifest in ``out_dir``; an empty manifest when it is absent or unreadable."""
    path = out_dir / MANIFEST_NAME
    if not path.is_file():
        return Manifest(entries={})
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return Manifest(entries={})
    return Manifest(entries=_entries(payload))


def _entries(payload: Any) -> dict[PurePosixPath, Entry]:
    if not isinstance(payload, dict) or payload.get('version') != _VERSION:
        return {}
    stubs = payload.get('stubs')
    if not isinstance(stubs, dict):
        return {}
    return {
        PurePosixPath(stub): Entry(
            template=PurePosixPath(str(raw['template'])),
            aligned=bool(raw.get('aligned', False)),
            support=tuple(PurePosixPath(str(item)) for item in raw.get('support', ())),
        )
        for stub, raw in stubs.items()
        if isinstance(raw, dict) and 'template' in raw
    }


def dumps(man: Manifest) -> str:
    """Render ``man`` as sorted JSON, so an unchanged run rewrites byte-identical output."""
    payload = {
        'version': _VERSION,
        'stubs': {
            str(stub): {
                'template': str(entry.template),
                'aligned': entry.aligned,
                'support': [str(path) for path in sorted(entry.support)],
            }
            for stub, entry in sorted(man.entries.items())
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False) + '\n'


def merge(previous: Manifest, current: Manifest, decided: set[PurePosixPath]) -> Manifest:
    """Fold this run's entries into the previous manifest.

    ``decided`` names the templates this run looked at. An earlier entry for one of them is
    replaced by whatever the run produced, which is nothing when the template lost its
    ``{#def #}`` header. Entries for templates the run never saw survive as long as the
    template is still on disk, so generating one file does not delete the rest of the tree.
    """
    kept = {
        stub: entry
        for stub, entry in previous.entries.items()
        if entry.template not in decided and Path(entry.template).is_file()
    }
    return Manifest(entries={**kept, **current.entries})


def stub_path_for(template: Path, out_dir: Path) -> Path | None:
    """Where ``template``'s stub lives on disk, or ``None`` when the manifest has no entry."""
    found = load(out_dir).stub_for(relative(template, Path.cwd()))
    return None if found is None else out_dir / found


def orphans(previous: Manifest, merged: Manifest, out_dir: Path) -> list[Path]:
    """Files the previous manifest owned that nothing in ``merged`` needs any more."""
    return sorted(out_dir / path for path in previous.files - merged.files)
