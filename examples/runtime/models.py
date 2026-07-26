"""Context types for the runtime example, one dataclass and one Pydantic model."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class Profile:
    """A plain dataclass context, validated at runtime by beartype or a TypeAdapter."""

    name: str
    email: str
    age: int


class ProfileModel(BaseModel):
    """A Pydantic context, statically checked identically to the dataclass."""

    name: str
    email: str
    age: int
