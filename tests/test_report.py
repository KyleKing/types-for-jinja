"""Tests for the text / JSON / SARIF formatters."""

import json
from pathlib import Path

from typed_jinja.diagnostic import Diagnostic
from typed_jinja.report import format_json, format_sarif, format_text

_DIAGS = [
    Diagnostic(Path('a.html'), 5, 12, 'error', 'Cannot access attribute "naem"', 'reportAttributeAccessIssue', 'TJ002'),
    Diagnostic(Path('a.html'), 11, 8, 'error', '"author" is not defined', 'reportUndefinedVariable', 'TJ001'),
]


def test_format_json_round_trips():
    payload = json.loads(format_json(_DIAGS))

    assert len(payload) == len(_DIAGS)
    assert payload[0] == {
        'path': 'a.html',
        'line': 5,
        'column': 12,
        'severity': 'error',
        'message': 'Cannot access attribute "naem"',
        'rule': 'reportAttributeAccessIssue',
        'code': 'TJ002',
    }


def test_format_text_shows_code_and_rule():
    line = format_text(_DIAGS).splitlines()[0]

    assert '(TJ002 reportAttributeAccessIssue)' in line


def test_format_sarif_is_valid_2_1_0():
    document = json.loads(format_sarif(_DIAGS))

    assert document['version'] == '2.1.0'
    run = document['runs'][0]
    assert run['tool']['driver']['name'] == 'typed-jinja'
    assert len(run['results']) == len(_DIAGS)
    first = run['results'][0]
    assert first['ruleId'] == 'TJ002'
    assert first['properties']['pyrightRule'] == 'reportAttributeAccessIssue'
    region = first['locations'][0]['physicalLocation']['region']
    assert region == {'startLine': _DIAGS[0].line, 'startColumn': _DIAGS[0].column}
