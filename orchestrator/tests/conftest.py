"""Default pytest runs skip live speech markers.

``e2e_latency`` and ``accent`` stay out of ``pytest`` / CI unless the command
selects them (``pytest -m e2e_latency`` or ``pytest -m accent``).
"""

from __future__ import annotations

import pytest

_LIVE = ("e2e_latency", "accent")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e_latency: spoken-turn latency against orchestrator and speech services",
    )
    config.addinivalue_line(
        "markers",
        "accent: beginner-phrase ASR fixtures; skipped unless ASR_URL answers /health",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    markexpr = config.getoption("-m") or ""
    keyword = config.getoption("-k") or ""
    explicit_node = any("::" in arg for arg in config.args)
    if explicit_node or keyword or any(name in markexpr for name in _LIVE):
        return
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if any(item.get_closest_marker(name) for name in _LIVE):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
