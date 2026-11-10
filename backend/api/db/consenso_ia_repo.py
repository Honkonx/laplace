"""
db/consenso_ia_repo.py — Consenso "N usuarios validan el mismo pick de IA" (2026-09-09).

Mecanismo NUEVO, distinto de `db/analisis_repo.py::activar_cache_consenso` (esa es TTL+
max_usos sobre filas de `AnalisisIndividual`, sin distinguir si dos análisis vinieron del
mismo usuario dos veces o de dos usuarios distintos). Acá el pedido es específico: cuando 2
usuarios DISTINTOS piden análisis del mismo partido y la IA da el mismo pick, ese resultado
queda "validado" y se sirve cacheado sin volver a llamar al proveedor de IA real — hasta que
expire (TTL 12h, ver `HORAS_TTL_DEFAULT`).

Este mecanismo AHORRA llamadas reales a la IA (que tienen costo/cuota) — nunca las agrega. El
caller (`services/analisis_completo.py::procesar_job`) es responsable de:
  1. Llamar `leer_validado()` ANTES de invocar al proveedor de IA — si hay un resultado
     vigente, usarlo y no llamar a la IA.
  2. Si no hay resultado vigente, llamar a la IA real y después `registrar_resultado_ia()`
     con el pick obtenido — esta función decide si el resultado queda como candidato nuevo,
     confirma (valida) un candidato previo de otro usuario, o reemplaza un candidato que
     divergía.

Diseño deliberadamente simple (una fila por partido_id, no una tabla de detalle de "quién
confirmó qué") — alcanza para el umbral pedido (2 usuarios distintos) sin la complejidad de
trackear N confirmaciones arbitrarias que el pedido no requiere.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.predicciones import ConsensoIaValidacion

log = logging.getLogger("laplace.consenso_ia")

HORAS_TTL_DEFAULT = 12
PICKS_SIN_SENAL = ("indeterminado", "")


def _now_str() -> str:
    """`creado_en`/`actualizado_en`/`expira_en` — normalizado a UTC 2026-09-09 (ver docstring
    de `jobs_repo._now_str`). Tabla nueva de esta misma ronda (sin filas previas a UTC)."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def leer_validado(db: Session, partido_id: str) -> dict | None:
    """Devuelve el resultado de IA ya validado (2+ usuarios distintos coincidieron) y vigente
    para este partido, o None si no hay uno — en cuyo caso el caller debe llamar a la IA real.
    """
    fila = db.get(ConsensoIaValidacion, partido_id)
    if fila is None or not fila.validado or fila.expira_en <= _now_str():
        return None
    return {
        "pick_ia": fila.pick_ia,
        "confianza_ia": fila.confianza_ia,
        "score_ia": fila.score_ia,
        "texto_ia": fila.texto_ia,
        "usuarios_confirmaron": fila.usuarios_confirmaron,
    }


def registrar_resultado_ia(
    db: Session,
    partido_id: str,
    pick_ia: str,
    confianza_ia: str | None,
    score_ia: int | None,
    texto_ia: str,
    usuario_id: str,
    horas_ttl: int = HORAS_TTL_DEFAULT,
) -> dict:
    """Registra un resultado de IA recién generado (llamada real ya hecha) como evidencia del
    consenso N-usuarios. Devuelve {"validado": bool, "usuarios_confirmaron": int, "motivo": str}.

    Reglas (ver docstring del módulo para el contrato completo):
    - Pick "Indeterminado"/vacío: no aporta señal, no se registra (no contamina el candidato).
    - Sin candidato vigente (no existe o expiró): se guarda como candidato nuevo (1 usuario).
    - Candidato vigente del MISMO usuario: se refresca (evidencia más reciente), no cuenta
      como confirmación distinta — un mismo usuario no puede "validarse a sí mismo".
    - Candidato vigente de OTRO usuario con el MISMO pick: se valida (2 usuarios distintos
      coincidieron) — a partir de acá `leer_validado()` sirve esto sin llamar a la IA.
    - Candidato vigente de otro usuario con pick DISTINTO: el candidato se reemplaza por este
      (evidencia más reciente gana; no se acumulan picks divergentes en una sola fila).
    """
    if not usuario_id:
        usuario_id = "desconocido"
    if (pick_ia or "").strip().lower() in PICKS_SIN_SENAL:
        return {"validado": False, "usuarios_confirmaron": 0, "motivo": "pick_sin_senal_no_registrado"}

    ahora_str = _now_str()
    expira = (utc_ahora() + timedelta(hours=horas_ttl)).strftime("%Y-%m-%d %H:%M:%S")

    fila = db.get(ConsensoIaValidacion, partido_id)
    vigente = fila is not None and fila.expira_en > ahora_str

    if not vigente:
        if fila is None:
            fila = ConsensoIaValidacion(partido_id=partido_id)
            db.add(fila)
            fila.creado_en = ahora_str
        else:
            # Candidato/validación expirada — reinicia el ciclo con este resultado.
            fila.creado_en = ahora_str
        fila.pick_ia = pick_ia
        fila.confianza_ia = confianza_ia
        fila.score_ia = score_ia
        fila.texto_ia = texto_ia
        fila.primer_usuario_id = usuario_id
        fila.segundo_usuario_id = None
        fila.usuarios_confirmaron = 1
        fila.validado = 0
        fila.actualizado_en = ahora_str
        fila.expira_en = expira
        db.commit()
        return {"validado": False, "usuarios_confirmaron": 1, "motivo": "candidato_nuevo"}

    if fila.validado:
        # Defensivo: en el flujo normal `leer_validado()` ya evita que se llegue a llamar a
        # la IA (y por lo tanto a esta función) cuando ya hay un resultado validado vigente.
        return {"validado": True, "usuarios_confirmaron": fila.usuarios_confirmaron, "motivo": "ya_validado"}

    if fila.primer_usuario_id == usuario_id:
        fila.pick_ia = pick_ia
        fila.confianza_ia = confianza_ia
        fila.score_ia = score_ia
        fila.texto_ia = texto_ia
        fila.actualizado_en = ahora_str
        db.commit()
        return {"validado": False, "usuarios_confirmaron": 1, "motivo": "mismo_usuario_no_valida"}

    if fila.pick_ia == pick_ia:
        fila.segundo_usuario_id = usuario_id
        fila.usuarios_confirmaron = 2
        fila.validado = 1
        fila.actualizado_en = ahora_str
        fila.expira_en = expira
        db.commit()
        log.info(
            "consenso_ia validado partido_id=%s pick=%s usuarios=%s,%s",
            partido_id, pick_ia, fila.primer_usuario_id, usuario_id,
        )
        return {"validado": True, "usuarios_confirmaron": 2, "motivo": "coincide_segundo_usuario"}

    # Usuario distinto, pero el pick diverge del candidato previo — no hay consenso todavía,
    # el candidato se reemplaza por la evidencia más reciente.
    fila.pick_ia = pick_ia
    fila.confianza_ia = confianza_ia
    fila.score_ia = score_ia
    fila.texto_ia = texto_ia
    fila.primer_usuario_id = usuario_id
    fila.segundo_usuario_id = None
    fila.usuarios_confirmaron = 1
    fila.validado = 0
    fila.actualizado_en = ahora_str
    fila.expira_en = expira
    db.commit()
    return {"validado": False, "usuarios_confirmaron": 1, "motivo": "pick_diverge_reemplaza_candidato"}
