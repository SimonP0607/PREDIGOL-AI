// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

/**
 * The dev server also forwards the API, so the whole platform is ONE origin:
 * set VITE_API_BASE_URL to this server (http://localhost:5173) and the browser
 * never makes a cross-origin request. Embedded browsers that block requests to
 * a second local port, CORS and the API's own origin list stop mattering.
 * FBI_API_PROXY overrides where the API runs (default 127.0.0.1:8010).
 */
const API_TARGET = process.env["FBI_API_PROXY"] ?? "http://127.0.0.1:8010";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
  vite: {
    server: {
      proxy: {
        "/api/v1": { target: API_TARGET, changeOrigin: true },
        "/health": { target: API_TARGET, changeOrigin: true },
      },
    },
  },
});
