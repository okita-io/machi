/** NPC clip playback. Barge-in calls `stopPlayback` as soon as a new capture starts. */

import { analyserGain, mouthFrameForGain, type MouthFrame } from "../mouth.ts";

let current: HTMLAudioElement | null = null;
let rafId = 0;
let audioCtx: AudioContext | null = null;

export function playNpcAudio(wavB64: string, onMouth?: (frame: MouthFrame) => void): void {
  stopPlayback();
  const audio = new Audio(`data:audio/wav;base64,${wavB64}`);
  current = audio;
  attachAnalyser(audio, onMouth);
  if (onMouth) {
    audio.addEventListener("ended", () => {
      if (current === audio) onMouth("closed");
    });
  }
  void audio.play().catch(() => {
    // Autoplay can reject. The element stays current so barge-in can still stop it.
  });
}

export function stopPlayback(): void {
  clearAnalyser();
  const audio = current;
  if (!audio) return;
  current = null;
  audio.pause();
  try {
    audio.currentTime = 0;
  } catch {
    // Not seekable yet.
  }
  audio.src = "";
}

function clearAnalyser() {
  if (rafId) {
    cancelAnimationFrame(rafId);
    rafId = 0;
  }
}

function attachAnalyser(audio: HTMLAudioElement, onMouth?: (frame: MouthFrame) => void) {
  if (!onMouth || typeof AudioContext === "undefined") return;
  try {
    audioCtx = audioCtx ?? new AudioContext();
    void audioCtx.resume();
    const source = audioCtx.createMediaElementSource(audio);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioCtx.destination);
    const bins = new Uint8Array(analyser.fftSize);
    let last: MouthFrame | null = null;
    const tick = () => {
      if (current !== audio) return;
      analyser.getByteTimeDomainData(bins);
      const frame = mouthFrameForGain(analyserGain(bins));
      if (frame !== last) {
        last = frame;
        onMouth(frame);
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
  } catch {
    // The element still plays if the graph cannot start.
  }
}
