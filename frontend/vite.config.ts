import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

// The repo's .env lives one directory above frontend/, not inside it.
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

// A strict CSP (script-src 'self', no 'unsafe-inline') is only safe to ship in
// the production build. Vite's dev server injects an inline React Refresh
// script into index.html; a CSP there would block it and break HMR. So this
// meta tag is added only for `vite build`, which is what T7.13 checks.
const cspMetaPlugin: Plugin = {
  name: "lgac-csp-meta",
  apply: "build",
  transformIndexHtml() {
    return [
      {
        tag: "meta",
        attrs: {
          "http-equiv": "Content-Security-Policy",
          content:
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        },
        injectTo: "head-prepend",
      },
    ];
  },
};

export default defineConfig(({ mode }) => {
  // Third argument "" loads every variable, not just the VITE_-prefixed ones,
  // so the dev proxy can read API_TOKEN (plan §6.4). This value is only read
  // here, in the Node config process; `npm run build` never touches it.
  const env = loadEnv(mode, repoRoot, "");

  return {
    root: fileURLToPath(new URL(".", import.meta.url)),
    envDir: repoRoot,
    plugins: [react(), cspMetaPlugin],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              proxyReq.setHeader("X-API-Token", env.API_TOKEN ?? "");
            });
          },
        },
      },
    },
  };
});
