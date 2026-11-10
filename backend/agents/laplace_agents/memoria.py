"""laplace_agents/memoria.py — memoria propia del agente, separada de las tablas compartidas
que el resto de `core.py` ya escribe (`analisis_comparativo`, vía `USUARIO_SISTEMA`). Persiste
en `LaplaceAgentMemoria` (`backend/api/models/laplace_agents.py` — migración `e0b8b0bd13dd`
aplicada y verificada contra la BD real 2026-09-10).

Uso real (`core.py`): un evento por corrida (`tipo_evento="ciclo_diario"`) con la distribución
de picks de esa corrida, para que `laplace_agents/deriva.py` pueda comparar la corrida actual
contra la última registrada — y un evento `tipo_evento="deriva_detectada"` cuando esa
comparación dispara una alerta real. `resumen` viaja como dict y se serializa a JSON acá adentro
(el caller no arma el JSON a mano)."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from backend.api.models.laplace_agents import LaplaceAgentMemoria


def _now_str() -> str:
    """UTC — mismo patrón que el resto de `db/*_repo.py` del backend (ver docstring de
    `jobs_repo._now_str`/`analisis_repo._now_str`)."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def guardar_evento(db: Session, tipo_evento: str, resumen: dict, fecha: str | None = None) -> dict:
    """`fecha` — día de negocio del evento (ej. el día de fixtures que procesó la corrida); por
    default hoy (hora local, mismo criterio que `AnalisisComparativo.fecha`). Nunca lanza hacia
    afuera de una corrida por un fallo de memoria — la llama el caller dentro de su propio try
    si hiciera falta, esta función en sí no agrega manejo especial porque un fallo de escritura
    acá (ej. BD bloqueada) debe verse, no esconderse silenciosamente."""
    fecha_evento = fecha or datetime.now().strftime("%Y-%m-%d")
    fila = LaplaceAgentMemoria(
        fecha=fecha_evento,
        tipo_evento=tipo_evento,
        resumen=json.dumps(resumen, ensure_ascii=False),
        creado_en=_now_str(),
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return {"id": fila.id, "fecha": fila.fecha, "tipo_evento": fila.tipo_evento}


def leer_ultimo_evento(db: Session, tipo_evento: str) -> dict | None:
    """Última fila real de este `tipo_evento` (por `id` descendente — equivalente a
    `creado_en` descendente porque una fila nunca se edita después de insertarse), con
    `resumen` ya deserializado de JSON. `None` si todavía no hay ninguna fila de este tipo
    (primera corrida real del agente, o memoria vacía en un entorno nuevo)."""
    fila = (
        db.query(LaplaceAgentMemoria)
        .filter(LaplaceAgentMemoria.tipo_evento == tipo_evento)
        .order_by(LaplaceAgentMemoria.id.desc())
        .first()
    )
    if fila is None:
        return None
    try:
        resumen = json.loads(fila.resumen)
    except (TypeError, ValueError):
        resumen = {}
    return {
        "id": fila.id, "fecha": fila.fecha, "tipo_evento": fila.tipo_evento,
        "resumen": resumen, "creado_en": fila.creado_en,
    }
