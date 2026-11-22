import assert from "node:assert/strict";
import { test } from "node:test";
import {
  consumePcmFrames,
  emptyPcmPending,
  floatSampleToInt16,
  FRAME_BYTES,
  FRAME_SAMPLES,
  pcmFrameLogEnabled,
  sliceFloat32ToInt16Frames,
} from "./pcm.ts";
import { buildSessionWsUrl } from "./socket.ts";
import { PCM_WORKLET_NAME, PCM_WORKLET_SOURCE } from "./workletSource.ts";

test("float sample clamps to int16", () => {
  assert.equal(floatSampleToInt16(0), 0);
  assert.equal(floatSampleToInt16(1), 32767);
  assert.equal(floatSampleToInt16(-1), -32768);
  assert.equal(floatSampleToInt16(2), 32767);
});

test("sliceFloat32ToInt16Frames emits 640-byte frames and a remainder", () => {
  const samples = new Float32Array(FRAME_SAMPLES + 10);
  samples.fill(1);
  const { frames, remainder } = sliceFloat32ToInt16Frames(samples);
  assert.equal(frames.length, 1);
  assert.equal(frames[0]?.byteLength, FRAME_BYTES);
  assert.equal(frames[0]?.[0], 0xff);
  assert.equal(frames[0]?.[1], 0x7f);
  assert.equal(remainder.length, 10);
  assert.equal(samples[0], 1);
});

test("consumePcmFrames assembles a 20 ms frame across chunks at 16 kHz", () => {
  const first = consumePcmFrames(emptyPcmPending(), new Float32Array(100), 16000);
  assert.equal(first.frames.length, 0);
  assert.equal(first.pending.samples.length, 100);
  const second = consumePcmFrames(first.pending, new Float32Array(220), 16000);
  assert.equal(second.frames.length, 1);
  assert.equal(second.frames[0]?.byteLength, 640);
  assert.equal(second.pending.samples.length, 0);
});

test("consumePcmFrames downsamples 48 kHz to 16 kHz frames", () => {
  const block = new Float32Array(480);
  block.fill(1);
  const partial = consumePcmFrames(emptyPcmPending(), block, 48000);
  assert.equal(partial.frames.length, 0);
  const done = consumePcmFrames(partial.pending, block, 48000);
  assert.equal(done.frames.length, 1);
  assert.equal(done.frames[0]?.byteLength, 640);
  assert.equal(done.frames[0]?.[0], 0xff);
  assert.equal(done.frames[0]?.[1], 0x7f);
  assert.equal(done.pending.samples.length, 0);
});

test("pcm frame logs are dev-only", () => {
  assert.equal(pcmFrameLogEnabled(false, undefined), false);
  assert.equal(pcmFrameLogEnabled(false, "1"), false);
  assert.equal(pcmFrameLogEnabled(true, undefined), true);
  assert.equal(pcmFrameLogEnabled(true, "0"), false);
  assert.equal(pcmFrameLogEnabled(true, "false"), false);
});

test("session websocket url stays on the page host", () => {
  assert.equal(
    buildSessionWsUrl("abc", { apiBase: "/api", protocol: "http:", host: "localhost:5173" }),
    "ws://localhost:5173/api/ws/abc",
  );
  assert.equal(
    buildSessionWsUrl("abc", { apiBase: "/api", protocol: "https:", host: "machi.local" }),
    "wss://machi.local/api/ws/abc",
  );
  assert.equal(
    buildSessionWsUrl("abc", {
      apiBase: "http://localhost:8100",
      protocol: "http:",
      host: "localhost:5173",
    }),
    "ws://localhost:8100/ws/abc",
  );
});

test("worklet source registers the capture processor", () => {
  assert.match(PCM_WORKLET_SOURCE, new RegExp(`registerProcessor\\("${PCM_WORKLET_NAME}"`));
});
