"""Map pyright rule names to stable typed-jinja codes (``TJ###``).

``apply_codes`` sets ``Diagnostic.code`` from ``RULE_CODES``. Rules with no
mapping keep an empty code. The rule-codes feature fills ``RULE_CODES`` and the
real assignment logic.
"""

from __future__ import annotations

from typed_jinja.diagnostic import Diagnostic

RULE_CODES: dict[str, str] = {}


def apply_codes(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Assign a stable typed-jinja code to each diagnostic (identity until filled)."""
    return diags
