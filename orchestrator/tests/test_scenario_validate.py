from pathlib import Path

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
RESTAURANT = SCENARIOS / "restaurant_ramen_01.yaml"

settings.scenarios_path = str(SCENARIOS)
settings.db_path = str(ROOT / "data" / "test_machi.sqlite")


def test_validate_accepts_restaurant_yaml():
    text = RESTAURANT.read_text(encoding="utf-8")
    before = {path.name: path.stat().st_mtime_ns for path in SCENARIOS.glob("*.yaml")}
    with TestClient(app) as client:
        response = client.post("/scenarios/validate", json={"yaml": text})
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["id"] == "restaurant_ramen_01"
        assert body["errors"] == []

        raw = client.get("/scenarios/restaurant_ramen_01/raw")
        assert raw.status_code == 200
        assert raw.json()["yaml"] == text
        assert client.get("/scenarios/missing_scenario/raw").status_code == 404
    after = {path.name: path.stat().st_mtime_ns for path in SCENARIOS.glob("*.yaml")}
    assert after == before


def test_validate_rejects_unknown_fields_and_missing_edges():
    text = RESTAURANT.read_text(encoding="utf-8")
    with TestClient(app) as client:
        unknown = client.post("/scenarios/validate", json={"yaml": "bonus: true\n" + text})
        assert unknown.status_code == 422
        unknown_body = unknown.json()
        assert unknown_body["ok"] is False
        assert any(
            err["path"] == "bonus" and "extra" in err["message"].lower() and err["line"] == 1
            for err in unknown_body["errors"]
        )

        broken = text.replace("on_success: seat", "on_success: missing_node", 1)
        missing = client.post("/scenarios/validate", json={"yaml": broken})
        assert missing.status_code == 422
        missing_body = missing.json()
        assert missing_body["ok"] is False
        edge = next(err for err in missing_body["errors"] if "missing_node" in err["message"])
        assert edge["path"] == "flow.nodes.greet.on_success"
        assert isinstance(edge["line"], int) and edge["line"] > 1

        no_edge = broken.replace("      on_success: missing_node\n", "", 1)
        dropped = client.post("/scenarios/validate", json={"yaml": no_edge})
        assert dropped.status_code == 422
        assert any("outgoing edge" in err["message"] for err in dropped.json()["errors"])
