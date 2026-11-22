#!/usr/bin/env python3
"""Offline ComfyUI bake for Machi scene art.

NEVER part of ``docker compose up``. This file is a manual one-shot. It only
queues a prompt on a ComfyUI server that is already running.

House rule: do not restart ComfyUI, and do not call its manager or ``/free``.
April shares that process. ``weight_dtype`` stays ``fp8_e4m3fn`` — bf16
OOM-kills the server, and ``fp8_e4m3fn_fast`` comes back as noise.

A real run refuses to start unless ``COMFY_BAKE_GO=1``. ``--dry-run`` prints
the workflow and does not open a socket.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = Path(__file__).resolve().parent / "workflows"
T2I_TEMPLATE = WORKFLOWS / "qwen_image_2511_t2i.json"
EDIT_TEMPLATE = WORKFLOWS / "qwen_image_2511_edit.json"
DEFAULT_SERVER = "http://100.69.65.33:8188"

Http = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]
Pause = Callable[[float], None]
Convert = Callable[[bytes, Path], None]


class BakeError(RuntimeError):
    pass


def convert_to_webp(data: bytes, dest: Path) -> None:
    """Write ``data`` (PNG or JPEG bytes) to a WebP file. Imports Pillow here."""
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError as exc:
        raise BakeError(
            "WebP conversion needs Pillow (pip install pillow). Not a compose dependency."
        ) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(data)) as image:
        image.save(dest, format="WEBP")


def urllib_request(method: str, url: str, data: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _replace(node: Any, prompt: str, ref: str) -> Any:
    if isinstance(node, dict):
        return {key: _replace(value, prompt, ref) for key, value in node.items()}
    if isinstance(node, list):
        return [_replace(value, prompt, ref) for value in node]
    if isinstance(node, str):
        return node.replace("{{PROMPT}}", prompt).replace("{{REF}}", ref)
    return node


def build_workflow(
    prompt: str,
    *,
    width: int,
    height: int,
    steps: int,
    seed: int,
    ref_name: str | None,
) -> dict[str, Any]:
    template = EDIT_TEMPLATE if ref_name else T2I_TEMPLATE
    workflow = json.loads(template.read_text(encoding="utf-8"))
    workflow = _replace(workflow, prompt, ref_name or "")
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        kind = node.get("class_type")
        if kind == "EmptySD3LatentImage":
            inputs["width"] = width
            inputs["height"] = height
        elif kind == "KSampler":
            inputs["steps"] = steps
            inputs["seed"] = seed
            inputs["cfg"] = 4.0
            inputs["sampler_name"] = "euler"
            inputs["scheduler"] = "simple"
        elif kind == "UNETLoader":
            inputs["weight_dtype"] = "fp8_e4m3fn"
    return workflow


def _url(server: str, path: str) -> str:
    return server.rstrip("/") + path


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BakeError(f"ComfyUI returned non-JSON: {raw[:200]!r}") from exc


def upload_image(http: Http, server: str, path: Path) -> str:
    content = path.read_bytes()
    boundary = f"----machi-bake-{uuid.uuid4().hex}"
    filename = path.name.replace('"', "")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = head + content + f"\r\n--{boundary}--\r\n".encode()
    status, raw = http(
        "POST",
        _url(server, "/upload/image"),
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    if status != 200:
        raise BakeError(f"upload failed ({status}): {raw[:200]!r}")
    name = _decode(raw).get("name")
    if not name:
        raise BakeError("upload response missing name")
    return str(name)


def submit_prompt(http: Http, server: str, workflow: dict[str, Any]) -> str:
    payload = json.dumps({"prompt": workflow, "client_id": uuid.uuid4().hex}).encode()
    status, raw = http(
        "POST",
        _url(server, "/prompt"),
        payload,
        {"Content-Type": "application/json"},
    )
    if status != 200:
        raise BakeError(f"prompt failed ({status}): {raw[:300]!r}")
    prompt_id = _decode(raw).get("prompt_id")
    if not prompt_id:
        raise BakeError("prompt response missing prompt_id")
    return str(prompt_id)


def poll_history(
    http: Http,
    server: str,
    prompt_id: str,
    *,
    pause: Pause,
    interval: float = 1.0,
    max_polls: int = 600,
) -> dict[str, Any]:
    url = _url(server, f"/history/{prompt_id}")
    for _ in range(max_polls):
        status, raw = http("GET", url, None, {})
        if status != 200:
            raise BakeError(f"history failed ({status}): {raw[:200]!r}")
        body = _decode(raw)
        entry = body.get(prompt_id) if isinstance(body, dict) else None
        if isinstance(entry, dict):
            state = (entry.get("status") or {}).get("status_str")
            if state == "error":
                raise BakeError(f"ComfyUI prompt {prompt_id} failed")
            if entry.get("outputs"):
                return entry
        pause(interval)
    raise BakeError(f"timed out waiting for ComfyUI history {prompt_id}")


def history_image(entry: dict[str, Any]) -> dict[str, str]:
    for node in entry.get("outputs", {}).values():
        images = node.get("images") if isinstance(node, dict) else None
        if images:
            image = images[0]
            return {
                "filename": image["filename"],
                "subfolder": image.get("subfolder") or "",
                "type": image.get("type") or "output",
            }
    raise BakeError("history had no images")


def download_image(http: Http, server: str, image: dict[str, str]) -> bytes:
    query = urlencode(
        {"filename": image["filename"], "subfolder": image["subfolder"], "type": image["type"]}
    )
    status, raw = http("GET", _url(server, f"/view?{query}"), None, {})
    if status != 200 or not raw:
        raise BakeError(f"download failed ({status})")
    return raw


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bake a Machi WebP via ComfyUI (offline; not compose).")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--ref", type=Path, default=None)
    parser.add_argument("--w", type=int, default=1024)
    parser.add_argument("--h", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=ROOT / "assets" / "comfy" / "bake.webp")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    http: Http = urllib_request,
    pause: Pause = time.sleep,
    convert: Convert = convert_to_webp,
) -> int:
    args = parse_args(argv)
    ref_name = args.ref.name if args.ref else None
    if args.dry_run:
        workflow = build_workflow(
            args.prompt,
            width=args.w,
            height=args.h,
            steps=args.steps,
            seed=args.seed,
            ref_name=ref_name,
        )
        json.dump(workflow, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if os.environ.get("COMFY_BAKE_GO") != "1":
        print(
            "Refusing to run. Set COMFY_BAKE_GO=1 to queue a ComfyUI prompt. "
            "This tool is not part of docker compose up, and it must not restart ComfyUI.",
            file=sys.stderr,
        )
        return 2

    if args.ref is not None:
        if not args.ref.is_file():
            print(f"ref image not found: {args.ref}", file=sys.stderr)
            return 1
        ref_name = upload_image(http, args.server, args.ref)

    workflow = build_workflow(
        args.prompt,
        width=args.w,
        height=args.h,
        steps=args.steps,
        seed=args.seed,
        ref_name=ref_name,
    )
    prompt_id = submit_prompt(http, args.server, workflow)
    entry = poll_history(http, args.server, prompt_id, pause=pause)
    image = history_image(entry)
    data = download_image(http, args.server, image)
    convert(data, args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
