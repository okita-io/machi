/** NPC clip playback. Barge-in calls `stopPlayback` as soon as a new capture starts. */

let current: HTMLAudioElement | null = null;

export function playNpcAudio(wavB64: string): void {
  stopPlayback();
  const audio = new Audio(`data:audio/wav;base64,${wavB64}`);
  current = audio;
  void audio.play().catch(() => {
    // Autoplay can reject. The element stays current so barge-in can still stop it.
  });
}

export function stopPlayback(): void {
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
