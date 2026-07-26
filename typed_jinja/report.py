"""Format checker diagnostics as text, JSON, or SARIF 2.1.0."""

from __future__ import annotations

import json
from typing import Any

from typed_jinja.diagnostic import Diagnostic

_SARIF_SCHEMA = 'https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json'
_SARIF_LEVELS = {'error': 'error', 'warning': 'warning'}


def format_text(diags: list[Diagnostic]) -> str:
    """Render diagnostics as one ``path:line:column severity: message (rule)`` per line."""
    return '\n'.join(_text_line(diag) for diag in diags)


def format_json(diags: list[Diagnostic]) -> str:
    """Render diagnostics as a JSON array of flat objects."""
    payload = [
        {
            'path': str(diag.path),
            'line': diag.line,
            'column': diag.column,
            'severity': diag.severity,
            'message': diag.message,
            'rule': diag.rule,
            'code': diag.code,
        }
        for diag in diags
    ]
    return json.dumps(payload, indent=2)


def format_sarif(diags: list[Diagnostic]) -> str:
    """Render diagnostics as a minimal, valid SARIF 2.1.0 document."""
    document: dict[str, Any] = {
        '$schema': _SARIF_SCHEMA,
        'version': '2.1.0',
        'runs': [
            {
                'tool': {'driver': {'name': 'typed-jinja', 'rules': _sarif_rules(diags)}},
                'results': [_sarif_result(diag) for diag in diags],
            },
        ],
    }
    return json.dumps(document, indent=2)


def _text_line(diag: Diagnostic) -> str:
    tag = f'{diag.code} {diag.rule}'.strip() if diag.code else diag.rule
    suffix = f' ({tag})' if tag else ''
    return f'{diag.path}:{diag.line}:{diag.column} {diag.severity}: {diag.message}{suffix}'


def _sarif_rules(diags: list[Diagnostic]) -> list[dict[str, str]]:
    return [{'id': rule_id} for rule_id in sorted({diag.code or diag.rule for diag in diags if diag.code or diag.rule})]


def _sarif_result(diag: Diagnostic) -> dict[str, Any]:
    return {
        'ruleId': diag.code or diag.rule or 'typed-jinja',
        'level': _SARIF_LEVELS.get(diag.severity, 'warning'),
        'message': {'text': diag.message},
        'properties': {'pyrightRule': diag.rule},
        'locations': [
            {
                'physicalLocation': {
                    'artifactLocation': {'uri': str(diag.path)},
                    'region': {'startLine': diag.line, 'startColumn': diag.column},
                },
            },
        ],
    }
