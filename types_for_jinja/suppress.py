"""Drop diagnostics on template lines marked with an inline ignore comment.

Supported forms, matched on the same source line as the flagged expression:

- ``{# type: ignore #}`` suppresses every diagnostic on that line
- ``{# type: ignore[TJ002] #}`` suppresses only the listed codes (comma-separated)

The whitespace-control forms ``{#- ... -#}`` are handled too.

``types-for-jinja check`` owns its diagnostics, so it honours the codes exactly. A
generated stub cannot: it is read by whichever checker the project runs, each of which
spells the same rule differently and reports the comment as an error when the name is one
it does not know. So ``annotate`` emits a blanket ignore for the whole line in every
style. ``STYLES`` maps a project's checker to the spelling it honours, and the portable
default suits a project running more than one.
"""

from __future__ import annotations

import re

from types_for_jinja.diagnostic import Diagnostic

_IGNORE_RE = re.compile(r'\{#-?\s*type:\s*ignore(?:\[(?P<codes>[^\]]*)\])?\s*-?#\}')
_MARKER_RE = re.compile(r'#\s*L(\d+)\s*$')

STYLES: dict[str, str] = {
    'mypy': '# type: ignore',
    'portable': '# type: ignore',
    'pyright': '# pyright: ignore',
    'ty': '# ty: ignore',
}


def apply_suppressions(source: str, diags: list[Diagnostic]) -> list[Diagnostic]:
    """Remove diagnostics suppressed by an inline ignore comment on the same line."""
    ignores = _collect_ignores(source)
    if not ignores:
        return diags
    return [diag for diag in diags if not _suppressed(diag, ignores)]


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


def _collect_ignores(source: str) -> dict[int, frozenset[str] | None]:
    ignores: dict[int, frozenset[str] | None] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        match = _IGNORE_RE.search(line)
        if match is None:
            continue
        spec = match.group('codes')
        ignores[lineno] = None if spec is None else frozenset(c.strip() for c in spec.split(',') if c.strip())
    return ignores


def _suppressed(diag: Diagnostic, ignores: dict[int, frozenset[str] | None]) -> bool:
    if diag.line not in ignores:
        return False
    codes = ignores[diag.line]
    return codes is None or diag.code in codes
