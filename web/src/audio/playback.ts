/** Clip playback. Barge-in calls `stopPlayback` as soon as a new capture starts. */

import { analyserGain, mouthFrameForGain, type MouthFrame } from "../mouth.ts";

export type SpeechPart = "shop" | "heard" | "pronounce";

export type SpeechClip = {
  wav: string;
  part: SpeechPart;
};

let current: HTMLAudioElement | null = null;
let rafId = 0;
let audioCtx: AudioContext | null = null;
let playGeneration = 0;
let onPartListener: ((part: SpeechPart | null) => void) | null = null;

/** Shop line, then what was heard, then the correction as its own clip. */
export function replyClips(parts: {
  shop?: string;
  heard?: string;
  pronounce?: string;
}): SpeechClip[] {
  const clips: SpeechClip[] = [];
  if (parts.shop) clips.push({ wav: parts.shop, part: "shop" });
  if (parts.heard) clips.push({ wav: parts.heard, part: "heard" });
  if (parts.pronounce) clips.push({ wav: parts.pronounce, part: "pronounce" });
  return clips;
}

export function playNpcAudio(wavB64: string, onMouth?: (frame: MouthFrame) => void): void {
  playSpeech([{ wav: wavB64, part: "shop" }], onMouth);
}

export function playSpeech(
  clips: SpeechClip[],
  onMouth?: (frame: MouthFrame) => void,
  onPart?: (part: SpeechPart | null) => void,
): void {
  stopPlayback();
  const playable = clips.filter((item) => item.wav.length > 0);
  if (!playable.length) return;
  onPartListener = onPart ?? null;
  startClip(playable, 0, playGeneration, onMouth);
}

function startClip(
  clips: SpeechClip[],
  index: number,
  generation: number,
  onMouth?: (frame: MouthFrame) => void,
): void {
  if (generation !== playGeneration) return;
  const clip = clips[index];
  if (!clip) return;
  onPartListener?.(clip.part);
  const audio = new Audio(`data:audio/wav;base64,${clip.wav}`);
  current = audio;
  const hasNext = index + 1 < clips.length;
  audio.addEventListener("ended", () => {
    if (generation !== playGeneration || current !== audio) return;
    if (hasNext) startClip(clips, index + 1, generation, onMouth);
    else {
      const notify = onPartListener;
      onPartListener = null;
      notify?.(null);
      if (onMouth) onMouth("closed");
    }
  });
  attachAnalyser(audio, onMouth);
  void audio.play().catch(() => {
    // Autoplay can reject. The element stays current so barge-in can still stop it.
  });
}

export function stopPlayback(): void {
  playGeneration += 1;
  const notify = onPartListener;
  onPartListener = null;
  notify?.(null);
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
