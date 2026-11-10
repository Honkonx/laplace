"""web_estatico.py — sirve la web compilada (`frontend/dist`) desde el propio backend, en el mismo puerto.

Por qué: en la instalación portable no hay Node. El instalador (o el empaquetador) deja `frontend/dist` compilado y el backend lo
entrega, de modo que `http://127.0.0.1:9001/` abre la web y la API vive en el mismo origen (sin CORS ni dirección de API que
configurar). En desarrollo se sigue usando `pnpm dev` (puerto 9002) y esto no hace nada si no existe `frontend/dist/index.html`.

Cómo: no agrega una ruta comodín (que convertiría un POST a una ruta inexistente en 405); intercepta el 404 de un GET que no es de
la API y entrega el archivo estático o, si es una ruta de la SPA (/historial, /agente…), el `index.html`.

Reglas (`deploy-safety.md`, sección Service Worker): `index.html`, `sw.js` y `manifest.json` nunca se cachean (`no-cache`) para que
nadie quede pegado a una versión vieja; los archivos con hash en `assets/` sí, por un año. Las rutas de la API (`/api/...`,
`/health`, `/docs`, `/openapi.json`…) nunca caen en el `index.html`: un 404 de la API sigue siendo un 404 en JSON.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

PREFIJOS_RESERVADOS = ("api/", "health", "docs", "redoc", "openapi.json", "webhook/", "capabilities", "dependencies/")
SIN_CACHE = {"Cache-Control": "no-cache"}
CACHE_LARGO = {"Cache-Control": "public, max-age=31536000, immutable"}
ARCHIVOS_SIN_CACHE = {"index.html", "sw.js", "manifest.json", "registerSW.js"}


def directorio_web(raiz: Path) -> Path | None:
    dist = raiz / "frontend" / "dist"
    return dist if (dist / "index.html").is_file() else None


def _cabeceras(ruta_relativa: str) -> dict[str, str]:
    if ruta_relativa.startswith("assets/"):
        return CACHE_LARGO
    if ruta_relativa in ARCHIVOS_SIN_CACHE or ruta_relativa.endswith(".html"):
        return SIN_CACHE
    return {"Cache-Control": "public, max-age=3600"}


def _es_reservada(ruta: str) -> bool:
    return any(ruta == p.rstrip("/") or ruta.startswith(p) for p in PREFIJOS_RESERVADOS)


def respuesta_web(base: Path, ruta: str) -> Response | None:
    """Archivo estático, `index.html` para una ruta de la SPA, o None si no corresponde a la web (404 real)."""
    if _es_reservada(ruta):
        return None
    candidato = (base / ruta).resolve() if ruta else base / "index.html"
    # Nunca salir de `frontend/dist` (../ o rutas absolutas).
    if candidato != base and base not in candidato.parents:
        return None
    if candidato.is_file():
        return FileResponse(candidato, headers=_cabeceras(candidato.relative_to(base).as_posix()))
    if Path(ruta).suffix:  # un archivo con extensión que no existe es un 404, no una ruta de la SPA
        return None
    return FileResponse(base / "index.html", headers=SIN_CACHE)


def montar_web(app: FastAPI, raiz: Path) -> bool:
    """Devuelve False (y no cambia nada) si no hay `frontend/dist/index.html`."""
    dist = directorio_web(raiz)
    if dist is None:
        return False
    base = dist.resolve()

    @app.exception_handler(StarletteHTTPException)
    async def _manejar_404(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and request.method == "GET":
            respuesta = respuesta_web(base, request.url.path.lstrip("/"))
            if respuesta is not None:
                return respuesta
        return await http_exception_handler(request, exc)

    return True
