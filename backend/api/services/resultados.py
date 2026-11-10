"""
services/resultados.py — Verificación de resultados reales (BSD primero, api-football
fallback). Port de actualizar_resultados.py.

Cambios reales vs el original:
  - `sqlite3`/`urllib.request` → SQLAlchemy ORM + `httpx.AsyncClient` (async).
  - `ejecutar_db_query(...)` por subprocess (invalidar caché) → `db.partidos_repo` directo.
  - La lógica de negocio (BSD primero, merge con prioridad BSD, cálculo de over25_real/
    btts_real con umbral 0.55, `_pick_acerto`) es IDÉNTICA — no se recalibra nada acá.

Nota de `.claude/rules/database-safety.md`: esta función modifica varias filas en una sola
llamada (`analisis_comparativo`, `predicciones`, `partidos_dia` por cada fixture) — el alcance
ya está acotado por `fixture_ids` explícito (nunca "todos los pendientes sin filtro" salvo que
el caller lo pida deliberadamente vía `leer_pendientes_del_dia`), y es idempotente: reprocesar
el mismo fixture_id dos veces dos veces dos veces sobreescribe con el mismo resultado, no lo
duplica (usa `INSERT OR REPLACE`/UPDATE por id, no INSERT ciego).
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.config import settings
from backend.api.db import partidos_repo
from backend.api.models.predicciones import AnalisisComparativo, AnalisisModulo, Prediccion
from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.services.normalizacion import nombre_equipo_bsd, normalizar_nombre
from backend.api.services import laboratorio_pronosticos

log = logging.getLogger("laplace.resultados")

APIF_BASE = "https://v3.football.api-sports.io"
BSD_BASE = "https://sports.bzzoiro.com/api/v2"

STATUS_TERMINADOS = {"FT", "AET", "PEN"}
STATUS_CANCELADOS = {"CANC", "PST", "ABD", "AWD", "WO"}

OVER25_UMBRAL = 0.55


def _now() -> str:
    """`actualizado_en` (resultados_partidos) — normalizado a UTC 2026-09-09 (ver docstring de
    `db/jobs_repo.py::_now_str`). Filas anteriores a este commit pueden estar en hora local de
    Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def _pick_acerto(pick: str | None, ganador: str, local: str, visitante: str) -> bool:
    if not pick:
        return False
    p = pick.strip().lower()
    if ganador == "empate":
        return p in ("empate", "draw", "x")
    if ganador == "local":
        return p in (local.strip().lower(), "local")
    if ganador == "visitante":
        return p in (visitante.strip().lower(), "visitante")
    return False


