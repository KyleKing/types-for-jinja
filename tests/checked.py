"""Check a template the way a project does: generate a stub, run a checker, remap the output.

This replaces the old in-process ``check_file``. Tests that used to assert pyright's rule
names now assert what any backend agrees on, which is the template line an error lands on
and the identifier its message is about. The full backend matrix lives in
``tests/test_backends.py``; these helpers run one backend so a semantic test stays quick.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from types_for_jinja.config import Config
from types_for_jinja.diagnostic import Diagnostic
from types_for_jinja.generate import diagnose, generate, write
from types_for_jinja.remap import Remapper, remap

from . import backends
from .backends import STUB_DIR, Invocation, capture

DEFAULT_BACKEND = 'ty'
"""Fastest of the three, and it needs no config file. Rule names never leak into a test."""

_INVOCATIONS = {entry.backend: entry for entry in backends.INVOCATIONS if entry.label in {'concise', 'text', 'json'}}


@dataclass(frozen=True)
class Reported:
    """One error a checker reported, located back in the template."""

    line: int
    column: int
    message: str

    def mentions(self, word: str) -> bool:
        """Whether the checker's own wording names ``word``, however it phrased the rest."""
        return word in self.message


def lay_out(root: Path, *, examples: bool = False) -> Path:
    """Lay out a checkable project in ``root``, optionally with the repo's ``examples/`` copied in.

    Copies rather than pointing at ``examples/`` in place, so a run never writes stubs into
    the repository.
    """
    source = Path('examples').resolve()
    backends.write_project(root)
    if examples:
        shutil.copytree(source, root / 'examples', ignore=shutil.ignore_patterns('__pycache__'))
    return root


def write_template(relative: str, source: str) -> Path:
    """Write one template in the current project and return its project-relative path."""
    path = Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')
    return path


def reported(template: Path, config: Config | None = None, backend: str = DEFAULT_BACKEND) -> list[Reported]:
    """Generate every template in the current project and return what ``backend`` says about one.

    Generating the whole tree rather than a single file matters for the cross-file cases,
    where a base template or a macro file has to be present for the stub to mean anything.
    Assumes the working directory is the project root, which the ``project`` fixtures arrange.
    """
    root = Path.cwd()
    templates = sorted(path.relative_to(root) for path in root.rglob('*.jinja') if STUB_DIR not in path.parts)
    write(generate(templates, Path(STUB_DIR), config))
    invocation = _INVOCATIONS[backend]
    remapper = Remapper(Path(STUB_DIR), root=root)
    found = invocation.locations(remap(capture(invocation, root), remapper))
    wanted = template.as_posix()
    return sorted(
        (
            Reported(line=line, column=column, message=message)
            for path, line, column, message in found
            if Path(path).as_posix() == wanted
        ),
        key=lambda entry: (entry.line, entry.column),
    )


def skipped(source: str, template: Path, config: Config | None = None) -> list[Diagnostic]:
    """What types-for-jinja itself says about a template, before any checker sees it."""
    return diagnose(source, template, config or Config(out_dir=STUB_DIR))


def one_backend(backend: str) -> Invocation:
    """The invocation ``reported`` uses for ``backend``, for a test that needs it directly."""
    return _INVOCATIONS[backend]
