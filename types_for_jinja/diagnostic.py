"""The Diagnostic value type, shared by ``generate`` and the language server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Diagnostic:
    """Something types-for-jinja itself found, located in the template.

    Only the four cases it can determine without a type checker: a missing or malformed
    ``{#def #}`` header, a Jinja syntax error, and a construct the transpiler cannot model.
    Everything about the types comes from the project's own checker reading the stub.

    ``reason`` is a short stable tag (``no-header``, ``bad-header``, ``syntax-error``,
    ``skipped``) for a client that wants to group these without matching on the message.
    """

    path: Path
    line: int
    column: int
    severity: str
    message: str
    reason: str
