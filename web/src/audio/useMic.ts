import { useEffect, useRef, useState } from "react";
import type { TurnResult } from "../api";
import { MicCapture, micErrorMessage } from "./capture";
import {
  describeSend,
  emptyMicDebug,
  formatMicDebug,
  micBlockedReason,
  readMicPage,
  type MicDebugSnapshot,
} from "./micDebug";
import { pcmChunksToBase64, pcmClipStats } from "./pcm";
import { stopPlayback } from "./playback";
import { encodeControl, sessionWsUrl } from "./socket";

type ServerEvent =
  | ({ type: "turn_result" } & TurnResult)
  | { type: "error"; detail?: string }
  | { type: "audio_ack"; frames?: number; event?: string };

/**
 * Push-to-talk mic over the session WebSocket.
 * Push-to-talk (`handsFree` false) ends on release (`audio_stop` + `turn`).
 * The server does not run VAD on that path. Hands-free may emit `turn_result`
 * after trailing silence; release still sends `turn`.
 * Starting a capture (push-to-talk press or hands-free capture start) stops
 * NPC playback immediately. The server cancels an in-flight turn on `audio_start`.
 * Push-to-talk posts the clip on the socket when it is open. A closed socket
 * posts the same clip over HTTP so the previous transcript is not left up.
 */
