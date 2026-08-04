"""``remap`` is the only thing that puts a template's own path into CI output.

Two layers of test. The recorded-payload tests pin each output format's shape and run
everywhere. The integration tests run the real checkers over a real project and assert the
remapped location lands on the identifier the checker complained about, which is the
property that actually matters and the one that survives a backend changing its columns.
"""

import re
from pathlib import Path, PurePosixPath

import pytest

from types_for_jinja import manifest
from types_for_jinja.generate import generate, write
from types_for_jinja.remap import Remapper, detect, remap

from . import backends
from .backends import EXPECTED_LINES, INVOCATIONS, STUB_DIR, TEMPLATE_PATH, Invocation, capture
from .configuration import requires_checker

_STUB = 'templates/page_html_jinja.py'
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A generated stub tree over the fixture project, with the checker's cwd at its root."""
    monkeypatch.chdir(tmp_path)
    backends.write_project(tmp_path)
    write(generate(sorted(Path('templates').glob('*.jinja')), Path(STUB_DIR)))
    return tmp_path


@pytest.fixture
def remapper(project):
    return Remapper(Path(STUB_DIR), root=project)


def _params(invocation: Invocation):
    return pytest.param(invocation, marks=requires_checker(invocation.backend), id=invocation.id)


@pytest.mark.parametrize('invocation', [_params(entry) for entry in INVOCATIONS])
def test_remapped_output_names_the_template_on_the_right_line(invocation, project, remapper):
    payload = capture(invocation, project)

    found = list(backends.template_locations(invocation.locations(remap(payload, remapper)), TEMPLATE_PATH))

    assert tuple(sorted(line for _, line, _, _ in found)) == EXPECTED_LINES


@pytest.mark.parametrize('invocation', [_params(entry) for entry in INVOCATIONS])
def test_remapped_column_points_at_the_same_identifier_the_stub_did(invocation, project, remapper):
    """Column recovery is only correct if the token survives the move.

    Backends disagree on whether to point at ``user`` or at ``naem`` in ``user.naem``, so the
    assertion is not a fixed column but that whichever name the checker chose in the stub is
    the name the template column now lands on.
    """
    payload = capture(invocation, project)
    stub_lines = (project / STUB_DIR / _STUB).read_text(encoding='utf-8').splitlines()
    template_lines = (project / TEMPLATE_PATH).read_text(encoding='utf-8').splitlines()

    before = invocation.locations(payload)
    after = invocation.locations(remap(payload, remapper))
    paired = [
        (stub, template)
        for stub, template in zip(before, after, strict=True)
        if Path(template[0]).as_posix().endswith(TEMPLATE_PATH)
    ]

    assert paired
    for (_, stub_line, stub_column, _), (_, line, column, _) in paired:
        expected = _token(stub_lines, stub_line, stub_column)
        assert expected, f'column {stub_column} of stub line {stub_line} is not on an identifier'
        assert _token(template_lines, line, column) == expected


def _token(lines: list[str], line: int, column: int) -> str:
    match = _IDENTIFIER.match(lines[line - 1], column - 1) if 0 < line <= len(lines) else None
    return match.group(0) if match else ''


@pytest.mark.parametrize('invocation', [_params(entry) for entry in INVOCATIONS])
def test_a_real_module_passes_through_untouched(invocation, project, remapper):
    """Piping a whole-project run through remap must not disturb the project's own errors."""
    payload = capture(invocation, project)

    def own(payload: str) -> list[backends.Location]:
        return [entry for entry in invocation.locations(payload) if backends.PROJECT_ERROR_PATH in entry[0]]

    before, after = own(payload), own(remap(payload, remapper))

    assert before
    assert after == before


@pytest.mark.parametrize('invocation', [_params(entry) for entry in INVOCATIONS])
def test_the_format_is_detected_without_being_named(invocation, project):
    """``ty check | types-for-jinja remap`` has to work with no flags at all."""
    payload = capture(invocation, project)

    assert detect(payload) != 'auto'


@pytest.mark.parametrize('invocation', [_params(entry) for entry in INVOCATIONS])
def test_a_generated_import_resolves_with_no_search_path_configuration(invocation, project):
    """The pitch is one generate call and the checker you already run, with nothing else set up.

    A stub imports the filter signature module and its macro sidecar by bare module name. If
    a backend cannot find those, every template using a filter reports an import error.
    """
    payload = capture(invocation, project)

    unresolved = [
        entry
        for entry in invocation.locations(payload)
        if any(word in entry[3].lower() for word in ('import', '_tj_filters', '_tj_shared'))
    ]

    assert unresolved == []


def test_a_path_outside_the_stub_tree_is_left_alone(remapper):
    line = 'app/broken.py:2:12: error: nope'

    assert remap(line, remapper) == line


def test_a_stub_the_manifest_does_not_know_is_left_alone(remapper):
    """A stray .py inside the output directory is not ours to reinterpret."""
    line = f'{STUB_DIR}/stray.py:2:12: error: nope'

    assert remap(line, remapper) == line


_MARKED_LINE = 9


def test_an_unaligned_stub_is_remapped_through_its_markers(project):
    """The rare template with no aligned form still has to report a template line."""
    (project / STUB_DIR / _STUB).write_text(f'_ = 1  # L7\n_ = 2  # L{_MARKED_LINE}\n', encoding='utf-8')
    (project / STUB_DIR / manifest.MANIFEST_NAME).write_text(
        manifest.dumps(
            manifest.Manifest(
                entries={
                    PurePosixPath(_STUB): manifest.Entry(
                        template=PurePosixPath(TEMPLATE_PATH),
                        aligned=False,
                        support=(),
                    ),
                },
            ),
        ),
        encoding='utf-8',
    )

    located = Remapper(Path(STUB_DIR), root=project).locate(f'{STUB_DIR}/{_STUB}', 2, 1)

    assert located is not None
    assert located.line == _MARKED_LINE


@requires_checker('ty')
def test_ty_full_shows_the_template_line_under_the_remapped_path(project, remapper):
    """A snippet still quoting the stub would contradict the path printed above it."""
    full = Invocation('ty', 'full', ('ty', 'check', '--extra-search-path', '.', '.'), lambda _: [])

    rewritten = remap(capture(full, project), remapper)

    assert '<h1>Hello {{ user.naem }}</h1>' in rewritten
    assert '_ = user.naem' not in rewritten
