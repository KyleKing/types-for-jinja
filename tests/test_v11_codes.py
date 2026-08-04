"""Tests for stable rule codes and inline suppression."""

import json
from pathlib import Path

import pytest

from types_for_jinja.codes import apply_codes
from types_for_jinja.config import load_config
from types_for_jinja.diagnostic import Diagnostic
from types_for_jinja.report import format_json, format_sarif, format_text
from types_for_jinja.suppress import STYLES, annotate, apply_suppressions


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


_TEMPLATE = '{#def\nname: str\n#}\n{{ name.bad }}{# type: ignore #}\n{{ name.worse }}\n'


def test_annotate_marks_the_aligned_line_only():
    code = 'preamble\n\n\n_ = name.bad\n_ = name.worse\n'

    annotated = annotate(code, _TEMPLATE, 'portable', aligned=True).splitlines()

    assert annotated[3] == '_ = name.bad  # type: ignore'
    assert annotated[4] == '_ = name.worse'


def test_annotate_keeps_the_line_marker_last():
    """`_template_line` reads the marker off the end, so the ignore goes in front of it."""
    code = '    _ = name.bad  # L4\n    _ = name.worse  # L5\n'

    annotated = annotate(code, _TEMPLATE, 'portable', aligned=False).splitlines()

    assert annotated[0] == '    _ = name.bad  # type: ignore  # L4'
    assert annotated[1] == '    _ = name.worse  # L5'


def test_each_style_emits_its_own_checker_spelling():
    code = 'preamble\n\n\n_ = name.bad\n'
    emitted = {style: annotate(code, _TEMPLATE, style, aligned=True).splitlines()[3] for style in STYLES}

    assert emitted['portable'].endswith('# type: ignore')
    assert emitted['pyright'].endswith('# pyright: ignore')
    assert emitted['ty'].endswith('# ty: ignore')


def test_annotate_leaves_a_template_without_ignores_untouched():
    code = '_ = name.bad\n'

    assert annotate(code, '{{ name.bad }}\n', 'portable', aligned=True) == code


def test_unknown_suppression_style_is_rejected(tmp_path):
    """Falling back silently would emit ignore comments the project's checker never honours."""
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja]\nsuppression = "pyrite"\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='unknown suppression style'):
        load_config(tmp_path)
