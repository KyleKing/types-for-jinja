"""Carry a template's inline ignore comments into the generated stub.

Supported forms, matched on the same source line as the expression to silence:

- ``{# type: ignore #}``
- ``{# type: ignore[some-code] #}``

The whitespace-control forms ``{#- ... -#}`` are handled too.

A bracketed code is read but not carried across, and the emitted comment is always a
blanket ignore for the whole generated line. The stub is read by whichever checker the
project runs, each spells the same rule differently, and a name one of them does not know
is itself reported as an error. ``STYLES`` maps a project's checker to the spelling it
honours, and the portable default suits a project running more than one.
"""

from __future__ import annotations

import re

_IGNORE_RE = re.compile(r'\{#-?\s*type:\s*ignore(?:\[(?P<codes>[^\]]*)\])?\s*-?#\}')
_MARKER_RE = re.compile(r'#\s*L(\d+)\s*$')

STYLES: dict[str, str] = {
    'mypy': '# type: ignore',
    'portable': '# type: ignore',
    'pyright': '# pyright: ignore',
    'ty': '# ty: ignore',
}


def annotate(code: str, source: str, style: str, *, aligned: bool) -> str:
    """Carry ``source``'s inline ignores into generated ``code`` as native ignore comments.

    An aligned stub maps generated line N to template line N. An unaligned one carries a
    trailing ``# L<n>`` marker instead, and the ignore goes in front of that marker so the
    checker sees it as the comment's own directive and the marker stays at end of line.
    """
    ignored = ignored_lines(source)
    comment = STYLES[style]
    if not ignored:
        return code
    annotated = [
        _annotate_line(text, index + 1 if aligned else _marked_line(text), ignored, comment)
        for index, text in enumerate(code.splitlines())
    ]
    return '\n'.join(annotated) + '\n'


def ignored_lines(source: str) -> set[int]:
    """Template lines carrying an inline ignore comment, whatever codes it names."""
    return set(_collect_ignores(source))


def _annotate_line(text: str, lineno: int | None, ignored: set[int], comment: str) -> str:
    if lineno not in ignored or not text.strip():
        return text
    marker = _MARKER_RE.search(text)
    if marker is None:
        return f'{text}  {comment}'
    return f'{text[: marker.start()].rstrip()}  {comment}  {text[marker.start() :]}'


def _marked_line(text: str) -> int | None:
    match = _MARKER_RE.search(text)
    return int(match.group(1)) if match else None


def _collect_ignores(source: str) -> set[int]:
    return {lineno for lineno, line in enumerate(source.splitlines(), start=1) if _IGNORE_RE.search(line)}
