"""The manifest is the only record tying a stub back to its template.

Two things depend on it being right. ``remap`` and the editor mirror read it to name the
template instead of the stub, and ``generate`` reads the previous one to delete stubs whose
template is gone. A missed deletion is worse than a missing feature: the stale stub keeps
reporting errors against a file that no longer exists, and a batch check has no way to tell
that from a real one.
"""

import json
from pathlib import Path, PurePosixPath

import pytest

from types_for_jinja import manifest
from types_for_jinja.generate import generate, plan, stale, write

_OK = """\
{#def
name: str
#}
<p>{{ name.upper() }}</p>
"""
_BAD = """\
{#def
name: str
#}
<p>{{ name.nope }}</p>
"""
_HEADERLESS = '<p>{{ whatever }}</p>\n'


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'pages').mkdir()
    return tmp_path


def _write(project, relative, source):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')
    return Path(relative)


def _run(templates, out_dir=Path('_jinja_stubs')):
    return write(generate(list(templates), out_dir))


def _loaded(out_dir=Path('_jinja_stubs')):
    return manifest.load(out_dir)


def test_manifest_names_the_template_each_stub_came_from(project):
    template = _write(project, 'pages/one.html.jinja', _OK)

    _run([template])
    man = _loaded()

    assert man.template_for(PurePosixPath('pages/one_html_jinja.py')) == template


def test_manifest_records_whether_the_stub_is_line_aligned(project):
    """``remap`` reads the stub's own ``# L`` markers only when this says it must."""
    template = _write(project, 'pages/one.html.jinja', _OK)

    _run([template])

    assert _loaded().aligned(PurePosixPath('pages/one_html_jinja.py'))


def test_a_deleted_template_takes_its_stub_with_it(project):
    kept = _write(project, 'pages/kept.html.jinja', _OK)
    doomed = _write(project, 'pages/doomed.html.jinja', _BAD)
    _run([kept, doomed])
    stub = project / '_jinja_stubs/pages/doomed_html_jinja.py'
    assert stub.is_file()

    (project / doomed).unlink()
    _run([kept])

    assert not stub.is_file()
    assert (project / '_jinja_stubs/pages/kept_html_jinja.py').is_file()
    assert set(_loaded().entries) == {PurePosixPath('pages/kept_html_jinja.py')}


def test_a_renamed_template_leaves_no_stub_behind(project):
    """A rename is a delete plus an add, and the phantom errors come from the delete half."""
    before = _write(project, 'pages/before.html.jinja', _BAD)
    _run([before])

    (project / before).rename(project / 'pages/after.html.jinja')
    _run([Path('pages/after.html.jinja')])

    assert not (project / '_jinja_stubs/pages/before_html_jinja.py').is_file()
    assert (project / '_jinja_stubs/pages/after_html_jinja.py').is_file()


def test_a_template_that_loses_its_header_loses_its_stub(project):
    """The template still exists, so only the run's own verdict can retire the stub."""
    template = _write(project, 'pages/one.html.jinja', _OK)
    _run([template])

    _write(project, 'pages/one.html.jinja', _HEADERLESS)
    _run([template])

    assert not (project / '_jinja_stubs/pages/one_html_jinja.py').is_file()
    assert _loaded().entries == {}


def test_generating_one_template_keeps_the_rest_of_the_tree(project):
    """Checking a single file in an editor or a pre-commit hook must not prune the others."""
    one = _write(project, 'pages/one.html.jinja', _OK)
    two = _write(project, 'pages/two.html.jinja', _OK)
    _run([one, two])

    _run([one])

    assert (project / '_jinja_stubs/pages/two_html_jinja.py').is_file()
    assert set(_loaded().entries) == {
        PurePosixPath('pages/one_html_jinja.py'),
        PurePosixPath('pages/two_html_jinja.py'),
    }


def test_the_last_stub_in_a_directory_takes_its_package_marker(project):
    template = _write(project, 'deep/nested/one.html.jinja', _OK)
    _run([template])
    marker = project / '_jinja_stubs/deep/nested/__init__.py'
    assert marker.is_file()

    (project / template).unlink()
    _run([])

    assert not marker.is_file()
    assert not (project / '_jinja_stubs/deep').exists()


def test_check_reports_a_tree_that_still_holds_a_deleted_templates_stub(project):
    kept = _write(project, 'pages/kept.html.jinja', _OK)
    doomed = _write(project, 'pages/doomed.html.jinja', _OK)
    _run([kept, doomed])

    (project / doomed).unlink()
    outdated = stale(generate([kept], Path('_jinja_stubs')))

    assert Path('_jinja_stubs/pages/doomed_html_jinja.py') in outdated


def test_check_is_quiet_on_a_current_tree(project):
    template = _write(project, 'pages/one.html.jinja', _OK)
    _run([template])

    assert stale(generate([template], Path('_jinja_stubs'))) == []


def test_a_second_write_changes_nothing(project):
    """The manifest is part of the write set, so an unstable rendering would churn forever."""
    template = _write(project, 'pages/one.html.jinja', _OK)
    _run([template])

    assert _run([template]) == []


def test_a_corrupt_manifest_is_rebuilt_rather_than_fatal(project):
    template = _write(project, 'pages/one.html.jinja', _OK)
    _run([template])
    (project / '_jinja_stubs' / manifest.MANIFEST_NAME).write_text('not json', encoding='utf-8')

    _run([template])

    assert _loaded().template_for(PurePosixPath('pages/one_html_jinja.py')) == template


def test_a_manifest_from_a_future_version_is_ignored(project):
    """Reading an unknown layout as if it were this one would delete files it does not describe."""
    template = _write(project, 'pages/one.html.jinja', _OK)
    _run([template])
    path = project / '_jinja_stubs' / manifest.MANIFEST_NAME
    payload = json.loads(path.read_text(encoding='utf-8'))
    path.write_text(json.dumps({**payload, 'version': payload['version'] + 99}), encoding='utf-8')

    _run([template])

    assert (project / '_jinja_stubs/pages/one_html_jinja.py').is_file()


def test_the_manifest_accounts_for_every_file_the_run_writes(project):
    """A file the manifest does not own can never be cleaned up."""
    templates = [
        _write(project, 'pages/one.html.jinja', _OK),
        _write(project, 'deep/nested/two.html.jinja', _OK),
    ]
    _run(templates)
    files, _ = plan(generate(templates, Path('_jinja_stubs')))

    accounted = {manifest.relative(path, Path('_jinja_stubs')) for path in files} - {
        PurePosixPath(manifest.MANIFEST_NAME)
    }

    assert accounted == _loaded().files
