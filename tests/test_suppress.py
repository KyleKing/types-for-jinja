"""Inline ``{# type: ignore #}`` comments, carried into the generated stub.

The TJ### codes are gone with the subprocess that owned them, so nothing here translates a
rule name. The emitted comment is a blanket ignore in whatever spelling the project's checker
honours, because the same rule is named differently by each and an unknown name is itself an
error.
"""

import pytest

from types_for_jinja.config import load_config
from types_for_jinja.suppress import STYLES, annotate, ignored_lines

_TEMPLATE = '{#def\nname: str\n#}\n{{ name.bad }}{# type: ignore #}\n{{ name.worse }}\n'


def test_ignored_lines_finds_the_marked_line_only():
    assert ignored_lines(_TEMPLATE) == {4}


def test_whitespace_control_ignore_is_recognized():
    assert ignored_lines('a\n{{ z }} {#- type: ignore -#}\n') == {2}


def test_a_bracketed_code_still_marks_the_line():
    """The code is read but not carried over, since checker rule names are not portable."""
    assert ignored_lines('a\n{{ y }} {# type: ignore[attr-defined] #}\n') == {2}


def test_annotate_marks_the_aligned_line_only():
    code = 'preamble\n\n\n_ = name.bad\n_ = name.worse\n'

    annotated = annotate(code, _TEMPLATE, 'portable', aligned=True).splitlines()

    assert annotated[3] == '_ = name.bad  # type: ignore'
    assert annotated[4] == '_ = name.worse'


def test_annotate_keeps_the_line_marker_last():
    """A checker only honours the directive when it opens the comment, so it goes in front."""
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
    assert emitted['mypy'].endswith('# type: ignore')


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
