/** Why this page can or cannot capture a microphone and send the bytes. */

export type MicPage = {
  href: string;
  protocol: string;
  host: string;
  secureContext: boolean;
  hasGetUserMedia: boolean;
};

export type MicDebugSnapshot = {
  pageUrl: string;
  secureContext: boolean;
  getUserMedia: boolean;
  blockedReason: string;
  wsUrl: string;
  wsState: string;
  localFrames: number;
  localBytes: number;
  serverFrames: number;
  lastSend: string;
};

export function httpsMicUrl(host: string): string {
  const hostname = host.replace(/:\d+$/, "");
  return `https://${hostname}:5174`;
}

export function micBlockedReason(page: MicPage): string {
  if (!page.secureContext) {
    const where = page.protocol && page.host ? `${page.protocol}//${page.host}` : "this page";
    return (
      `${where} is not a secure context. Browsers refuse the microphone here, ` +
      `so no audio can be sent. Open ${httpsMicUrl(page.host || "localhost")} ` +
      `or http://localhost:5173 on this computer.`
    );
  }
  if (!page.hasGetUserMedia) {
    return "This browser has no getUserMedia, so no audio can be captured.";
  }
  return "";
}

export function readMicPage(): MicPage {
  if (typeof window === "undefined") {
    return {
      href: "",
      protocol: "",
      host: "",
      secureContext: false,
      hasGetUserMedia: false,
    };
  }
  return {
    href: window.location.href,
    protocol: window.location.protocol,
    host: window.location.host,
    secureContext: window.isSecureContext,
    hasGetUserMedia: !!navigator.mediaDevices?.getUserMedia,
  };
}

export function emptyMicDebug(page: MicPage, wsUrl = ""): MicDebugSnapshot {
  return {
    pageUrl: page.href,
    secureContext: page.secureContext,
    getUserMedia: page.hasGetUserMedia,
    blockedReason: micBlockedReason(page),
    wsUrl,
    wsState: "not created",
    localFrames: 0,
    localBytes: 0,
    serverFrames: 0,
    lastSend: "No audio has been sent yet.",
  };
}

export function formatMicDebug(debug: MicDebugSnapshot): string {
  const microphone = debug.blockedReason
    ? `blocked. ${debug.blockedReason}`
    : "allowed on this page";
  return [
    `page: ${debug.pageUrl || "(unknown)"}`,
    `secure context: ${debug.secureContext ? "yes" : "no"}`,
    `getUserMedia: ${debug.getUserMedia ? "available" : "unavailable"}`,
    `microphone: ${microphone}`,
    `websocket: ${debug.wsState}${debug.wsUrl ? ` ${debug.wsUrl}` : ""}`,
    `captured: ${debug.localFrames} frames, ${debug.localBytes} bytes`,
    `server acked: ${debug.serverFrames} frames`,
    `last send: ${debug.lastSend}`,
  ].join("\n");
}

export function describeSend(localFrames: number, localBytes: number, wsState: string): string {
  if (localBytes <= 0) {
    return "Release captured 0 bytes, so nothing was sent.";
  }
  if (wsState !== "open") {
    return (
      `Captured ${localBytes} bytes (${localFrames} frames), ` +
      `but the WebSocket was ${wsState}, so the audio stayed in the browser.`
    );
  }
  return `Sent ${localBytes} bytes of PCM (${localFrames} frames) on the turn message.`;
}
