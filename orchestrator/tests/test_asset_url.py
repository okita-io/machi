from machi.config import settings
from machi.main import _asset_url


def test_asset_url_relative():
    settings.assets_base_url = "/assets"
    assert _asset_url("bg/ramen.webp") == "/assets/bg/ramen.webp"


def test_asset_url_absolute():
    settings.assets_base_url = "http://cdn.example:8080"
    assert _asset_url("/sprites/sora/neutral.webp") == (
        "http://cdn.example:8080/sprites/sora/neutral.webp"
    )