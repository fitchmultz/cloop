/**
 * vite.config.ts - Frontend dev/build configuration for the Vite + TypeScript cutover.
 *
 * Purpose:
 *   Configure local development, production bundle output, and test execution for
 *   the Cloop frontend workspace.
 *
 * Responsibilities:
 *   - Run the Vite dev server with FastAPI API proxying.
 *   - Emit production assets into src/cloop/static/dist for packaged serving.
 *   - Copy root-level public assets (manifest, favicon, service worker) into dist.
 *   - Hash app assets while keeping production output package-friendly.
 *   - Configure Vitest for frontend-local checks.
 *
 * Scope:
 *   - Frontend-only build/test/dev configuration.
 *
 * Usage:
 *   - pnpm --dir frontend dev
 *   - pnpm --dir frontend build
 *   - pnpm --dir frontend test
 *
 * Invariants/Assumptions:
 *   - Production bundle output lives in src/cloop/static/dist.
 *   - Built app assets are served from /static/assets/*.
 *   - Root PWA files (/, /manifest.json, /favicon.ico, /sw.js) are served by FastAPI.
 */

import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

const backendUrl = process.env["CLOOP_BACKEND_URL"] ?? "http://127.0.0.1:8000";
const distDir = resolve(__dirname, "../src/cloop/static/dist");

export default defineConfig(({ command }) => ({
  base: command === "serve" ? "/" : "/static/",
  publicDir: resolve(__dirname, "public"),
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "^/(health|healthz|loops|chat|memory|ask|ingest|openapi\\.json)(/.*)?$": {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: distDir,
    emptyOutDir: true,
    sourcemap: true,
    assetsDir: "assets",
    manifest: "asset-manifest.json",
    rollupOptions: {
      input: resolve(__dirname, "index.html"),
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    restoreMocks: true,
    include: ["src/**/*.test.ts"],
  },
}));
