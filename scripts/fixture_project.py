"""Write the shared fixture project into a directory, for the editor smoke tests.

The same layout ``tests/backends.py`` builds, so a template that fails in the test suite
fails the same way in a real editor.
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_REPO), str(_REPO / 'tests')]

import backends  # noqa: E402


def main(root: Path) -> None:
    """Lay out the fixture plus the extras the editor phases need."""
    backends.write_project(root)
    (root / 'templates/bare.html.jinja').write_text('<p>{{ whatever }}</p>\n', encoding='utf-8')
    (root / 'pyproject.toml').write_text('[project]\nname = "fixture"\nversion = "0"\n', encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
