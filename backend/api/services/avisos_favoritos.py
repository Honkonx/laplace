"""services/avisos_favoritos.py — avisos de los favoritos (MB-34, ampliado por MS-4 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Solo a quien lo activó con `/avisos on` (o diciéndoselo al agente) y mantiene el consentimiento. Son trabajos DETERMINISTAS contra el calendario: sin IA en el bucle; el pronóstico sale del modelo y,
si el modelo no cubre el partido, el aviso sale sin pronóstico (nunca se inventa).
- `enviar_avisos`: «hoy juegan tus favoritos», con el pronóstico del modelo si lo hay. Un aviso por partido (`bot_avisos_enviados`), solo en horario activo, con tope por usuario, y en silencio si no hay nada nuevo.
- `enviar_resultados`: el final de los partidos que ya se avisaron, con el pronóstico que se mandó y si acertó.
Apagado por defecto (`AVISOS_FAVORITOS`); un máximo de `MAX_AVISOS_POR_EJECUCION` mensajes por corrida protege la cuota de Telegram. Si no se puede comprobar lo ya enviado (esquema atrasado) NO se envía nada:
sin esa comprobación un fallo repetiría el aviso cada día.
"""
from __future__ import annotations

import html
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db import bot_memoria_repo
from backend.api.models.bot_memoria import BotAvisoEnviado, BotPreferencias
from backend.api.models.partidos import ResultadoPartido
from backend.api.services import agent_perfil, planes_seguimiento, pronosticables, telegram_client

