"""Per-session PCM accumulation for the browser WebSocket."""

from __future__ import annotations

import base64

# 20 ms of mono 16 kHz signed 16-bit PCM.
SAMPLE_RATE = 16_000
FRAME_MS = 20
PCM_FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
PCM_FRAME_BYTES = PCM_FRAME_SAMPLES * 2


class SessionAudioBuffer:
    """PCM captured on one WebSocket, owned by that connection's handler."""

    def __init__(self) -> None:
        self.pcm = bytearray()
        self.frames = 0
        self.capturing = False
        self.hands_free = False

    def start(self, *, hands_free: bool = False) -> None:
        self.pcm.clear()
        self.frames = 0
        self.capturing = True
        self.hands_free = hands_free

    def stop(self) -> int:
        self.capturing = False
        return self.frames

    def append(self, frame: bytes) -> bool:
        if not self.capturing or len(frame) != PCM_FRAME_BYTES:
            return False
        self.pcm.extend(frame)
        self.frames += 1
        return True

    def clear(self) -> None:
        self.pcm.clear()
        self.frames = 0
        self.capturing = False

    def take_b64(self) -> str | None:
        if not self.pcm:
            self.capturing = False
            return None
        encoded = base64.b64encode(bytes(self.pcm)).decode("ascii")
        self.clear()
        return encoded
