"""Tests for ``types-for-jinja wrapper``: writing, drift detection, and flag precedence."""

import argparse
from pathlib import Path

from types_for_jinja.cli import _wrapper_config, main
from types_for_jinja.config import Config, WrapperConfig

_TEMPLATES = 'examples/runtime/templates'
_ENV = 'from examples.runtime.env import env as _env'


def _run(out_dir, *extra):
    return main(['wrapper', _TEMPLATES, '-o', str(out_dir), '--env-import', _ENV, *extra])


def test_wrapper_writes_a_typed_render_function(tmp_path):
    assert _run(tmp_path) == 0

    generated = (tmp_path / 'examples/runtime/templates/profile_html_jinja.py').read_text(encoding='utf-8')
    assert 'def render_profile(*, profile: Profile) -> Markup:' in generated
    assert _ENV in generated


def test_check_passes_when_the_wrapper_is_current(tmp_path):
    _run(tmp_path)

    assert _run(tmp_path, '--check') == 0


def test_check_fails_once_the_wrapper_drifts(tmp_path):
    _run(tmp_path)
    generated = tmp_path / 'examples/runtime/templates/profile_html_jinja.py'
    generated.write_text('# stale\n', encoding='utf-8')

    assert _run(tmp_path, '--check') == 1


def test_check_fails_when_the_wrapper_was_never_written(tmp_path):
    assert _run(tmp_path, '--check') == 1
    assert not (tmp_path / 'examples').exists()


def test_validator_flag_reaches_the_generated_module(tmp_path):
    _run(tmp_path, '--validator', 'pydantic')

    generated = (tmp_path / 'examples/runtime/templates/profile_html_jinja.py').read_text(encoding='utf-8')
    assert 'TypeAdapter(Profile)' in generated


def test_flags_win_over_the_project_config():
    config = Config(wrapper=WrapperConfig(validator='beartype', return_type='Markup'))
    args = argparse.Namespace(
        env_import=None,
        return_import=None,
        return_type='HTMLResponse',
        validator=None,
    )

    merged = _wrapper_config(args, config).wrapper

    assert merged.return_type == 'HTMLResponse'
    assert merged.validator == 'beartype'


def test_out_dir_defaults_to_the_configured_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template = tmp_path / 'page.html.jinja'
    template.write_text('{#def\nname: str\n#}\n<p>{{ name }}</p>\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja.wrapper]\nout_dir = "generated"\n',
        encoding='utf-8',
    )

    assert main(['wrapper', 'page.html.jinja']) == 0
    assert (tmp_path / 'generated' / Path('page_html_jinja.py')).is_file()


def test_a_deleted_template_takes_its_wrapper_with_it(tmp_path, monkeypatch):
    """A wrapper left behind stays importable, so callers keep rendering a template that is gone."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja.wrapper]\nout_dir = "generated"\n',
        encoding='utf-8',
    )
    for name in ('kept', 'dropped'):
        (tmp_path / f'{name}.html.jinja').write_text('{#def\nname: str\n#}\n<p>{{ name }}</p>\n', encoding='utf-8')

    assert main(['wrapper', 'kept.html.jinja', 'dropped.html.jinja']) == 0
    dropped_wrapper = tmp_path / 'generated' / 'dropped_html_jinja.py'
    assert dropped_wrapper.is_file()

    (tmp_path / 'dropped.html.jinja').unlink()

    assert main(['wrapper', 'kept.html.jinja']) == 0
    assert not dropped_wrapper.exists()
    assert (tmp_path / 'generated' / 'kept_html_jinja.py').is_file()


def test_check_reports_a_wrapper_whose_template_is_gone(tmp_path, monkeypatch):
    """Every wrapper on disk is current here; the only fault is one the tree should no longer hold."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.types_for_jinja.wrapper]\nout_dir = "generated"\n',
        encoding='utf-8',
    )
    for name in ('kept', 'dropped'):
        (tmp_path / f'{name}.html.jinja').write_text('{#def\nname: str\n#}\n<p>{{ name }}</p>\n', encoding='utf-8')
    assert main(['wrapper', 'kept.html.jinja', 'dropped.html.jinja']) == 0
    assert main(['wrapper', 'kept.html.jinja', 'dropped.html.jinja', '--check']) == 0

    (tmp_path / 'dropped.html.jinja').unlink()

    assert main(['wrapper', 'kept.html.jinja', '--check']) == 1
