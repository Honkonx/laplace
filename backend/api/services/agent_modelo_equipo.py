"""services/agent_modelo_equipo.py — lo que el modelo sabe de un equipo, dicho por el agente (MP-4 del plan `11_PLAN_MODELO_PREDICTIVO…`).

Usa la memoria compartida (`ml_estado_vivo`, vía `ml/laplace/auditoria.memoria_equipo`). Es un accesorio del perfil de equipo: si falta el modelo, la base o el equipo, devuelve texto vacío y el perfil sale
como siempre. Nunca da una probabilidad: son datos de la memoria del modelo (rating, goles, forma, partidos) con su origen y fecha.
"""
from __future__ import annotations

import json
import logging
import time
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("laplace.agente_modelo_equipo")
TTL_INDICE_SEGUNDOS = 600
MIN_LETRAS = 4
_indice: dict[int, tuple[float, dict[str, list[tuple[str, str, int]]]]] = {}


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).casefold().strip()


def limpiar_cache() -> None:
    _indice.clear()


def _construir_indice(db: Session, modelo_id: int) -> dict[str, list[tuple[str, str, int]]]:
    """{nombre sin acentos: [(liga, nombre, partidos)]}: un mismo equipo figura en su liga y en las copas (Libertadores, Champions…), cada una con sus partidos."""
    from backend.api.models.ml_modelo import MlEstadoVivo  # noqa: PLC0415

    indice: dict[str, list[tuple[str, str, int]]] = {}
    for fila in db.scalars(select(MlEstadoVivo).where(MlEstadoVivo.modelo_id == modelo_id)):
        estado = json.loads(fila.estado_json)
        partidos = estado.get("n") or {}
        for nombre in (estado.get("elo") or {}):
            indice.setdefault(_plano(nombre), []).append((fila.liga, nombre, int(partidos.get(nombre, 0))))
    return indice


def _mejor(entradas: list[tuple[str, str, int]]) -> tuple[str, str]:
    """De las competiciones en las que figura, la de más partidos (la liga, no la copa)."""
    liga, nombre, _ = max(entradas, key=lambda e: e[2])
    return liga, nombre


def _buscar(indice: dict[str, list[tuple[str, str, int]]], nombre: str) -> tuple[str, str] | None:
    """El equipo con ese nombre (exacto sin acentos; si no, un único nombre que lo contenga, de al menos `MIN_LETRAS`). Con dos nombres distintos que cuadran («Barcelona» y «Barcelona SC») es ambiguo: None."""
    buscado = _plano(nombre)
    if len(buscado) < MIN_LETRAS:
        return None
    if buscado in indice:
        return _mejor(indice[buscado])
    nombres = {k for k in indice if len(k) >= MIN_LETRAS and (buscado in k or k in buscado)}
    return _mejor(indice[next(iter(nombres))]) if len(nombres) == 1 else None


def linea_de_equipo(db: Session, nombre: str) -> str:
    """«\\nMemoria del modelo: …» para añadir al perfil de un equipo, o «» si no hay nada que decir."""
    try:
        from backend.api.ml.laplace import auditoria, registro  # noqa: PLC0415

        modelo = registro.modelo_vigente(db)
        if modelo is None:
            return ""
        marca, indice = _indice.get(modelo.id, (0.0, {}))
        if not indice or time.monotonic() - marca > TTL_INDICE_SEGUNDOS:
            indice = _construir_indice(db, modelo.id)
            _indice[modelo.id] = (time.monotonic(), indice)
        encontrado = _buscar(indice, nombre)
        if encontrado is None:
            return ""
        m = auditoria.memoria_equipo(db, modelo, encontrado[0], encontrado[1])
        if m is None:
            return ""
        fiabilidad = " (pocos partidos: poco fiable)" if m["fiabilidad"] == "baja" else ""
        return (f"\nMemoria del modelo: rating {m['rating_elo']:.0f}, marca {m['goles_a_favor']:.2f} y recibe {m['goles_en_contra']:.2f} goles por partido, "
                f"forma {m['forma_puntos_por_partido']:.2f} puntos por partido, {m['partidos']} partidos en memoria{fiabilidad}; actualizado {str(m['actualizado_en'])[:10]}.")
    except Exception:  # noqa: BLE001 — accesorio: el perfil nunca falla por esto
        db.rollback()
        log.warning("no se pudo leer la memoria del modelo para %s", nombre, exc_info=True)
        return ""
