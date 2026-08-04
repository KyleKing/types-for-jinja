"""Map pyright rule names to stable types-for-jinja codes (``TJ###``).

``apply_codes`` sets ``Diagnostic.code`` from ``RULE_CODES``. Rules with no
mapping keep an empty code.

Code catalog:

- ``TJ000`` no ``{#def ... #}`` type header, template skipped
- ``TJ001`` undefined variable
- ``TJ002`` bad attribute access on a typed object
- ``TJ003`` bad index or key access
- ``TJ004`` bad call (for example a macro called with the wrong arguments)
- ``TJ005`` argument of the wrong type
- ``TJ006`` general type error
- ``TJ010`` template syntax error
- ``TJ011`` malformed ``{#def ... #}`` header
"""

from __future__ import annotations

from dataclasses import replace

from types_for_jinja.diagnostic import Diagnostic

RULE_CODES: dict[str, str] = {
    'bad-header': 'TJ011',
    'no-header': 'TJ000',
    'reportArgumentType': 'TJ005',
    'reportAttributeAccessIssue': 'TJ002',
    'reportCallIssue': 'TJ004',
    'reportGeneralTypeIssues': 'TJ006',
    'reportIndexIssue': 'TJ003',
    'reportUndefinedVariable': 'TJ001',
    'syntax-error': 'TJ010',
}


def apply_codes(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Assign a stable types-for-jinja code to each diagnostic from its pyright rule."""
    return [replace(diag, code=RULE_CODES.get(diag.rule, diag.code)) for diag in diags]
