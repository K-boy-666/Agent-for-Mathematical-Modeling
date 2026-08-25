"""Time source used by deadline-aware application services."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def utc_now(self) -> datetime: ...

    def monotonic(self) -> float: ...
