"""ml/laplace/estado_vivo.py — la memoria del modelo en la base: el estado por equipo (Elo, tasas de gol, forma, tiros) de cada liga, al día.

Antes el estado vivía solo dentro del artefacto en disco y se reconstruía el domingo en el reentreno: entre un domingo y otro el modelo no veía los resultados nuevos y un equipo recién ascendido (sin historia
en el maestro) quedaba «sin historial» para siempre. Ahora, cada día, `reconstruir` repite TODO el historial de cada liga (maestro + capa en vivo + capa actual) con los hiperparámetros del modelo activo y guarda el
resultado en `ml_estado_vivo`; el servicio lo usa por encima del estado del artefacto. Los PESOS siguen siendo los del artefacto (solo el reentreno los cambia).

Se reconstruye en vez de actualizar de forma incremental porque es exactamente la misma recurrencia que el entrenamiento (`entrenamiento.recorrer`): no puede divergir, recoge correcciones de resultados y trae la historia
completa de los recién llegados. Todo lo accesorio es a prueba de fallos: sin la tabla o con un error, el servicio sigue con el estado del artefacto.
"""
from __future__ import annotations

import json
import logging
import time
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.api.ml import datos
from backend.api.ml.laplace import entrenamiento, registro
from backend.api.models.ml_modelo import MlEstadoVivo

log = logging.getLogger("laplace.estado_vivo")

TTL_CACHE_SEGUNDOS = 120
_cache: dict[int, tuple[float, dict[str, entrenamiento.EstadoLiga]]] = {}


def plano(texto: str) -> str:
    """Sin acentos y con espacios normales: «São Bernardo» → «Sao Bernardo» (el nombre con el que entran los equipos nuevos)."""
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).split())


def limpiar_cache() -> None:
    _cache.clear()


def reconstruir(db: Session, partidos: list[dict] | None = None) -> dict:
    """Reconstruye y guarda el estado de cada liga del modelo activo. Devuelve `{ok, modelo_id, ligas, partidos, equipos_nuevos}` o `{ok: False, motivo}`."""
    modelo = registro.modelo_vigente(db)
    if modelo is None:
        return {"ok": False, "motivo": "no hay un modelo Laplace activo"}
    art = registro.cargar_artefacto(modelo)
    if art is None or art.get("familia") != entrenamiento.FAMILIA_JERARQUICA:
        return {"ok": False, "motivo": "el artefacto del modelo falta o no es jerárquico"}
    if partidos is None:
        partidos, _ = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    hiper = art.get("hiper") or {}
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    existentes = {f.liga: f for f in db.scalars(select(MlEstadoVivo).where(MlEstadoVivo.modelo_id == modelo.id))}
    ligas = total = nuevos = 0
    for codigo, info in art["ligas"].items():
        ps = por_liga.get(codigo)
        if not ps:
            continue
        _, estado = entrenamiento.recorrer(ps, hiper)
        nuevos += len(set(estado.elo) - set((info.get("estado") or {}).get("elo", {})))
        fila = existentes.get(codigo) or MlEstadoVivo(modelo_id=modelo.id, liga=codigo)
        fila.estado_json = json.dumps(estado.a_dict(), separators=(",", ":"))
        fila.hasta_dia = max(p["dia"] for p in ps)
        fila.partidos = len(ps)
        fila.actualizado_en = ahora
        db.add(fila)
        ligas += 1
        total += len(ps)
    db.execute(delete(MlEstadoVivo).where(MlEstadoVivo.modelo_id != modelo.id))  # los estados de modelos anteriores ya no sirven
    db.commit()
    limpiar_cache()
    return {"ok": True, "modelo_id": modelo.id, "ligas": ligas, "partidos": total, "equipos_nuevos": nuevos}


def estado_de(modelo_id: int | None, liga: str) -> entrenamiento.EstadoLiga | None:
    """Estado al día de una liga para el modelo `modelo_id`, o None (sin tabla, sin filas o con cualquier error: el servicio usa entonces el del artefacto). Con caché de unos minutos."""
    if modelo_id is None:
        return None
    try:
        t, mapa = _cache.get(modelo_id, (0.0, None))
        if mapa is None or time.monotonic() - t > TTL_CACHE_SEGUNDOS:
            from backend.api.db.session import SessionLocal

            with SessionLocal() as db:
                filas = db.scalars(select(MlEstadoVivo).where(MlEstadoVivo.modelo_id == modelo_id)).all()
                mapa = {f.liga: entrenamiento.EstadoLiga.de_dict(json.loads(f.estado_json)) for f in filas}
            _cache[modelo_id] = (time.monotonic(), mapa)
        return mapa.get(liga)
    except Exception as exc:  # noqa: BLE001 — accesorio: nunca rompe un pronóstico
        log.warning("estado vivo no disponible: %s", exc)
        return None
