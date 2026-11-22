import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type ServerOptions } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const httpsOn = process.env.HTTPS === "1";

function httpsConfig(): ServerOptions["https"] {
  if (!httpsOn) return undefined;
  const dir = path.join(root, ".certs");
  return {
    key: fs.readFileSync(path.join(dir, "machi.key")),
    cert: fs.readFileSync(path.join(dir, "machi.crt")),
  };
}

const proxy: ServerOptions["proxy"] = {
  "/api": {
    target: process.env.VITE_ORCHESTRATOR_URL || "http://localhost:8100",
    changeOrigin: true,
    ws: true,
    rewrite: (p) => p.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: httpsOn ? 5174 : 5173,
    https: httpsConfig(),
    proxy,
  },
  preview: {
    host: "0.0.0.0",
    port: httpsOn ? 5174 : 4173,
    https: httpsConfig(),
    proxy,
  },
});