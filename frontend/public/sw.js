// Service Worker de Laplace PWA.
//
// REGLA DURA (.claude/rules/deploy-safety.md): la navegación (index.html) NUNCA es cache-first
// — siempre network-first, con el cache como respaldo SOLO si la red falla (offline). Sin esto
// un usuario puede quedar pegado a una versión vieja del sitio indefinidamente sin ningún error
// visible. cache-first es seguro únicamente para assets con hash en el nombre (JS/CSS que
// genera Vite en /assets/*, ej. index-a1b2c3d4.js) — esos SÍ pueden ser cache-first porque un
// build nuevo genera un nombre de archivo distinto, nunca pisa el viejo.
//
// Nota de despliegue: si en el futuro esto se sirve tras un CDN/Cloudflare, forzar
// `Cache-Control: no-cache` en la respuesta de ESTE archivo (sw.js) — si el CDN lo cachea con
// un TTL de archivo estático por defecto, un navegador puede quedar corriendo un service worker
// viejo sin enterarse nunca de que hay uno nuevo. No se configuró un `_headers`/CDN acá porque
// todavía no existe hosting real para la PWA (ver reporte de esta ronda).

const CACHE_VERSION = "laplace-pwa-v1";
const OFFLINE_SHELL_CACHE = `${CACHE_VERSION}-shell`;
const ASSET_CACHE = `${CACHE_VERSION}-assets`;

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(OFFLINE_SHELL_CACHE).then((cache) => cache.addAll(["/"])),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("laplace-pwa-") && key !== OFFLINE_SHELL_CACHE && key !== ASSET_CACHE)
          .map((key) => caches.delete(key)),
      ),
    ),
  );
  self.clients.claim();
});

function esNavegacion(request) {
  return request.mode === "navigate" || (request.method === "GET" && request.headers.get("accept")?.includes("text/html"));
}

function esAssetConHash(url) {
  // Vite emite JS/CSS versionados bajo /assets/ con hash en el nombre — esos son los únicos
  // seguros para cache-first (un build nuevo nunca reutiliza el mismo nombre de archivo).
  return url.pathname.startsWith("/assets/");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // nunca interceptar el backend/API externo

  if (esNavegacion(request)) {
    // Network-first: la red real manda siempre que esté disponible. El cache es solo un
    // respaldo offline — nunca la fuente primaria para la navegación.
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(OFFLINE_SHELL_CACHE).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/").then((cached) => cached ?? Response.error())),
    );
    return;
  }

  if (esAssetConHash(url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          const copy = response.clone();
          caches.open(ASSET_CACHE).then((cache) => cache.put(request, copy));
          return response;
        });
      }),
    );
  }
  // Todo lo demás (manifest.json, íconos, /api/* si algún día se sirviera del mismo origen):
  // sin manejar acá — pasa directo a la red, comportamiento normal del navegador.
});
