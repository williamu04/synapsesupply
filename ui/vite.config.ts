import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: `npm run dev` proxies API routes to the SynapseSupply API on :8080.
// Prod: built with base "/console/" and served by the API; a separate host would set VITE_API_BASE.
const api = process.env.SYNAPSE_API ?? "http://localhost:8080";
const routes = ["/cases", "/requests", "/demo", "/recordings", "/health"];

export default defineConfig({
  base: "/console/",
  plugins: [react()],
  server: { proxy: Object.fromEntries(routes.map((r) => [r, { target: api, changeOrigin: true }])) },
  test: { environment: "node" },
});
