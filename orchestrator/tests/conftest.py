"""Default pytest runs skip live speech markers.

``e2e_latency`` and ``accent`` stay out of ``pytest`` / CI unless the command
selects them (``pytest -m e2e_latency`` or ``pytest -m accent``).
"""

from __future__ import annotations

import pytest

from machi.config import settings

_LIVE = ("e2e_latency", "accent")


@pytest.fixture(autouse=True)
def _isolate_baked_audio():
    """Keep committed assets/audio off the turn path unless a test opts in."""
    previous = settings.assets_path
    settings.assets_path = "/assets-not-mounted"
    yield
    settings.assets_path = previous


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e_latency: spoken-turn latency against orchestrator and speech services",
    )
    config.addinivalue_line(
        "markers",
        "accent: beginner-phrase ASR fixtures; skipped unless ASR_URL answers /health",
    )
    config.addinivalue_line(
        "markers",
        "pron_model: OpenJTalk dictionary and librosa.pyin; skip if the dictionary is missing",
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
