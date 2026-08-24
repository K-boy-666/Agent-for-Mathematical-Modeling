"""Shared pytest configuration for the formal test suite."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if os.name == "nt":
        return

    deselected = [
        item
        for item in items
        if item.get_closest_marker("windows_only") is not None
        and item.get_closest_marker("cross_platform") is None
    ]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = [item for item in items if item not in deselected]
