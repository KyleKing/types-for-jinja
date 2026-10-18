from textwrap import dedent

from jinja2 import Environment

from types_for_jinja.transpile import macro_defs


def test_typed_macro_with_comparison():
    source = dedent(
        """{% macro show(value) %}
            {#def
            value: int
            #}
            {% if value == 1 %}yes{% endif %}
        {% endmacro %}
        """
    )
    tree = Environment(autoescape=True).parse(source)
    types, imports = macro_defs(source, tree)

    assert list(types.values()) == [{'value': 'int'}]
    assert imports == []
