export type AudioControl =
  | { type: "audio_start"; hands_free: boolean; hint_max?: Record<string, number> }
  | { type: "audio_stop" }
  | { type: "turn"; text?: string; hint_max?: Record<string, number> };

export function buildSessionWsUrl(
  sessionId: string,
  env: { apiBase?: string; protocol: string; host: string },
): string {
  const base = (env.apiBase || "/api").replace(/\/$/, "");
  const id = encodeURIComponent(sessionId);
  if (base.startsWith("ws://") || base.startsWith("wss://")) {
    return `${base}/ws/${id}`;
  }
  if (base.startsWith("http://") || base.startsWith("https://")) {
    return `${base.replace(/^http/, "ws")}/ws/${id}`;
  }
  const proto = env.protocol === "https:" ? "wss:" : "ws:";
  const path = base.startsWith("/") ? base : `/${base}`;
  return `${proto}//${env.host}${path}/ws/${id}`;
}

export function sessionWsUrl(sessionId: string): string {
  return buildSessionWsUrl(sessionId, {
    apiBase: import.meta.env.VITE_API_BASE,
    protocol: window.location.protocol,
    host: window.location.host,
  });
}

export function encodeControl(message: AudioControl): string {
  return JSON.stringify(message);
}
