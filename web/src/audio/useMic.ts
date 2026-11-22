import { useEffect, useRef, useState } from "react";
import type { TurnResult } from "../api";
import { MicCapture, micErrorMessage } from "./capture";
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
  const pressedRef = useRef(false);
  const sentStartRef = useRef(false);
  const seqRef = useRef(0);
  const opRef = useRef<Promise<void>>(Promise.resolve());
  handsFreeRef.current = handsFree;
  onTurnRef.current = onTurn;

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

  function enqueue(task: () => Promise<void>) {
    opRef.current = opRef.current.then(task).catch((err: unknown) => {
      setError(micErrorMessage(err));
      setRecording(false);
      setSending(false);
    });
  }

  function holdStart() {
    if (pressedRef.current || !sessionId) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setError("Session WebSocket is not connected");
      return;
    }
    stopPlayback();
    pressedRef.current = true;
    sentStartRef.current = false;
    const gen = ++seqRef.current;
    const capture = new MicCapture();
    captureRef.current = capture;
    setError(null);
    enqueue(async () => {
      if (seqRef.current !== gen) return;
      try {
        await capture.prepare();
        if (seqRef.current !== gen || ws.readyState !== WebSocket.OPEN) {
          await capture.stop();
          return;
        }
        ws.send(encodeControl({ type: "audio_start", hands_free: handsFreeRef.current }));
        sentStartRef.current = true;
        capture.connect((frame) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(frame);
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
    enqueue(async () => {
      setRecording(false);
      await captureRef.current?.stop();
      captureRef.current = null;
      if (!sentStartRef.current) return;
      sentStartRef.current = false;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        setSending(false);
        setError("Session WebSocket is not connected");
        return;
      }
      setSending(true);
      ws.send(encodeControl({ type: "audio_stop" }));
      ws.send(encodeControl({ type: "turn" }));
    });
  }

  return { recording, sending, frames, error, ready, holdStart, holdEnd };
}
