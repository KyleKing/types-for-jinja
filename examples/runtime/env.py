"""The Jinja Environment the generated wrappers render through."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES = Path(__file__).parent / 'templates'

env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True)
