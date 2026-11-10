"""routers/prediccion_web.py — Endpoint público de análisis completo, para `frontend/` (web).

`routers/deportivo.py::POST /api/v1/analisis` (Parte 1) espera que el CALLER ya le mande
`pos_local`/`odds_local`/`h2h_*` calculados — sirve para uso interno (bot/app ya hacen ese
enriquecimiento vía `services/analisis_completo.py` antes de llamar al motor). La web no tiene
esos datos: solo conoce `match_id`/`local`/`visitante`/`liga`/`fecha` desde `/api/v1/partidos`.
Este endpoint corre el MISMO pipeline de enriquecimiento que ya usa el bot/app
(`analisis_completo._enriquecer_partido`, standings+odds+H2H reales) pero de forma síncrona
(sin job en background, sin IA — solo el motor estadístico Poisson/Dixon-Coles+consenso, más
rápido y sin costo de proveedores de IA para un caso de uso de "mostrar la predicción en la
web"), y devuelve el resultado completo en la misma request.

2026-09-09 — rate limit agregado (hallazgo de auditoría: este endpoint corre el enriquecimiento
completo — standings+odds+H2H reales contra APIs externas — sin ningún límite, público, sin
auth). `15/minute` por IP, mismo mecanismo que `/auth/login`/`/registro`
(`core/rate_limit.py::limitar`) — deja margen real de uso normal (varios partidos consultados
seguidos) sin permitir automatizar un abuso de cuota de las APIs externas que paga el proyecto.
"""
from __future__ import annotations

import httpx
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.core.rate_limit import limitar
from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.db.session import get_db
from backend.api.models.predicciones import HistorialPrediccionWeb
from backend.api.services import modelo_historico
from backend.api.services.analisis_completo import _enriquecer_partido as _pipeline_enriquecer_partido
from backend.api.services.analisis_completo import analizar_y_persistir

router = APIRouter(prefix="/api/v1", tags=["prediccion-web"])


async def _enriquecer_partido(db: Session, client: httpx.AsyncClient, partido: dict, match_id: str, fecha: str) -> dict:
    """Punto de extension compatible para pruebas y consumidores del endpoint web."""
    return await _pipeline_enriquecer_partido(db, client, partido, match_id, fecha)


class PrediccionWebInput(BaseModel):
    match_id: str
    local: str
    visitante: str
    liga: str
    fecha: str  # yyyyMMdd, mismo formato que /api/v1/partidos


@router.post("/prediccion-web")
@limitar("15/minute")
async def prediccion_web(request: Request, body: PrediccionWebInput, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Análisis estadístico completo (sin IA) para un partido, listo para mostrar en la web.
    Mismo motor que usa el bot/app — mismos números, no una versión simplificada aparte."""
    async with httpx.AsyncClient() as client:
        partido = {"local": body.local, "visitante": body.visitante, "liga": body.liga}
        enriquecido = await _enriquecer_partido(db, client, partido, body.match_id, body.fecha)
        persisted = await analizar_y_persistir(db, client, match_id=body.match_id, local=body.local, visitante=body.visitante, liga=body.liga, fecha=body.fecha, con_ia=False, usuario_id=usuario["sub"], datos_enriquecidos=enriquecido)
        resultado = persisted["resultado_motor"]
        resultado["resumen_estadistico"] = persisted["resumen_estadistico"]
        resultado["standings_info"] = persisted["standings_info"]
        resultado["odds_info"] = persisted["odds_info"]
        resultado["h2h_resumen"] = persisted["h2h_resumen"]
        # Tasa base real de la liga (solo si ambos equipos se reconocen en el histórico): contexto honesto
        # para leer la probabilidad. None cuando no hay cobertura; la interfaz no debe inventarla.
        resultado["tasa_base_liga"] = modelo_historico.resumen_tasa_base(
            {"liga": body.liga, "local": body.local, "visitante": body.visitante})
        consenso = resultado.get("consenso", {})
        db.add(HistorialPrediccionWeb(user_id=usuario["sub"], partido_id=body.match_id, fecha=body.fecha, liga=body.liga, local=body.local, visitante=body.visitante, pick=consenso.get("pick_final"), confianza=consenso.get("confianza_final"), resultado_json=json.dumps(resultado, ensure_ascii=False), creado_en=datetime.now(timezone.utc).isoformat()))
        db.commit()
        return resultado
