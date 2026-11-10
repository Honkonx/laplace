// Registro del Service Worker (public/sw.js) — separado de main.tsx para poder testear/omitir
// fácil. Se registra recién después del evento `load` para no competir por ancho de banda con
// la carga inicial real de la página (patrón estándar, no específico de este proyecto).
export function registrarServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (import.meta.env.DEV) return; // en dev, Vite ya sirve todo en caliente — un SW solo estorba

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.error("No se pudo registrar el service worker:", err);
    });
  });
}