export function useMic(
  sessionId: string | null,
  handsFree: boolean,
  onTurn: (result: TurnResult) => void,
  hintMaxRef?: { current: Record<string, number> },
  reviewActive = false,
  onReviewAudio?: (audioB64: string) => void | Promise<void>,
  onSessionLost?: () => void,
  onClipStart?: (bytes?: number) => void,
  onAudioFallback?: (audioB64: string) => void | Promise<void>,
) {
  const [recording, setRecording] = useState(false);
  const [sending, setSending] = useState(false);
  const [frames, setFrames] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [debug, setDebug] = useState<MicDebugSnapshot>(() => emptyMicDebug(readMicPage()));

  const wsRef = useRef<WebSocket | null>(null);
  const captureRef = useRef<MicCapture | null>(null);
  const handsFreeRef = useRef(handsFree);
  const onTurnRef = useRef(onTurn);
  const reviewActiveRef = useRef(reviewActive);
  const onReviewAudioRef = useRef(onReviewAudio);
  const onSessionLostRef = useRef(onSessionLost);
  const onClipStartRef = useRef(onClipStart);
  const onAudioFallbackRef = useRef(onAudioFallback);
  const reviewChunksRef = useRef<Uint8Array[]>([]);
  const pressedRef = useRef(false);
  const sentStartRef = useRef(false);
  const seqRef = useRef(0);
  const opRef = useRef<Promise<void>>(Promise.resolve());
  const localFramesRef = useRef(0);
  const localBytesRef = useRef(0);
  handsFreeRef.current = handsFree;
  onTurnRef.current = onTurn;
  reviewActiveRef.current = reviewActive;
  onReviewAudioRef.current = onReviewAudio;
  onSessionLostRef.current = onSessionLost;
  onClipStartRef.current = onClipStart;
  onAudioFallbackRef.current = onAudioFallback;

  useEffect(() => {
    const reason = micBlockedReason(readMicPage());
    if (reason) {
      setError(reason);
      console.info("[machi] mic\n" + formatMicDebug(emptyMicDebug(readMicPage())));
    }
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    const url = sessionWsUrl(sessionId);
    let stopped = false;
    let socket: WebSocket | null = null;
    let retryTimer = 0;

    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(url);
      socket = ws;
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";
      setDebug((prev) => ({ ...prev, wsUrl: url, wsState: "connecting" }));
      ws.onopen = () => {
        if (stopped || wsRef.current !== ws) return;
        setReady(true);
        setDebug((prev) => ({ ...prev, wsState: "open" }));
      };
      ws.onclose = (ev) => {
        if (wsRef.current === ws) {
          setReady(false);
          setSending(false);
          setDebug((prev) => ({ ...prev, wsState: "closed" }));
        }
        if (stopped) return;
        // 4404: the orchestrator no longer has this session. A retry would close again.
        if (ev.code === 4404) {
          onSessionLostRef.current?.();
          return;
        }
        retryTimer = window.setTimeout(connect, 1000);
      };
      ws.onerror = () => {
        if (wsRef.current === ws) setError("Session WebSocket failed");
      };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        let msg: ServerEvent;
        try {
          msg = JSON.parse(ev.data) as ServerEvent;
        } catch {
          return;
        }
        if (msg.type === "audio_ack" && typeof msg.frames === "number") {
          const acked = msg.frames;
          setFrames(acked);
          setDebug((prev) => ({ ...prev, serverFrames: acked }));
        } else if (msg.type === "turn_result") {
          setSending(false);
          onTurnRef.current(msg);
        } else if (msg.type === "error") {
          setSending(false);
          setError(micErrorMessage(msg.detail || "Turn failed"));
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
      if (wsRef.current === socket) wsRef.current = null;
      void captureRef.current?.stop();
      captureRef.current = null;
    };
  }, [sessionId]);

  useEffect(() => {
    if (reviewActive) {
      setReady(true);
      return;
    }
    setReady(wsRef.current?.readyState === WebSocket.OPEN);
  }, [reviewActive]);

  function enqueue(task: () => Promise<void>) {
    opRef.current = opRef.current.then(task).catch((err: unknown) => {
      setError(micErrorMessage(err));
      setRecording(false);
      setSending(false);
    });
  }

  function holdStart() {
    const review = reviewActiveRef.current;
    if (pressedRef.current) return;
    if (!review && !sessionId) {
      setError("No session yet. Wait for the page to reconnect.");
      return;
    }
    stopPlayback();
    onClipStartRef.current?.();
    pressedRef.current = true;
    sentStartRef.current = false;
    reviewChunksRef.current = [];
    const gen = ++seqRef.current;
    const capture = new MicCapture();
    captureRef.current = capture;
    setError(null);
    localFramesRef.current = 0;
    localBytesRef.current = 0;
    setDebug((prev) => ({
      ...prev,
      localFrames: 0,
      localBytes: 0,
      serverFrames: 0,
      lastSend: "Holding. Audio has not been sent yet.",
    }));
    enqueue(async () => {
      if (seqRef.current !== gen) return;
      try {
        await capture.prepare();
        if (seqRef.current !== gen) {
          await capture.stop();
          return;
        }
        const live = reviewActiveRef.current;
        const ws = wsRef.current;
        if (!live && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(
            encodeControl({
              type: "audio_start",
              hands_free: handsFreeRef.current,
              hint_max: hintMaxRef?.current ?? {},
            }),
          );
        }
        sentStartRef.current = true;
        capture.connect((frame) => {
          const copy = frame.slice();
          reviewChunksRef.current.push(copy);
          localFramesRef.current += 1;
          localBytesRef.current += copy.byteLength;
          if (localFramesRef.current % 10 === 0) {
            const localFrames = localFramesRef.current;
            const localBytes = localBytesRef.current;
            setDebug((prev) => ({ ...prev, localFrames, localBytes }));
          }
          if (reviewActiveRef.current) return;
          const socket = wsRef.current;
          if (socket && socket.readyState === WebSocket.OPEN) socket.send(copy);
        });
        setFrames(0);
        setRecording(true);
      } catch (err) {
        await capture.stop();
        pressedRef.current = false;
        setRecording(false);
        const message = micErrorMessage(err);
        setError(message);
        setDebug((prev) => {
          const next = { ...prev, lastSend: message };
          console.info("[machi] mic\n" + formatMicDebug(next));
          return next;
        });
      }
    });
  }

  function holdEnd() {
    if (!pressedRef.current) return;
    pressedRef.current = false;
    seqRef.current += 1;
    const review = reviewActiveRef.current;
    enqueue(async () => {
      setRecording(false);
      await captureRef.current?.stop();
      captureRef.current = null;
      const chunks = reviewChunksRef.current;
      reviewChunksRef.current = [];
      const localFrames = localFramesRef.current;
      const localBytes = localBytesRef.current;
      setDebug((prev) => ({ ...prev, localFrames, localBytes }));
      if (!sentStartRef.current) {
        const page = readMicPage();
        const blocked = micBlockedReason(page);
        const lastSend = blocked
          ? "Nothing was sent. The page cannot capture the microphone."
          : "Nothing was sent. Capture stopped before it started.";
        setDebug((prev) => {
          const next = { ...prev, lastSend };
          console.info("[machi] mic\n" + formatMicDebug(next));
          return next;
        });
        return;
      }
      sentStartRef.current = false;
      if (review) {
        const audioB64 = pcmChunksToBase64(chunks);
        const lastSend = audioB64
          ? `Sent ${localBytes} bytes of PCM (${localFrames} frames) to the review.`
          : "Release captured 0 bytes, so nothing was sent.";
        setDebug((prev) => {
          const next = { ...prev, lastSend };
          console.info("[machi] mic\n" + formatMicDebug(next));
          return next;
        });
        if (!audioB64) {
          setError("No microphone audio was captured");
          return;
        }
        setSending(true);
        try {
          await onReviewAudioRef.current?.(audioB64);
        } finally {
          setSending(false);
        }
        return;
      }
      const audioB64 = pcmChunksToBase64(chunks);
      const identity = clipIdentity(chunks);
      onClipStartRef.current?.(localBytes);
      if (!audioB64) {
        setSending(false);
        setError("No microphone audio was captured");
        setDebug((prev) => {
          const next = {
            ...prev,
            lastSend: "Release captured 0 bytes, so nothing was sent.",
          };
          console.info("[machi] mic\n" + formatMicDebug(next));
          return next;
        });
        return;
      }
      const socket = wsRef.current;
      const open = Boolean(socket && socket.readyState === WebSocket.OPEN);
      if (open && socket) {
        setSending(true);
        const lastSend = `${describeSend(localFrames, localBytes, "open")} ${identity}`;
        setDebug((prev) => {
          const next = { ...prev, lastSend };
          console.info("[machi] mic\n" + formatMicDebug(next));
          return next;
        });
        socket.send(encodeControl({ type: "audio_stop" }));
        socket.send(
          encodeControl({
            type: "turn",
            hint_max: hintMaxRef?.current ?? {},
            audio_b64: audioB64,
          }),
        );
        return;
      }
      const fallback = onAudioFallbackRef.current;
      if (!fallback) {
        setSending(false);
        setError("Session WebSocket is not connected");
        const lastSend = `${describeSend(localFrames, localBytes, "closed")} ${identity}`;
        setDebug((prev) => {
          const next = { ...prev, wsState: "closed", lastSend };
          console.info("[machi] mic\n" + formatMicDebug(next));
          return next;
        });
        return;
      }
      setSending(true);
      const lastSend = `Posting ${localBytes} bytes (${localFrames} frames, ${identity}) because the WebSocket is closed.`;
      setDebug((prev) => {
        const next = { ...prev, wsState: "closed", lastSend };
        console.info("[machi] mic\n" + formatMicDebug(next));
        return next;
      });
      try {
        await fallback(audioB64);
      } finally {
        setSending(false);
      }
    });
  }

  return { recording, sending, frames, error, ready, debug, holdStart, holdEnd };
}

function clipIdentity(chunks: Uint8Array[]): string {
  const stats = pcmClipStats(chunks);
  return `peak ${stats.peak}, checksum ${stats.checksum}`;
}
