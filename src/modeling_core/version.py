"""Application and milestone versions."""

from enum import StrEnum

APPLICATION_VERSION = "0.1.0"


class Milestone(StrEnum):
    """Verification milestones understood by the application."""

    M1A = "m1a"
    M1B = "m1b"
