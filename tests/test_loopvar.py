"""The Jinja ``loop`` variable is defined inside a ``{% for %}`` body."""

from . import checked
from .checked import reported, write_template
from .configuration import requires_checker

pytestmark = requires_checker(checked.DEFAULT_BACKEND)

_TEMPLATE = """{#def
items: list[str]
#}
{% for item in items %}{{ loop.index }}: {{ item }}{% endfor %}
"""


def test_loop_variable_is_defined(project):
    template = write_template('templates/loop.html.jinja', _TEMPLATE)

    assert reported(template) == []
