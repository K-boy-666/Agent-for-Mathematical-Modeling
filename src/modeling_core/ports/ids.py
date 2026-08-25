"""ID source kept explicit to make workflows deterministic under test."""

from typing import Protocol


class IdGenerator(Protocol):
    def new_uuid4(self) -> str: ...
