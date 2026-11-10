/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// SPA pura, sin SSR — el backend real (FastAPI, backend/api/) es el único que tiene lógica
// de negocio. Puerto 9002 (cambiado 2026-09-10 de 5173 — el usuario pidió puertos arriba de
// 9000 para no chocar con otros proyectos locales, ver scritp/iniciar-web.bat) ya está
// agregado a CORS_ORIGINS en el .env real.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 9002,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
