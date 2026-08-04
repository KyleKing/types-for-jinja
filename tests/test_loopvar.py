"""The Jinja ``loop`` variable is defined inside a ``{% for %}`` body."""

from pathlib import Path

from types_for_jinja.check import check_source

from .configuration import requires_pyright

pytestmark = requires_pyright

_TEMPLATE = """{#def
items: list[str]
#}
{% for item in items %}{{ loop.index }}: {{ item }}{% endfor %}
"""


def test_loop_variable_is_defined(tmp_path):
    diags = check_source(_TEMPLATE, Path('loop.html'), cache_dir=tmp_path)

    assert diags == []
