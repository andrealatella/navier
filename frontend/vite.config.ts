import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import fs from "node:fs";
import path from "node:path";

function readHttps(): { key: Buffer; cert: Buffer } | undefined {
  const cert = process.env.NAVIER_SSL_CERT ?? path.resolve(__dirname, "certs/cert.pem");
  const key = process.env.NAVIER_SSL_KEY ?? path.resolve(__dirname, "certs/key.pem");
  try {
    if (fs.existsSync(cert) && fs.existsSync(key)) {
      return { cert: fs.readFileSync(cert), key: fs.readFileSync(key) };
    }
  } catch {
  }
  return undefined;
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    host: true,
    https: readHttps(),
    proxy: {
      "/api": { target: "http://localhost:5700", changeOrigin: true },
      "/ws": { target: "ws://localhost:5700", ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "../backend/app/static_dist",
    emptyOutDir: true,
  },
});