log = logging.getLogger("laplace.avisos")
MAX_AVISOS_POR_EJECUCION = 200
MAX_PARTIDOS_POR_AVISO = 5
VENTANA_RESULTADO = timedelta(days=3)
_NOMBRES = (("local", "Local"), ("empate", "Empate"), ("visitante", "Visitante"))
NOTA_ESTIMACION = "Estimaciones del modelo, no certezas ni consejos de apuesta."


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def _marca(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def en_horas_activas(ahora: datetime) -> bool:
    """Horario activo (hora de Chile) de `AVISOS_HORA_INICIO` a `AVISOS_HORA_FIN`."""
    return settings.AVISOS_HORA_INICIO <= ahora.hour < settings.AVISOS_HORA_FIN


async def enviar_por_canal(client: httpx.AsyncClient, chat_id: str, texto: str) -> bool:
    """Manda el aviso por el bot que dice `AVISOS_CANAL`: el del agente (si tiene token; es donde la persona sigue lo que sigue) o el bot deportivo."""
    token = settings.AGENT_TELEGRAM_BOT_TOKEN if settings.AVISOS_CANAL == "agente" and settings.AGENT_TELEGRAM_BOT_TOKEN else None
    return await telegram_client.enviar_mensaje(client, chat_id, texto, token=token)


def _linea_modelo(p: dict) -> str:
    return "Modelo: " + " · ".join(f"{etiqueta} {round(float(p[clave]) * 100)}%" for clave, etiqueta in _NOMBRES)


def texto_aviso(partidos: list[dict], pronosticos: dict[str, dict] | None = None, zona=None, fecha_iso: str = "") -> str:
    pronosticos = pronosticos or {}
    lineas, con_modelo = [], False
    for p in partidos[:MAX_PARTIDOS_POR_AVISO]:
        linea = f"• {html.escape(p['local'] or '?')} vs {html.escape(p['visitante'] or '?')}" + (f" ({html.escape(agent_perfil.hora_para(p['hora_chile'], fecha_iso, zona) or p['hora_chile'])})" if p.get("hora_chile") else "")
        if p.get("liga"):
            linea += f" · {html.escape(p['liga'])}"
        pron = pronosticos.get(p.get("match_id") or "")
        if pron:
            linea += f"\n   ↳ {_linea_modelo(pron)}"
            con_modelo = True
        lineas.append(linea)
    pie = f"\n\n{NOTA_ESTIMACION}" if con_modelo else ""
    return "⭐ <b>Hoy juegan tus favoritos</b>\n" + "\n".join(lineas) + pie + "\n\nPide el análisis con /juegos. Apaga los avisos con /avisos off."


def _resultado_1x2(gl: int, gv: int) -> str:
    return "local" if gl > gv else "visitante" if gv > gl else "empate"


def texto_resultado(items: list[tuple[BotAvisoEnviado, ResultadoPartido]]) -> str:
    lineas = []
    for aviso, res in items[:MAX_PARTIDOS_POR_AVISO]:
        linea = f"• {html.escape(res.local or '?')} {res.goles_local}-{res.goles_visitante} {html.escape(res.visitante or '?')}"
        if aviso.pronostico_json:
            p = json.loads(aviso.pronostico_json)
            pick = max(("local", "empate", "visitante"), key=lambda k: p[k])
            linea += f"\n   ↳ {_linea_modelo(p)} → " + ("acertó ✅" if pick == _resultado_1x2(res.goles_local, res.goles_visitante) else "no acertó ❌")
        lineas.append(linea)
    return "⭐ <b>Final de tus favoritos</b>\n" + "\n".join(lineas) + "\n\nApaga los avisos con /avisos off."


def pronostico_del_modelo(db: Session, partido: dict) -> dict | None:
    """Probabilidades 1X2 del modelo para un partido, o None si el modelo no lo cubre (ningún equipo con historia o sin modelo). Deja el pronóstico registrado en sombra para poder evaluarlo."""
    from backend.api.ml.laplace import servicio  # noqa: PLC0415

    salida = servicio.pronosticar_partido(db, {"local": partido.get("local") or "", "visitante": partido.get("visitante") or "", "liga": partido.get("liga") or "", "partido_id": partido.get("match_id")}, canal="agente")
    resumen = servicio.resumen_para_consumidores(salida)
    if not resumen or salida.get("fuente") == "referencia_de_liga":
        return None
    return resumen["p1x2"]


def _recientes(db: Session, ahora: datetime) -> list[BotAvisoEnviado]:
    return list(db.scalars(select(BotAvisoEnviado).where(BotAvisoEnviado.enviado_en >= _marca(ahora - VENTANA_RESULTADO))))


def _guardar(db: Session, uid: str, filas: list[tuple[str, str, str | None]], ahora: datetime) -> None:
    try:
        for partido_id, tipo, pron in filas:
            db.add(BotAvisoEnviado(user_id=uid, partido_id=partido_id, tipo=tipo, pronostico_json=pron, enviado_en=_marca(ahora)))
        db.commit()
    except Exception:  # noqa: BLE001 — una carrera con otra ejecución (clave única) no debe tumbar el resto
        db.rollback()
        log.warning("no se pudo registrar el aviso de %s", uid)


def _usados_24h(recientes: list[BotAvisoEnviado], ahora: datetime) -> dict[str, int]:
    corte, usados = _marca(ahora - timedelta(hours=24)), defaultdict(int)
    for r in recientes:
        if r.enviado_en >= corte:
            usados[r.user_id] += 1
    return usados


async def enviar_avisos(db: Session, client: httpx.AsyncClient, fecha_bd: str, enviar=enviar_por_canal, pronostico=None, ahora: datetime | None = None) -> dict:
    """Envía el aviso a cada usuario con favoritos que juegan en `fecha_bd` y que aún no lo recibió; devuelve cuántos se enviaron y cuántos fallaron.
    `pronostico(db, partido)` (p. ej. `pronostico_del_modelo`) añade las probabilidades del modelo; sin él, el aviso sale sin pronóstico. `ahora` (hora de Chile) activa el horario."""
    vacio = {"fecha": fecha_bd, "candidatos": 0, "enviados": 0, "fallidos": 0}
    if ahora is not None and not en_horas_activas(ahora):
        return {**vacio, "omitido": "fuera del horario de avisos"}
    try:
        partidos = pronosticables.listar_pronosticables(db, fecha_bd).get("partidos", [])
        por_usuario = bot_memoria_repo.avisos_del_dia(db, partidos)
    except Exception:  # noqa: BLE001 — la fuente de partidos caída: no se inventa nada
        db.rollback()
        log.exception("avisos: no se pudieron leer los partidos del día")
        return {**vacio, "omitido": "partidos no disponibles"}
    try:
        recientes = _recientes(db, _ahora_utc())
    except Exception:  # noqa: BLE001 — sin saber qué se envió, un reintento duplicaría el aviso cada día
        db.rollback()
        log.exception("avisos: no se pudo comprobar lo ya enviado; no se envía nada")
        return {**vacio, "omitido": "no se pudo comprobar lo ya enviado"}
    ya = {(r.user_id, r.partido_id) for r in recientes if r.tipo == "previo"}
    usados = _usados_24h(recientes, _ahora_utc())
    cache: dict[str, dict | None] = {}
    candidatos = enviados = fallidos = 0
    for uid, tocan in list(por_usuario.items())[:MAX_AVISOS_POR_EJECUCION]:
        cupo = min(settings.AVISOS_MAX_PARTIDOS_24H, planes_seguimiento.limites(db, uid)["partidos_24h"]) - usados[uid]  # MS-11: el tope también depende del plan
        nuevos = [p for p in tocan if (uid, p["match_id"]) not in ya][:max(0, min(MAX_PARTIDOS_POR_AVISO, cupo))]
        zona = agent_perfil.zona_de(db, uid)  # MS-6: la hora y el horario activo, en la zona de cada persona
        if ahora is not None and zona is not None and not en_horas_activas(ahora.astimezone(zona)):
            continue
        if not nuevos:
            continue  # silencio: nada nuevo que avisar
        pronosticos: dict[str, dict] = {}
        if pronostico is not None:
            for p in nuevos:
                if p["match_id"] not in cache:
                    try:
                        cache[p["match_id"]] = pronostico(db, p)
                    except Exception:  # noqa: BLE001 — el modelo caído deja el aviso sin pronóstico
                        db.rollback()
                        cache[p["match_id"]] = None
                if cache[p["match_id"]]:
                    pronosticos[p["match_id"]] = cache[p["match_id"]]
        candidatos += 1
        if await enviar(client, uid, texto_aviso(nuevos, pronosticos, zona, fecha_bd)):
            enviados += 1
            _guardar(db, uid, [(p["match_id"], "previo", json.dumps(pronosticos[p["match_id"]]) if p["match_id"] in pronosticos else None) for p in nuevos], _ahora_utc())
        else:
            fallidos += 1
    return {"fecha": fecha_bd, "candidatos": candidatos, "enviados": enviados, "fallidos": fallidos}


async def enviar_resultados(db: Session, client: httpx.AsyncClient, enviar=enviar_por_canal, ahora: datetime | None = None) -> dict:
    """Manda el final de los partidos que ya se avisaron y que terminaron, con el pronóstico que se mandó y si acertó. Un final por partido; en silencio si no hay ninguno nuevo."""
    vacio = {"candidatos": 0, "enviados": 0, "fallidos": 0}
    if ahora is not None and not en_horas_activas(ahora):
        return {**vacio, "omitido": "fuera del horario de avisos"}
    try:
        recientes = _recientes(db, _ahora_utc())
        hechos = {(r.user_id, r.partido_id) for r in recientes if r.tipo == "resultado"}
        pendientes = [r for r in recientes if r.tipo == "previo" and (r.user_id, r.partido_id) not in hechos]
        ids = {r.partido_id for r in pendientes}
        finales = {r.fixture_id: r for r in db.scalars(select(ResultadoPartido).where(ResultadoPartido.fixture_id.in_(ids), ResultadoPartido.goles_local.is_not(None), ResultadoPartido.goles_visitante.is_not(None)))} if ids else {}
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("avisos de resultado: no se pudo leer lo enviado o los resultados")
        return {**vacio, "omitido": "no se pudo comprobar lo ya enviado"}
    por_usuario: dict[str, list[tuple[BotAvisoEnviado, ResultadoPartido]]] = defaultdict(list)
    for aviso in pendientes:
        if aviso.partido_id in finales:
            por_usuario[aviso.user_id].append((aviso, finales[aviso.partido_id]))
    candidatos = enviados = fallidos = 0
    for uid, items in list(por_usuario.items())[:MAX_AVISOS_POR_EJECUCION]:
        preferencias = db.get(BotPreferencias, uid)
        if not (preferencias and preferencias.avisos == 1 and bot_memoria_repo.tiene_consentimiento(db, uid)):
            continue  # apagó los avisos o revocó el consentimiento después del aviso previo
        zona = agent_perfil.zona_de(db, uid)
        if ahora is not None and zona is not None and not en_horas_activas(ahora.astimezone(zona)):
            continue
        items = items[:MAX_PARTIDOS_POR_AVISO]
        candidatos += 1
        if await enviar(client, uid, texto_resultado(items)):
            enviados += 1
            _guardar(db, uid, [(a.partido_id, "resultado", None) for a, _ in items], _ahora_utc())
        else:
            fallidos += 1
    return {"candidatos": candidatos, "enviados": enviados, "fallidos": fallidos}
