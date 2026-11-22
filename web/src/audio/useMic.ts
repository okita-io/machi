import { useEffect, useRef, useState } from "react";
import type { TurnResult } from "../api";
import { MicCapture, micErrorMessage } from "./capture";
import { pcmChunksToBase64 } from "./pcm";
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
 */
export function useMic(
  sessionId: string | null,
  handsFree: boolean,
  onTurn: (result: TurnResult) => void,
  hintMaxRef?: { current: Record<string, number> },
  reviewActive = false,
  onReviewAudio?: (audioB64: string) => void | Promise<void>,
) {
  const [recording, setRecording] = useState(false);
  const [sending, setSending] = useState(false);
  const [frames, setFrames] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const captureRef = useRef<MicCapture | null>(null);
  const handsFreeRef = useRef(handsFree);
  const onTurnRef = useRef(onTurn);
  const reviewActiveRef = useRef(reviewActive);
  const onReviewAudioRef = useRef(onReviewAudio);
  const reviewChunksRef = useRef<Uint8Array[]>([]);
  const pressedRef = useRef(false);
  const sentStartRef = useRef(false);
  const seqRef = useRef(0);
  const opRef = useRef<Promise<void>>(Promise.resolve());
  handsFreeRef.current = handsFree;
  onTurnRef.current = onTurn;
  reviewActiveRef.current = reviewActive;
  onReviewAudioRef.current = onReviewAudio;

  useEffect(() => {
    if (!sessionId) return;
    const ws = new WebSocket(sessionWsUrl(sessionId));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => setReady(true);
    ws.onclose = () => setReady(false);
    ws.onerror = () => setError("Session WebSocket failed");
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      let msg: ServerEvent;
      try {
        msg = JSON.parse(ev.data) as ServerEvent;
      } catch {
        return;
      }
      if (msg.type === "audio_ack" && typeof msg.frames === "number") {
        setFrames(msg.frames);
      } else if (msg.type === "turn_result") {
        setSending(false);
        onTurnRef.current(msg);
      } else if (msg.type === "error") {
        setSending(false);
        setError(msg.detail || "Turn failed");
      }
    };
    return () => {
      ws.close();
      if (wsRef.current === ws) wsRef.current = null;
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
    if (pressedRef.current || (!review && !sessionId)) return;
    const ws = wsRef.current;
    if (!review && (!ws || ws.readyState !== WebSocket.OPEN)) {
      setError("Session WebSocket is not connected");
      return;
    }
    stopPlayback();
    pressedRef.current = true;
    sentStartRef.current = false;
    reviewChunksRef.current = [];
    const gen = ++seqRef.current;
    const capture = new MicCapture();
    captureRef.current = capture;
    setError(null);
    enqueue(async () => {
      if (seqRef.current !== gen) return;
      try {
        await capture.prepare();
        const live = reviewActiveRef.current;
        if (seqRef.current !== gen || (!live && ws?.readyState !== WebSocket.OPEN)) {
          await capture.stop();
          return;
        }
        if (!live && ws) {
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
          if (reviewActiveRef.current) {
            reviewChunksRef.current.push(frame.slice());
            return;
          }
          if (ws && ws.readyState === WebSocket.OPEN) ws.send(frame);
        });
        setFrames(0);
        setRecording(true);
      } catch (err) {
        await capture.stop();
        pressedRef.current = false;
        setRecording(false);
        setError(micErrorMessage(err));
      }
    });
  }

  function holdEnd() {
    if (!pressedRef.current) return;
    pressedRef.current = false;
    seqRef.current += 1;
    const ws = wsRef.current;
    const review = reviewActiveRef.current;
    enqueue(async () => {
      setRecording(false);
      await captureRef.current?.stop();
      captureRef.current = null;
      const chunks = reviewChunksRef.current;
      reviewChunksRef.current = [];
      if (!sentStartRef.current) return;
      sentStartRef.current = false;
      if (review) {
        setSending(true);
        try {
          await onReviewAudioRef.current?.(pcmChunksToBase64(chunks));
        } finally {
          setSending(false);
        }
        return;
      }
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        setSending(false);
        setError("Session WebSocket is not connected");
        return;
      }
      setSending(true);
      ws.send(encodeControl({ type: "audio_stop" }));
      ws.send(encodeControl({ type: "turn", hint_max: hintMaxRef?.current ?? {} }));
    });
  }

  return { recording, sending, frames, error, ready, holdStart, holdEnd };
}
