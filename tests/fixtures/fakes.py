from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Iterator

from modeling_core.ports.clock import Clock
from modeling_core.ports.ids import IdGenerator


class FakeClock(Clock):
    def __init__(self, start: datetime, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def utc_now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("FakeClock cannot move backwards")
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds


class FixedIdGenerator(IdGenerator):
    def __init__(self, values: Iterable[str]) -> None:
        self._values: Iterator[str] = iter(values)

    def new_uuid4(self) -> str:
        try:
            return next(self._values)
        except StopIteration as error:
            raise RuntimeError("FixedIdGenerator exhausted") from error
