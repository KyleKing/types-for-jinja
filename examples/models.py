"""Context types used by the example templates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    """A single list entry rendered by the example templates."""

    title: str
    done: bool


@dataclass(frozen=True)
class User:
    """The current user passed into the example templates."""

    name: str
    is_admin: bool
    items: list[Item]
