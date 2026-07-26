"""The Diagnostic value type, shared by the checker, reporters, and LSP."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Diagnostic:
    """A type error located back in the original template.

    ``rule`` is pyright's own rule name. ``code`` is the stable typed-jinja code
    (for example ``TJ001``) assigned from ``rule``, empty when unmapped.
    """

    path: Path
    line: int
    column: int
    severity: str
    message: str
    rule: str
    code: str = ''
