/** Clip playback. Barge-in calls `stopPlayback` as soon as a new capture starts. */

import { analyserGain, mouthFrameForGain, type MouthFrame } from "../mouth.ts";

let current: HTMLAudioElement | null = null;
let rafId = 0;
let audioCtx: AudioContext | null = null;
let playGeneration = 0;

/** Shop line first, then Sora's spoken interpretation when that clip exists. */
export function speechClips(npcWav?: string, coachWav?: string): string[] {
  const clips: string[] = [];
  if (npcWav) clips.push(npcWav);
  if (coachWav) clips.push(coachWav);
  return clips;
}

/** The clip Repeat should play: Sora's line, or the warm-up clip when that is the only one. */
export function interpretationClip(kind: string, npcWav?: string, coachWav?: string): string {
  if (coachWav) return coachWav;
  if (kind === "warmup" && npcWav) return npcWav;
  return "";
}

export function playNpcAudio(wavB64: string, onMouth?: (frame: MouthFrame) => void): void {
  playSpeech([wavB64], onMouth);
}

export function playSpeech(wavs: string[], onMouth?: (frame: MouthFrame) => void): void {
  stopPlayback();
  const clips = wavs.filter((item) => item.length > 0);
  if (!clips.length) return;
  startClip(clips, 0, playGeneration, onMouth);
}

function startClip(
  clips: string[],
  index: number,
  generation: number,
  onMouth?: (frame: MouthFrame) => void,
): void {
  if (generation !== playGeneration) return;
  const audio = new Audio(`data:audio/wav;base64,${clips[index]}`);
  current = audio;
  const hasNext = index + 1 < clips.length;
  if (onMouth || hasNext) {
    audio.addEventListener("ended", () => {
      if (generation !== playGeneration || current !== audio) return;
      if (hasNext) startClip(clips, index + 1, generation, onMouth);
      else if (onMouth) onMouth("closed");
    });
  }
  attachAnalyser(audio, onMouth);
  void audio.play().catch(() => {
    // Autoplay can reject. The element stays current so barge-in can still stop it.
  });
}

export function stopPlayback(): void {
  playGeneration += 1;
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
