import assert from "node:assert/strict";
import { test } from "node:test";
import { playNpcAudio, stopPlayback } from "./playback.ts";

class FakeAudio {
  static last: FakeAudio | null = null;
  src: string;
  currentTime = 0;
  paused = true;

  constructor(src?: string) {
    this.src = src ?? "";
    FakeAudio.last = this;
  }

  play(): Promise<void> {
    this.paused = false;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }
}

test("stopPlayback halts the current NPC clip", () => {
  const previous = globalThis.Audio;
  globalThis.Audio = FakeAudio as unknown as typeof Audio;
  FakeAudio.last = null;
  try {
    playNpcAudio("QQ==");
    const clip = FakeAudio.last;
    assert.ok(clip);
    assert.equal(clip.paused, false);
    assert.match(clip.src, /^data:audio\/wav;base64,QQ==$/);
    stopPlayback();
    assert.equal(clip.paused, true);
    assert.equal(clip.currentTime, 0);
    assert.equal(clip.src, "");
    stopPlayback();
  } finally {
    globalThis.Audio = previous;
  }
});
