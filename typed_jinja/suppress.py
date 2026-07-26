"""Drop diagnostics on template lines marked with an inline ignore comment.

Supported forms, matched on the same source line as the flagged expression:

- ``{# type: ignore #}`` suppresses every diagnostic on that line
- ``{# type: ignore[TJ002] #}`` suppresses only the listed codes (comma-separated)

The whitespace-control forms ``{#- ... -#}`` are handled too.
"""

from __future__ import annotations

import re

from typed_jinja.diagnostic import Diagnostic

_IGNORE_RE = re.compile(r'\{#-?\s*type:\s*ignore(?:\[(?P<codes>[^\]]*)\])?\s*-?#\}')


def apply_suppressions(source: str, diags: list[Diagnostic]) -> list[Diagnostic]:
    """Remove diagnostics suppressed by an inline ignore comment on the same line."""
    ignores = _collect_ignores(source)
    if not ignores:
        return diags
    return [diag for diag in diags if not _suppressed(diag, ignores)]


def _collect_ignores(source: str) -> dict[int, frozenset[str] | None]:
    ignores: dict[int, frozenset[str] | None] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        match = _IGNORE_RE.search(line)
        if match is None:
            continue
        spec = match.group('codes')
        ignores[lineno] = None if spec is None else frozenset(c.strip() for c in spec.split(',') if c.strip())
    return ignores


def _suppressed(diag: Diagnostic, ignores: dict[int, frozenset[str] | None]) -> bool:
    if diag.line not in ignores:
        return False
    codes = ignores[diag.line]
    return codes is None or diag.code in codes
