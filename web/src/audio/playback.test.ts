import assert from "node:assert/strict";
import { test } from "node:test";
import { playNpcAudio, playSpeech, replyClips, stopPlayback, type SpeechPart } from "./playback.ts";

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

test("speech plays the shop line, then what was heard, then the correction", () => {
  const previous = globalThis.Audio;
  globalThis.Audio = FakeAudio as unknown as typeof Audio;
  FakeAudio.last = null;
  FakeAudio.all = [];
  const parts: Array<SpeechPart | null> = [];
  try {
    const clips = replyClips({ shop: "shop", heard: "heard", pronounce: "correction" });
    assert.deepEqual(
      clips.map((clip) => clip.part),
      ["shop", "heard", "pronounce"],
    );
    assert.deepEqual(
      replyClips({ heard: "heard" }).map((clip) => clip.wav),
      ["heard"],
    );
    playSpeech(clips, undefined, (part) => parts.push(part));
    assert.deepEqual(parts, ["shop"]);
    FakeAudio.all[0]?.emit("ended");
    assert.deepEqual(parts, ["shop", "heard"]);
    FakeAudio.all[1]?.emit("ended");
    assert.deepEqual(parts, ["shop", "heard", "pronounce"]);
    const correction = FakeAudio.all[2];
    assert.ok(correction);
    assert.match(correction.src, /correction$/);
    correction.emit("ended");
    assert.deepEqual(parts, ["shop", "heard", "pronounce", null]);
    stopPlayback();
  } finally {
    globalThis.Audio = previous;
  }
});
