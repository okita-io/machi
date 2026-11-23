import assert from "node:assert/strict";
import { test } from "node:test";
import { interpretationClip, playNpcAudio, playSpeech, speechClips, stopPlayback } from "./playback.ts";

class FakeAudio {
  static last: FakeAudio | null = null;
  static all: FakeAudio[] = [];
  src: string;
  currentTime = 0;
  paused = true;
  private listeners = new Map<string, Array<() => void>>();

  constructor(src?: string) {
    this.src = src ?? "";
    FakeAudio.last = this;
    FakeAudio.all.push(this);
  }

  play(): Promise<void> {
    this.paused = false;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }

  addEventListener(type: string, listener: () => void): void {
    const found = this.listeners.get(type) ?? [];
    found.push(listener);
    this.listeners.set(type, found);
  }

  emit(type: string): void {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
}

test("stopPlayback halts the current NPC clip", () => {
  const previous = globalThis.Audio;
  globalThis.Audio = FakeAudio as unknown as typeof Audio;
  FakeAudio.last = null;
  FakeAudio.all = [];
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

test("repeat uses Sora's clip, and the warm-up clip when she is the only voice", () => {
  assert.equal(interpretationClip("turn", "shop", "coach"), "coach");
  assert.equal(interpretationClip("warmup", "coach-only", ""), "coach-only");
  assert.equal(interpretationClip("turn", "shop", ""), "");
});

test("speech plays the shop line, then the spoken interpretation", () => {
  const previous = globalThis.Audio;
  globalThis.Audio = FakeAudio as unknown as typeof Audio;
  FakeAudio.last = null;
  FakeAudio.all = [];
  try {
    assert.deepEqual(speechClips("shop", "coach"), ["shop", "coach"]);
    assert.deepEqual(speechClips("", "coach"), ["coach"]);
    playSpeech(speechClips("shop", "coach"));
    const shop = FakeAudio.all[0];
    assert.ok(shop);
    assert.match(shop.src, /shop$/);
    assert.equal(FakeAudio.all.length, 1);
    shop.emit("ended");
    const coach = FakeAudio.all[1];
    assert.ok(coach);
    assert.match(coach.src, /coach$/);
    assert.equal(shop.paused, false);
    stopPlayback();
    coach.emit("ended");
    assert.equal(FakeAudio.all.length, 2);
  } finally {
    globalThis.Audio = previous;
  }
});