async def _bsd_buscar_resultado(client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict | None:
    if not settings.BSD_API_KEY or not local or not fecha:
        return None
    team_q = local.strip()[:12]
    url = f"{BSD_BASE}/events/?team_name={team_q}&date_from={fecha}&date_to={fecha}&status=finished&limit=20"
    try:
        r = await client.get(url, headers={"Authorization": f"Token {settings.BSD_API_KEY}"}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("resultados: consulta BSD falló: %s", exc)
        return None

    resultados = data.get("results") or []
    norm_local = normalizar_nombre(local)
    norm_visit = normalizar_nombre(visitante)

    for ev in resultados:
        nombre_local_bsd = nombre_equipo_bsd(ev.get("home_team")) or local
        nombre_visit_bsd = nombre_equipo_bsd(ev.get("away_team")) or visitante
        hn = normalizar_nombre(nombre_local_bsd)
        an = normalizar_nombre(nombre_visit_bsd)
        if not ((norm_local[:6] in hn or hn[:6] in norm_local) and (norm_visit[:6] in an or an[:6] in norm_visit)):
            continue
        gl, gv = ev.get("home_score"), ev.get("away_score")
        if gl is None or gv is None:
            continue
        return {
            "status": "FT",
            "local": nombre_local_bsd,
            "visitante": nombre_visit_bsd,
            "liga": (ev.get("league") or {}).get("name", ""),
            "goles_local": int(gl),
            "goles_visitante": int(gv),
            "fecha": fecha,
        }
    return None


async def _consultar_fixtures_apifootball(client: httpx.AsyncClient, fixture_ids: list[str]) -> dict[str, dict]:
    if not settings.SPORTS_API_KEY or not fixture_ids:
        return {}
    resultados: dict[str, dict] = {}
    for i in range(0, len(fixture_ids), 20):
        lote = fixture_ids[i : i + 20]
        ids_str = "-".join(str(fid) for fid in lote)
        try:
            r = await client.get(
                f"{APIF_BASE}/fixtures?ids={ids_str}",
                headers={"x-apisports-key": settings.SPORTS_API_KEY},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("resultados: consulta api-football falló: %s", exc)
            continue
        for fixture in data.get("response", []):
            fid = str(fixture["fixture"]["id"])
            resultados[fid] = {
                "status": fixture["fixture"]["status"]["short"],
                "local": fixture["teams"]["home"]["name"],
                "visitante": fixture["teams"]["away"]["name"],
                "liga": fixture["league"]["name"],
                "goles_local": fixture["goals"]["home"],
                "goles_visitante": fixture["goals"]["away"],
                "fecha": fixture["fixture"]["date"][:10],
            }
    return resultados


def leer_pendientes_del_dia(db: Session, fecha: str) -> list[dict]:
    """Comparativos sin resultado_real todavía para una fecha — mismo criterio que
    `leer_pendientes_db` del original."""
    filas = (
        db.query(AnalisisComparativo)
        .filter(AnalisisComparativo.fecha == fecha, AnalisisComparativo.resultado_real.is_(None))
        .order_by(AnalisisComparativo.hora_kickoff.asc())
        .all()
    )
    return [
        {
            "fixture_id": f.partido_id,
            "local": f.local or "",
            "visitante": f.visitante or "",
            "liga": f.liga or "",
            "hora_kickoff": f.hora_kickoff or "",
        }
        for f in filas
    ]


def _guardar_resultado(db: Session, fixture_id: str, local: str, visitante: str, liga: str,
                        goles_local: int, goles_visitante: int, status_api: str, fecha_partido: str) -> dict:
    """Port de `guardar_resultado_db` — UPSERT en resultados_partidos, actualiza
    analisis_comparativo/predicciones/partidos_dia. Misma lógica de over25/btts (umbral 0.55)."""
    if goles_local > goles_visitante:
        ganador = "local"
    elif goles_visitante > goles_local:
        ganador = "visitante"
    else:
        ganador = "empate"

    resultado_str = f"{goles_local}-{goles_visitante}"
    ts = _now()

    existente = db.query(ResultadoPartido).filter(ResultadoPartido.fixture_id == fixture_id).first()
    if existente is None:
        db.add(
            ResultadoPartido(
                fixture_id=fixture_id, local=local, visitante=visitante, liga=liga,
                goles_local=goles_local, goles_visitante=goles_visitante, ganador=ganador,
                status_api=status_api, fecha_partido=fecha_partido, actualizado_en=ts,
            )
        )
    else:
        existente.local, existente.visitante, existente.liga = local, visitante, liga
        existente.goles_local, existente.goles_visitante, existente.ganador = goles_local, goles_visitante, ganador
        existente.status_api, existente.actualizado_en = status_api, ts

    filas_comp = (
        db.query(AnalisisComparativo)
        .filter(AnalisisComparativo.partido_id == fixture_id, AnalisisComparativo.resultado_real.is_(None))
        .all()
    )
    total_goles = goles_local + goles_visitante
    over25_real = 1 if total_goles > 2 else 0
    btts_real = 1 if (goles_local > 0 and goles_visitante > 0) else 0

    for fila in filas_comp:
        fila.resultado_real = resultado_str
        fila.goles_local = goles_local
        fila.goles_visitante = goles_visitante
        fila.status_partido = status_api
        fila.pick_correcto = 1 if _pick_acerto(fila.pick_final, ganador, local, visitante) else 0
        if fila.pick_python:
            fila.pick_python_correcto = 1 if _pick_acerto(fila.pick_python, ganador, local, visitante) else 0
        if fila.pick_claude:
            fila.pick_claude_correcto = 1 if _pick_acerto(fila.pick_claude, ganador, local, visitante) else 0
        if fila.pick_form:
            fila.pick_form_correcto = 1 if _pick_acerto(fila.pick_form, ganador, local, visitante) else 0

        fila.over25_real = over25_real
        fila.btts_real = btts_real
        if fila.over25_pred is not None:
            if fila.over25_pred >= OVER25_UMBRAL:
                fila.over25_correcto = 1 if over25_real == 1 else 0
            elif fila.over25_pred <= (1 - OVER25_UMBRAL):
                fila.over25_correcto = 1 if over25_real == 0 else 0
        if fila.btts_pred is not None:
            if fila.btts_pred >= OVER25_UMBRAL:
                fila.btts_correcto = 1 if btts_real == 1 else 0
            elif fila.btts_pred <= (1 - OVER25_UMBRAL):
                fila.btts_correcto = 1 if btts_real == 0 else 0

    # Mantener el track record granular alineado con el comparativo. Las filas de
    # `analisis_modulos` se crean al guardar el analisis y reciben el resultado cuando el
    # fixture termina; sin esta actualizacion los modulos quedaban inutilizables para
    # calibracion aunque el pick final ya estuviera verificado.
    filas_modulos = db.query(AnalisisModulo).filter(AnalisisModulo.partido_id == fixture_id).all()
    for fila in filas_modulos:
        if fila.pick:
            fila.pick_correcto = 1 if _pick_acerto(fila.pick, ganador, local, visitante) else 0

    filas_pred = db.query(Prediccion).filter(Prediccion.partido_id == fixture_id).all()
    for fila in filas_pred:
        fila.pick_correcto = 1 if _pick_acerto(fila.pick, ganador, local, visitante) else 0

    partido_dia = (
        db.query(PartidoDia)
        .filter(PartidoDia.match_id == fixture_id, PartidoDia.fecha == fecha_partido)
        .first()
    )
    if partido_dia is not None:
        partido_dia.status = "finished"
        partido_dia.goles_local = goles_local
        partido_dia.goles_visitante = goles_visitante
        partido_dia.cache_invalidado = 1

    experimentales_actualizados = laboratorio_pronosticos.evaluar_partido(
        db, partido_id=fixture_id, goles_local=goles_local, goles_visitante=goles_visitante,
    )

    db.commit()

    return {
        "fixture_id": fixture_id, "resultado": resultado_str, "ganador": ganador,
        "comparativos": len(filas_comp), "predicciones": len(filas_pred),
        "experimentales": experimentales_actualizados,
        "over25_real": over25_real, "btts_real": btts_real,
    }


async def actualizar_resultados(db: Session, client: httpx.AsyncClient, fixture_ids: list[str],
                                 fecha_consulta: str) -> dict:
    """Punto de entrada: BSD primero (sin cuota), api-football fallback. Igual que el
    `main()` del original, pero recibe `fixture_ids` explícito en vez de leerlos de argv."""
    pendientes_map = {p["fixture_id"]: p for p in leer_pendientes_del_dia(db, fecha_consulta)}
    for fid in fixture_ids:
        pendientes_map.setdefault(fid, {"fixture_id": fid, "local": "", "visitante": "", "hora_kickoff": ""})

    bsd_encontrados: dict[str, dict] = {}
    ids_para_apif: list[str] = []
    for fid in fixture_ids:
        p = pendientes_map.get(fid, {})
        if p.get("local") and p.get("visitante"):
            bsd_res = await _bsd_buscar_resultado(client, p["local"], p["visitante"], p.get("fecha", fecha_consulta))
            if bsd_res:
                bsd_encontrados[fid] = bsd_res
                continue
        ids_para_apif.append(fid)

    datos_apif = await _consultar_fixtures_apifootball(client, ids_para_apif) if ids_para_apif else {}
    datos_api = {**datos_apif, **bsd_encontrados}  # BSD tiene prioridad

    procesados = []
    for fid in fixture_ids:
        if fid not in datos_api:
            procesados.append({"fixture_id": fid, "estado": "sin_datos_api"})
            continue

        d = datos_api[fid]
        status = d["status"]
        if status in STATUS_CANCELADOS:
            for fila in db.query(AnalisisComparativo).filter(
                AnalisisComparativo.partido_id == fid, AnalisisComparativo.resultado_real.is_(None)
            ):
                fila.status_partido = status
                fila.resultado_real = "CANC"
            db.commit()
            partidos_repo.invalidar_partido_cache(db, d.get("fecha", fecha_consulta), fid)
            procesados.append({"fixture_id": fid, "estado": "cancelado", "status": status})
        elif status not in STATUS_TERMINADOS:
            procesados.append({"fixture_id": fid, "estado": "pendiente", "status": status})
        else:
            resultado = _guardar_resultado(
                db, fid, d["local"], d["visitante"], d["liga"],
                int(d["goles_local"] or 0), int(d["goles_visitante"] or 0), status, d["fecha"],
            )
            partidos_repo.invalidar_partido_cache(db, d["fecha"], fid)
            procesados.append({"fixture_id": fid, "estado": "actualizado", "resultado": resultado})

    resumen = {
        "total": len(procesados),
        "actualizados": sum(1 for p in procesados if p["estado"] == "actualizado"),
        "pendientes": sum(1 for p in procesados if p["estado"] == "pendiente"),
        "cancelados": sum(1 for p in procesados if p["estado"] == "cancelado"),
        "sin_datos": sum(1 for p in procesados if p["estado"] == "sin_datos_api"),
    }
    return {"fecha": fecha_consulta, "resumen": resumen, "detalle": procesados}
