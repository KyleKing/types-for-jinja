"""Drop diagnostics on template lines marked with an inline ignore comment.

The suppression feature parses ``{# type: ignore #}`` (and code-scoped variants
like ``{# type: ignore[TJ002] #}``) from the template source and removes matching
diagnostics. Identity until filled.
"""

from __future__ import annotations

from typed_jinja.diagnostic import Diagnostic


def apply_suppressions(source: str, diags: list[Diagnostic]) -> list[Diagnostic]:  # ruff:ignore[unused-function-argument]
    """Remove diagnostics suppressed by inline ignore comments (identity until filled)."""
    return diags
