"""Parse the ``{#def ... #}`` type header from a Jinja template."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADER_RE = re.compile(r'\{#-?\s*def\b(?P<body>.*?)-?#\}', re.DOTALL)


@dataclass(frozen=True)
class TemplateHeader:
    """The typed context a template declares via its ``{#def ... #}`` comment."""

    imports: list[str]
    params: list[tuple[str, str]]
    lineno: int


def parse_header(source: str) -> TemplateHeader | None:
    """Return the first ``{#def ... #}`` header in ``source``, or ``None`` if absent."""
    match = _HEADER_RE.search(source)
    if match is None:
        return None
    lineno = source.count('\n', 0, match.start()) + 1
    imports: list[str] = []
    params: list[tuple[str, str]] = []
    for raw in match.group('body').splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(('import ', 'from ')):
            imports.append(line)
        elif ':' in line:
            name, type_str = line.split(':', 1)
            params.append((name.strip(), type_str.strip()))
    return TemplateHeader(imports=imports, params=params, lineno=lineno)
