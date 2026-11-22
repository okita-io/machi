import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from comfyui_bake import main  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []
        self.history_hits = 0
        self.upload_name = "ref_uploaded.png"

    def __call__(self, method: str, url: str, data: bytes | None, headers: dict[str, str]):
        self.calls.append((method, url, data))
        if url.endswith("/upload/image"):
            return 200, json.dumps({"name": self.upload_name}).encode()
        if url.endswith("/prompt"):
            return 200, json.dumps({"prompt_id": "job-1"}).encode()
        if url.endswith("/history/job-1"):
            self.history_hits += 1
            if self.history_hits < 2:
                return 200, b"{}"
            body = {
                "job-1": {
                    "outputs": {
                        "10": {
                            "images": [
                                {"filename": "machi_00001_.png", "subfolder": "", "type": "output"}
                            ]
                        }
                    }
                }
            }
            return 200, json.dumps(body).encode()
        if "/view?" in url and "machi_00001_.png" in url:
            return 200, PNG
        raise AssertionError(url)


def test_dry_run_prints_workflow_without_network(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("COMFY_BAKE_GO", raising=False)
    http = FakeHttp()
    code = main(
        [
            "--prompt",
            "ramen shop at dusk",
            "--w",
            "768",
            "--h",
            "512",
            "--steps",
            "8",
            "--seed",
            "3",
            "--dry-run",
        ],
        http=http,
    )
    assert code == 0
    assert http.calls == []
    printed = json.loads(capsys.readouterr().out)
    unet = next(node for node in printed.values() if node["class_type"] == "UNETLoader")
    sampler = next(node for node in printed.values() if node["class_type"] == "KSampler")
    assert unet["inputs"]["weight_dtype"] == "fp8_e4m3fn"
    assert "qwen_image_edit_2511_bf16" in unet["inputs"]["unet_name"]
    clip = next(node for node in printed.values() if node["class_type"] == "CLIPLoader")
    assert clip["inputs"]["type"] == "qwen_image"
    assert "qwen_2.5_vl_7b_fp8_scaled" in clip["inputs"]["clip_name"]
    vae = next(node for node in printed.values() if node["class_type"] == "VAELoader")
    assert "qwen_image_vae" in vae["inputs"]["vae_name"]
    assert sampler["inputs"]["cfg"] == 4.0
    assert sampler["inputs"]["sampler_name"] == "euler"
    assert sampler["inputs"]["scheduler"] == "simple"
    assert sampler["inputs"]["steps"] == 8
    assert sampler["inputs"]["seed"] == 3
    latent = next(node for node in printed.values() if node["class_type"] == "EmptySD3LatentImage")
    assert latent["inputs"]["width"] == 768
    assert latent["inputs"]["height"] == 512
    assert any(
        node.get("inputs", {}).get("prompt") == "ramen shop at dusk" for node in printed.values()
    )
    assert not (tmp_path / "bake.webp").exists()


def test_refuses_without_guard(monkeypatch, capsys):
    monkeypatch.delenv("COMFY_BAKE_GO", raising=False)
    http = FakeHttp()
    code = main(["--prompt", "counter"], http=http)
    assert code == 2
    assert http.calls == []
    err = capsys.readouterr().err
    assert "COMFY_BAKE_GO=1" in err
    assert "restart" in err.lower()


def test_submits_polls_downloads_and_converts(monkeypatch, tmp_path):
    monkeypatch.setenv("COMFY_BAKE_GO", "1")
    http = FakeHttp()
    pauses: list[float] = []
    converted: list[tuple[bytes, Path]] = []

    def convert(data: bytes, dest: Path) -> None:
        converted.append((data, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"RIFF")

    out = tmp_path / "assets" / "bg" / "ramen.webp"
    code = main(
        ["--prompt", "warm ramen counter", "--server", "http://comfy.test:8188", "--out", str(out)],
        http=http,
        pause=pauses.append,
        convert=convert,
    )
    assert code == 0
    assert pauses == [1.0]
    assert http.history_hits == 2
    prompt_call = next(call for call in http.calls if call[1].endswith("/prompt"))
    payload = json.loads(prompt_call[2])
    workflow = payload["prompt"]
    assert workflow["1"]["inputs"]["weight_dtype"] == "fp8_e4m3fn"
    assert workflow["8"]["inputs"]["cfg"] == 4.0
    assert workflow["8"]["inputs"]["sampler_name"] == "euler"
    assert workflow["8"]["inputs"]["scheduler"] == "simple"
    assert workflow["5"]["inputs"]["prompt"] == "warm ramen counter"
    view = next(call for call in http.calls if "/view?" in call[1])
    assert "filename=machi_00001_.png" in view[1]
    assert converted == [(PNG, out)]
    assert out.read_bytes() == b"RIFF"


def test_edit_upload_name_lands_in_the_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("COMFY_BAKE_GO", "1")
    http = FakeHttp()
    ref = tmp_path / "plate.png"
    ref.write_bytes(PNG)

    def convert(data: bytes, dest: Path) -> None:
        dest.write_bytes(b"RIFF")

    code = main(
        ["--prompt", "keep the counter", "--ref", str(ref), "--out", str(tmp_path / "out.webp")],
        http=http,
        pause=lambda _seconds: None,
        convert=convert,
    )
    assert code == 0
    assert any(call[1].endswith("/upload/image") for call in http.calls)
    payload = json.loads(next(call[2] for call in http.calls if call[1].endswith("/prompt")))
    loaders = [node for node in payload["prompt"].values() if node["class_type"] == "LoadImage"]
    assert loaders[0]["inputs"]["image"] == "ref_uploaded.png"


def test_webp_conversion_writes_a_file(tmp_path):
    pytest.importorskip("PIL")
    from comfyui_bake import convert_to_webp

    dest = tmp_path / "nested" / "plate.webp"
    convert_to_webp(PNG, dest)
    assert dest.read_bytes()[:4] == b"RIFF"
