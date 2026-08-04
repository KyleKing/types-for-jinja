"""The aligned stubs and their sidecars must be valid Python and line-aligned."""

import ast
import json
import shutil
import subprocess  # ruff:ignore[suspicious-subprocess-import]
from pathlib import Path

from types_for_jinja.check import check_file
from types_for_jinja.config import Config
from types_for_jinja.generate import generate, write
from types_for_jinja.header import parse_header
from types_for_jinja.layout import layout
from types_for_jinja.transpile import transpile

from .configuration import requires_pyright

_EXAMPLES = Path('examples')


def _generated(tmp_path):
    return generate(sorted(_EXAMPLES.rglob('*.html.jinja')) + sorted(_EXAMPLES.rglob('*.html')), tmp_path)


def test_every_generated_file_parses(tmp_path):
    for path, text in _generated(tmp_path).files.items():
        ast.parse(text, filename=str(path))


def test_aligned_stub_keeps_template_line_numbers(tmp_path):
    generated = _generated(tmp_path)

    assert generated.stubs
    assert generated.unaligned == []


def test_sidecar_binds_the_declared_context(tmp_path):
    """An unbound name in the sidecar buries the real errors from the other template."""
    sidecars = [text for path, text in _generated(tmp_path).files.items() if '_tj_shared' in path.name]

    assert sidecars
    for text in sidecars:
        assert 'current_route: str = _tj_any' in text or 'current_route' not in text


@requires_pyright
def test_generated_stubs_report_what_the_checker_reports(tmp_path):
    """The bring-your-own-checker path must agree with `types-for-jinja check`."""
    out_dir = tmp_path / 'stubs'
    write(_generated(out_dir))
    (out_dir / 'pyrightconfig.json').write_text(
        json.dumps({'include': ['.'], 'extraPaths': [str(Path.cwd().resolve())]}),
        encoding='utf-8',
    )

    result = subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true]
        [shutil.which('pyright') or 'pyright', '--outputjson'],
        cwd=out_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    raw = json.loads(result.stdout)['generalDiagnostics']
    reported = sorted(
        (Path(entry['file']).name, entry['range']['start']['line'] + 1) for entry in raw if entry['severity'] == 'error'
    )
    template = Path('examples/templates/greeting_bad.html.jinja')
    expected = sorted(
        ('greeting_bad_html_jinja.py', diag.line) for diag in check_file(template, cache_dir=tmp_path / 'cache')
    )

    assert reported == expected


def _aligned(source):
    header = parse_header(source)
    assert header is not None
    return layout(transpile(source, header, Config()), header, 'shared')


def test_inline_conditional_has_an_aligned_form():
    """Two compound statements cannot share a line, so if/else collapses to an expression."""
    source = '{#def\nname: str\n#}\n<p>{% if name %}{{ name.a }}{% else %}{{ name.b }}{% endif %}</p>\n'

    aligned = _aligned(source)

    assert aligned is not None
    assert aligned.code.splitlines()[3] == '_ = (name.a if name else name.b)'


def test_multi_statement_branch_still_has_no_aligned_form():
    """Only a branch that is a single checked expression fits in a conditional expression."""
    source = '{#def\nname: str\n#}\n<p>{% if name %}{{ name.a }}{{ name.c }}{% else %}{{ name.b }}{% endif %}</p>\n'

    assert _aligned(source) is None


def test_unsupported_construct_skips_one_template(tmp_path):
    """A namespace assignment used to raise out of transpile and take down the whole run."""
    source = '{#def\nname: str\n#}\n{% set ns = namespace(n=0) %}\n{% set ns.n = 1 %}\n'
    template = tmp_path / 'ns.html.jinja'
    template.write_text(source, encoding='utf-8')

    generated = generate([Path('examples/templates/greeting_bad.html.jinja'), template], tmp_path / 'out')

    assert [reason for path, reason in generated.skipped if path == template] == [
        'unsupported template construct: NSRef'
    ]
    assert generated.stubs
