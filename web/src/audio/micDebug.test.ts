import assert from "node:assert/strict";
import { test } from "node:test";
import {
  describeSend,
  emptyMicDebug,
  formatMicDebug,
  httpsMicUrl,
  micBlockedReason,
  type MicPage,
} from "./micDebug.ts";

const tailscale: MicPage = {
  href: "http://100.81.228.4:5173/",
  protocol: "http:",
  host: "100.81.228.4:5173",
  secureContext: false,
  hasGetUserMedia: false,
};

test("plain HTTP off localhost explains that the microphone cannot send audio", () => {
  const reason = micBlockedReason(tailscale);
  assert.match(reason, /http:\/\/100\.81\.228\.4:5173/);
  assert.match(reason, /https:\/\/100\.81\.228\.4:5174/);
  assert.match(reason, /no audio can be sent/);
  const text = formatMicDebug(emptyMicDebug(tailscale, "ws://100.81.228.4:5173/api/ws/abc"));
  assert.match(text, /secure context: no/);
  assert.match(text, /getUserMedia: unavailable/);
  assert.match(text, /microphone: blocked/);
  assert.match(text, /No audio has been sent yet/);
});

test("localhost HTTP is allowed to capture", () => {
  const page: MicPage = {
    href: "http://localhost:5173/",
    protocol: "http:",
    host: "localhost:5173",
    secureContext: true,
    hasGetUserMedia: true,
  };
  assert.equal(micBlockedReason(page), "");
  const text = formatMicDebug(emptyMicDebug(page));
  assert.match(text, /secure context: yes/);
  assert.match(text, /microphone: allowed on this page/);
});

test("a closed socket keeps captured audio in the browser", () => {
  assert.match(describeSend(12, 7680, "closed"), /stayed in the browser/);
  assert.match(describeSend(0, 0, "open"), /0 bytes/);
  assert.match(describeSend(4, 2560, "open"), /Sent 2560 bytes/);
});

test("https mic url drops the current port", () => {
  assert.equal(httpsMicUrl("100.81.228.4:5173"), "https://100.81.228.4:5174");
  assert.equal(httpsMicUrl("localhost"), "https://localhost:5174");
});
