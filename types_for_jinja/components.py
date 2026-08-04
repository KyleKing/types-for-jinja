"""Check JinjaX component tags against the component's own ``{#def #}`` header.

``<Card title={{ user.name }} />`` is JinjaX preprocessor syntax. Jinja's parser reads it as
literal text plus output nodes, so the embedded expression is checked by the ordinary walk and
the component boundary is not. This module closes that half by emitting the use as a call
against a signature built from the component template's own header.

The signature ends in ``**attrs``, which is the important detail. JinjaX pops the declared
parameters and hands everything left over to the component as ``attrs``, so an undeclared
attribute is not an error, it is an HTML attribute. A strict call would report an error on
every component use that passes ``class`` or ``id``, which is most of them. What the call does
catch is a missing required attribute and a declared attribute given the wrong type.

Resolution follows what JinjaX does, and stops where JinjaX needs its own configuration.
A tag with a registry prefix (``<ui:Button>``) is skipped, because the prefix maps to a search
path that lives in the catalog rather than in the template. An unresolvable tag is skipped too:
the checker says nothing rather than guessing.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from pathlib import Path

from types_for_jinja.header import Param, TemplateHeader, parse_header
from types_for_jinja.resolve import resolve_template

_RAW = re.compile(r'\{%-?\s*raw\s*-?%\}.+?\{%-?\s*endraw\s*-?%\}', re.DOTALL)
_TAG = re.compile(r'<(?P<tag>(?:[0-9A-Za-z._-]+:)?(?:[0-9A-Za-z_-]+\.)*[A-Z][0-9A-Za-z_-]*)(?=[\s\n/>])')
_ATTR = re.compile(
    r"""
    (?P<name>[a-zA-Z@:$_][a-zA-Z@:$_0-9\-.]*)
    (?:\s*=\s*(?P<value>".*?"|'.*?'|\{\{.*?\}\}))?
    (?:\s+|/|"|$)
    """,
    re.VERBOSE | re.DOTALL,
)
_CALLABLE_PREFIX = 'tj_component_'
"""No leading underscore: the signatures reach the stub through ``import *``, which skips
private names, and the sidecar they live in has no ``__all__`` to override that."""

_DEFAULT_EXTENSION = '.jinja'


@dataclass(frozen=True)
class Attribute:
    """One component attribute, as the Python expression its value amounts to."""

    name: str
    expression: str


@dataclass(frozen=True)
class Use:
    """One component tag in a template, and where it sits."""

    tag: str
    lineno: int
    attributes: list[Attribute]

    @property
    def callable_name(self) -> str:
        """The generated function this use calls."""
        return _CALLABLE_PREFIX + ''.join(char if char.isalnum() else '_' for char in self.tag)

    @property
    def call(self) -> str:
        """The call expression to emit at the tag's own template line."""
        arguments = ', '.join(f'{attr.name}={attr.expression}' for attr in self.attributes)
        return f'{self.callable_name}({arguments})'


def find_uses(source: str) -> list[Use]:
    """Every resolvable-looking component tag in ``source``, in source order.

    ``{% raw %}`` blocks are blanked first, the way JinjaX blanks them, so a tag shown as
    example markup is not read as a use.
    """
    scanned = _RAW.sub(lambda match: ' ' * len(match.group(0)), source)
    uses: list[Use] = []
    for match in _TAG.finditer(scanned):
        tag = match.group('tag')
        if ':' in tag:
            continue
        attributes, end = _opening_tag(scanned, match.end())
        if end == -1:
            continue
        uses.append(
            Use(tag=tag, lineno=scanned.count('\n', 0, match.start()) + 1, attributes=_attributes(attributes)),
        )
    return uses


def _opening_tag(source: str, start: int) -> tuple[str, int]:
    """Find where the opening tag ends, ignoring ``>`` inside quotes or inside ``{{ }}``.

    Mirrors JinjaX's own scanner, because an attribute value may legitimately contain the
    character that would otherwise close the tag.
    """
    quote = ''
    braced = False
    index = start
    while index < len(source):
        char, pair = source[index], source[index : index + 2]
        if not quote:
            if pair == '{{' and not braced:
                braced = True
                index += 2
                continue
            if pair == '}}' and braced:
                braced = False
                index += 2
                continue
            if pair in {'{{', '}}'}:
                return '', -1
        if quote and pair in {'\\"', "\\'"}:
            index += 2
            continue
        if char in {'"', "'"} and quote in {'', char}:
            quote = '' if quote else char
            index += 1
            continue
        if char == '>' and not quote and not braced:
            return source[start:index].strip().removesuffix('/'), index + 1
        index += 1
    return '', -1


def _attributes(text: str) -> list[Attribute]:
    """Turn an opening tag's attribute text into name and Python expression pairs.

    An attribute named after a Python keyword (``class``) is dropped. JinjaX carries it as a
    string key in a dict, so it always lands in ``attrs`` and could never have been a declared
    parameter, since ``{#def class: str #}`` does not parse either.
    """
    collapsed = text.replace('\n', ' ').strip()
    found: list[Attribute] = []
    for name, value in _ATTR.findall(collapsed):
        expression = _expression(name.strip(), value.strip())
        identifier = name.strip().lstrip(':').replace('-', '_')
        if expression is not None and identifier.isidentifier() and not keyword.iskeyword(identifier):
            found.append(Attribute(name=identifier, expression=expression))
    return found


def _expression(name: str, value: str) -> str | None:
    """The Python expression an attribute value amounts to, or ``None`` to leave it unchecked.

    Three forms, all from JinjaX. A bare attribute is ``True``. ``{{ ... }}`` is the expression
    itself. A quoted value is a string literal, unless the name carries the vue-like ``:``
    prefix, in which case the quotes hold an expression.
    """
    if not value:
        return 'True'
    if value.startswith('{{') and value.endswith('}}'):
        inner = value[2:-2].strip()
        return inner or None
    if name.startswith(':') and value[:1] in {'"', "'"}:
        return value[1:-1].strip() or None
    return value if value[:1] in {'"', "'"} else None


def resolve_component(tag: str, search_dirs: list[Path], extension: str = _DEFAULT_EXTENSION) -> TemplateHeader | None:
    """Read a component's declared context, or ``None`` when the component cannot be found.

    Tries what JinjaX tries: the dotted name as a path, its kebab-case form, and an ``index``
    file inside a directory of that name.
    """
    stem = tag.replace('.', '/')
    for candidate in (f'{stem}{extension}', f'{_kebab(stem)}{extension}', f'{stem}/index{extension}'):
        found = resolve_template(candidate, search_dirs)
        if found is not None:
            return parse_header(found[1])
    return None


def _kebab(name: str) -> str:
    """``AlertDanger`` to ``alert-danger``, which JinjaX accepts as a filename."""
    spaced = re.sub(r'(?<=[^A-Z_/-])(?=[A-Z])', '-', name)
    return spaced.replace('_', '-').lower()


def signature(use: Use, header: TemplateHeader, any_type: str) -> str:
    """The ``def`` a use is checked against, built from the component's own header.

    Keyword-only, so declaration order does not constrain which parameters may default, and
    ending in ``**attrs`` because JinjaX forwards undeclared attributes rather than rejecting
    them.
    """
    declared = ', '.join(_parameter(param, any_type) for param in header.params)
    parameters = f'*, {declared}, **attrs: {any_type}' if declared else f'**attrs: {any_type}'
    return f'def {use.callable_name}({parameters}) -> None: ...'


def _parameter(param: Param, any_type: str) -> str:
    declared = param.annotated(any_type)
    return declared if param.default is None else f'{declared} = {param.default}'
