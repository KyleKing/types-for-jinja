"""Tests for stable rule codes and inline suppression."""

import json
from pathlib import Path

from types_for_jinja.codes import apply_codes
from types_for_jinja.diagnostic import Diagnostic
from types_for_jinja.report import format_json, format_sarif, format_text
from types_for_jinja.suppress import apply_suppressions


def _diag(line, rule, code=''):
    return Diagnostic(Path('t.html'), line, 1, 'error', 'msg', rule, code)


def test_apply_codes_maps_common_rules():
    coded = apply_codes([_diag(1, 'reportUndefinedVariable'), _diag(2, 'reportAttributeAccessIssue')])

    assert [d.code for d in coded] == ['TJ001', 'TJ002']


def test_apply_codes_leaves_unknown_rule_empty():
    assert not apply_codes([_diag(1, 'reportSomethingNew')])[0].code


def test_bare_ignore_drops_only_its_line():
    source = 'line one\n{{ x }} {# type: ignore #}\nline three\n'
    diags = [_diag(2, 'reportUndefinedVariable', 'TJ001'), _diag(3, 'reportUndefinedVariable', 'TJ001')]

    kept = apply_suppressions(source, diags)

    assert [d.line for d in kept] == [3]


def test_code_scoped_ignore_drops_only_named_code():
    source = 'a\n{{ y }} {# type: ignore[TJ002] #}\n'
    same_line = [_diag(2, 'reportAttributeAccessIssue', 'TJ002'), _diag(2, 'reportUndefinedVariable', 'TJ001')]

    kept = apply_suppressions(source, same_line)

    assert [d.code for d in kept] == ['TJ001']


def test_whitespace_control_ignore_is_recognized():
    source = 'a\n{{ z }} {#- type: ignore -#}\n'

    assert apply_suppressions(source, [_diag(2, 'reportUndefinedVariable', 'TJ001')]) == []


def test_reports_carry_the_code():
    diags = apply_codes([_diag(5, 'reportAttributeAccessIssue')])

    assert '(TJ002 reportAttributeAccessIssue)' in format_text(diags)
    assert json.loads(format_json(diags))[0]['code'] == 'TJ002'
    assert json.loads(format_sarif(diags))['runs'][0]['results'][0]['ruleId'] == 'TJ002'
