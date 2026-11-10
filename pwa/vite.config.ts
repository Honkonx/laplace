/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// PWA de Laplace — proyecto Vite independiente, sibling de frontend/ (no depende de él).
// Puerto 9003 (cambiado 2026-09-10 de 5174 — frontend/ pasó a 9002, mismo pedido del usuario
// de puertos arriba de 9000, ver scritp/iniciar-pwa.bat) para poder correr ambos dev servers a
// la vez sin choque. Ya agregado a CORS_ORIGINS del .env real del backend.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 9003,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
