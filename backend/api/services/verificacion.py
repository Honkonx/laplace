"""verificacion.py — el sistema verifica solo cada pronóstico: a la hora del partido va a buscar el resultado y lo guarda (AU-1 a AU-4).

Flujo:
1. Todo pronóstico emitido (bot, agente, laboratorio, modelo, autopiloto) llama a `encolar_seguro`: una fila por partido en `verificaciones`
   con el inicio en UTC y el primer intento a inicio + 140 min.
2. El trabajo `verificar_partidos` (cada 10 min) llama a `procesar_vencidas`: para cada fila vencida pregunta el resultado a las fuentes
   (base local → BSD sin cuota → api-football con tope por corrida) y la deja en uno de estos estados:
   `final` (resultado guardado y todo lo enlazado calificado por `resultados._guardar_resultado`), `en_juego` (se reintenta a los 20, 20, 30, 60, 120 y 240 min),
   `aplazado` (se reprograma cada día hasta 3 días), `sin_resultado` (cancelado o 3 días sin dato: se informa, no se inventa).
3. `sembrar_pendientes` rescata lo anterior a la cola (comparativos y observaciones del laboratorio sin resultado) para no dejar nada sin estado.
`procesar_vencidas` recibe el reloj (`ahora`) y la fuente de resultados por parámetro: la repetición del pasado (`SM-1`) los sustituye sin tocar el resto.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.api.core.horario import DURACION_PARTIDO_MIN, a_texto_utc, a_utc, fecha_chile
from backend.api.core.config import settings
from backend.api.core.tiempo import utc_ahora
from backend.api.db import partidos_repo
from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.models.predicciones import AnalisisComparativo, PronosticoExperimental
from backend.api.models.verificacion import Verificacion
from backend.api.services.normalizacion import normalizar_nombre

log = logging.getLogger("laplace.verificacion")

ESCALA_REINTENTOS_MIN = (20, 20, 30, 60, 120, 240)
HORIZONTE_DIAS = 3
MAX_APIF_POR_CORRIDA = 5
LIMITE_POR_CORRIDA = 60
ATRASO_ALARMA_MIN = 90
ESTADOS_ABIERTOS = ("pendiente", "en_juego", "aplazado")
TERMINADOS = frozenset({"FT", "AET", "PEN"})
APLAZADOS = frozenset({"PST", "SUSP", "INT"})
CANCELADOS = frozenset({"CANC", "ABD", "AWD", "WO"})
EN_JUEGO = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE"})

Fuente = Callable[[httpx.AsyncClient | None, Verificacion], Awaitable[dict | None]]


def _ahora(ahora: datetime | None) -> datetime:
    return ahora or utc_ahora().replace(tzinfo=None)


def _primer_intento(inicio: datetime | None, fecha: str | None, ahora: datetime) -> datetime:
    """Con inicio conocido: inicio + 140 min. Sin él: la mañana siguiente al día del partido (06:00 de Chile ≈ 09:00 UTC), nunca en el pasado."""
    if inicio is not None:
        return max(inicio + timedelta(minutes=DURACION_PARTIDO_MIN), ahora)   # un partido ya jugado se verifica ya
    try:
        dia = datetime.strptime(str(fecha)[:10], "%Y-%m-%d") + timedelta(days=1, hours=9)
    except ValueError:
        return ahora + timedelta(hours=3)
    return max(dia, ahora)


def encolar(db: Session, *, partido_id: str, fecha_partido: str | None, local: str | None, visitante: str | None,
            liga: str | None = None, inicio_utc: str | None = None, origen: str = "bot", ahora: datetime | None = None) -> Verificacion | None:
    """Pone el partido en la cola de verificación (idempotente: una fila por partido). Completa el inicio si antes no se conocía."""
    partido_id = str(partido_id or "").strip()
    if not partido_id:
        return None
    ahora = _ahora(ahora)
    fecha = (str(fecha_partido)[:10] if fecha_partido else "") or None
    if fecha and len(fecha) == 8 and fecha.isdigit():
        fecha = f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}"
    inicio = a_utc(inicio_utc)
    if inicio is None and fecha:
        inicio = a_utc(partidos_repo.leer_kick_off_utc(db, partido_id, fecha))
    if inicio is None:   # el análisis guarda la fecha del análisis, no la del partido: se busca el partido por su id en cualquier fecha
        fila_pd = db.query(PartidoDia.kick_off_utc).filter(PartidoDia.match_id == partido_id, PartidoDia.kick_off_utc.isnot(None), PartidoDia.kick_off_utc != "").order_by(PartidoDia.fecha.desc()).first()
        inicio = a_utc(fila_pd[0]) if fila_pd else None
    existente = db.get(Verificacion, partido_id)
    if existente is not None:
        if existente.inicio_utc is None and inicio is not None and existente.estado in ESTADOS_ABIERTOS:
            existente.inicio_utc = a_texto_utc(inicio)
            existente.proximo_intento = a_texto_utc(_primer_intento(inicio, fecha, ahora))
            existente.fecha_partido = fecha_chile(existente.inicio_utc) or existente.fecha_partido
        return existente
    fila = Verificacion(
        partido_id=partido_id, fecha_partido=(fecha_chile(a_texto_utc(inicio)) if inicio else fecha), inicio_utc=a_texto_utc(inicio) if inicio else None,
        local=local, visitante=visitante, liga=liga, origen=origen, estado="pendiente", intentos=0,
        proximo_intento=a_texto_utc(_primer_intento(inicio, fecha, ahora)), creado_en=a_texto_utc(ahora),
    )
    db.add(fila)
    db.flush()
    return fila


def encolar_seguro(db: Session, **campos) -> bool:
    """`encolar` que nunca rompe el flujo de quien llama: una falla de la cola no puede tumbar un pronóstico (se registra y se sigue)."""
    try:
        with db.begin_nested():
            return encolar(db, **campos) is not None
    except Exception as exc:  # noqa: BLE001 — función accesoria: el pronóstico ya se emitió
        log.warning("verificacion: no se pudo encolar %s: %s", campos.get("partido_id"), str(exc)[:150])
        return False


# ─────────────────────────────────────────────── fuentes de resultado
def _desde_base(db: Session, v: Verificacion) -> dict | None:
    fila = db.query(ResultadoPartido).filter(ResultadoPartido.fixture_id == v.partido_id).first()
    if fila is None and v.fecha_partido and v.local and v.visitante:
        fila = db.query(ResultadoPartido).filter(
            ResultadoPartido.fecha_partido == v.fecha_partido, ResultadoPartido.local == v.local, ResultadoPartido.visitante == v.visitante).first()
    if fila is not None and fila.goles_local is not None and fila.goles_visitante is not None:
        return {"status": "FT", "goles_local": int(fila.goles_local), "goles_visitante": int(fila.goles_visitante), "liga": fila.liga or v.liga or "", "fuente": "base"}
    pd = db.query(PartidoDia).filter(PartidoDia.match_id == v.partido_id, PartidoDia.goles_local.isnot(None)).first()
    if pd is not None and pd.status in ("finished", "FT"):
        return {"status": "FT", "goles_local": int(pd.goles_local), "goles_visitante": int(pd.goles_visitante), "liga": pd.liga_nombre or v.liga or "", "fuente": "base"}
    if pd is not None and pd.status in ("PST", "CANC", "ABD", "SUSP"):
        return {"status": pd.status, "fuente": "base"}
    return None


_ESTADO_DE_LIVESCORE = {"finished": "FT", "AET": "AET", "PEN": "PEN", "PST": "PST", "CANC": "CANC", "ABD": "ABD", "SUSP": "SUSP", "1H": "1H", "HT": "HT", "2H": "2H"}
MAX_FECHAS_LIVESCORE_POR_CORRIDA = 3


def _mismo_equipo(a: str | None, b: str | None) -> bool:
    x, y = normalizar_nombre(a), normalizar_nombre(b)
    return bool(x and y and (x == y or (len(x) >= 6 and len(y) >= 6 and (x[:6] in y or y[:6] in x))))


class FuenteReal:
    """Base local → LiveScore por fecha (una petición cubre todos los partidos de un día; con tope por corrida y el tope diario del colector) → BSD (sin cuota) → api-football
    (solo ids numéricos; el plan gratuito no da la temporada actual). Una instancia por corrida lleva sus contadores y la caché por fecha."""

    def __init__(self, db: Session, tope_apif: int = MAX_APIF_POR_CORRIDA, tope_fechas: int = MAX_FECHAS_LIVESCORE_POR_CORRIDA):
        self.db, self.restante_apif, self.restantes_fechas = db, tope_apif, tope_fechas
        self._livescore: dict[str, list[dict]] = {}

    async def _eventos_livescore(self, client: httpx.AsyncClient, fecha: str) -> list[dict]:
        from backend.api.services import colector_resultados as col

        if fecha in self._livescore:
            return self._livescore[fecha]
        hoy = utc_ahora().strftime("%Y-%m-%d")
        if self.restantes_fechas <= 0 or int(col.consumo_colector_hoy(self.db, hoy).get("peticiones", 0)) >= col.tope_peticiones_dia():
            return []
        self.restantes_fechas -= 1
        col._registrar_peticion(self.db, hoy)  # noqa: SLF001 — comparte el presupuesto diario con el colector
        try:
            stages, _ = await col.pedir_livescore6(client, fecha.replace("-", ""))
            eventos, _, _ = col.parsear_stages(stages or [], fecha)
        except Exception as exc:  # noqa: BLE001 — sin la fuente se sigue con las demás
            log.warning("verificacion: livescore %s falló: %s", fecha, str(exc)[:120])
            eventos = []
        self._livescore[fecha] = eventos
        return eventos

    async def _desde_livescore(self, client: httpx.AsyncClient, v: Verificacion) -> dict | None:
        if not v.fecha_partido or not settings.LIVESCORE6_KEY:
            return None
        siguiente = (datetime.strptime(v.fecha_partido, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")   # LiveScore fecha por UTC+7: un partido de la noche de Chile cae al día siguiente
        for fecha in (v.fecha_partido, siguiente):
            for p in await self._eventos_livescore(client, fecha):
                if _mismo_equipo(p["local"], v.local) and _mismo_equipo(p["visitante"], v.visitante):
                    estado = _ESTADO_DE_LIVESCORE.get(p["status"])
                    if estado is None:
                        return None   # aún sin empezar
                    return {"status": estado, "goles_local": p["goles_local"], "goles_visitante": p["goles_visitante"], "liga": p["liga_nombre"], "fuente": "livescore"}
        return None

    async def __call__(self, client: httpx.AsyncClient | None, v: Verificacion) -> dict | None:
        from backend.api.services import resultados as svc

        local = _desde_base(self.db, v)
        if local is not None:
            return local
        if client is None:
            return None
        encontrado = await self._desde_livescore(client, v)
        if encontrado is not None:
            return encontrado
        if v.local and v.visitante and v.fecha_partido:
            bsd = await svc._bsd_buscar_resultado(client, v.local, v.visitante, v.fecha_partido)
            if bsd:
                return {**bsd, "fuente": "bsd"}
        if v.partido_id.isdigit() and self.restante_apif > 0:
            self.restante_apif -= 1
            datos = (await svc._consultar_fixtures_apifootball(client, [v.partido_id])).get(v.partido_id)
            if datos:
                return {**datos, "fuente": "api-football"}
        return None


# ─────────────────────────────────────────────── cierre
def _cerrar_con_resultado(db: Session, v: Verificacion, d: dict, ahora: datetime) -> None:
    from backend.api.services import resultados as svc

    gl, gv = int(d["goles_local"] or 0), int(d["goles_visitante"] or 0)
    fecha = v.fecha_partido or (a_texto_utc(ahora)[:10])
    svc._guardar_resultado(db, v.partido_id, d.get("local") or v.local or "", d.get("visitante") or v.visitante or "", d.get("liga") or v.liga or "", gl, gv, d.get("status") or "FT", fecha)
    v.estado, v.goles_local, v.goles_visitante, v.resuelto_en, v.proximo_intento = "final", gl, gv, a_texto_utc(ahora), None
    v.ultima_fuente = d.get("fuente")


def _cerrar_sin_resultado(db: Session, v: Verificacion, motivo: str, ahora: datetime, marca: str = "CANC") -> None:
    for fila in db.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == v.partido_id, AnalisisComparativo.resultado_real.is_(None)):
        fila.status_partido, fila.resultado_real = marca, marca
    v.estado, v.ultimo_error, v.resuelto_en, v.proximo_intento = "sin_resultado", motivo, a_texto_utc(ahora), None


def _reprogramar(v: Verificacion, ahora: datetime, minutos: int | None = None, dias: int | None = None) -> None:
    espera = timedelta(days=dias) if dias else timedelta(minutes=minutos if minutos is not None else ESCALA_REINTENTOS_MIN[min(v.intentos - 1, len(ESCALA_REINTENTOS_MIN) - 1)])
    v.proximo_intento = a_texto_utc(ahora + espera)


async def verificar_uno(db: Session, client: httpx.AsyncClient | None, v: Verificacion, fuente: Fuente, ahora: datetime) -> str:
    """Un intento sobre un partido: devuelve el estado en que queda. Nunca lanza: una fuente caída solo cuenta como intento."""
    v.intentos = (v.intentos or 0) + 1
    try:
        d = await fuente(client, v)
    except Exception as exc:  # noqa: BLE001 — una fuente caída no detiene al resto
        v.ultimo_error = f"{type(exc).__name__}: {str(exc)[:120]}"
        d = None
    inicio = a_utc(v.inicio_utc) or a_utc(v.creado_en) or ahora
    limite = inicio + timedelta(days=HORIZONTE_DIAS)
    estado = str((d or {}).get("status") or "")
    if d and estado in TERMINADOS and d.get("goles_local") is not None and d.get("goles_visitante") is not None:
        _cerrar_con_resultado(db, v, d, ahora)
    elif d and estado in CANCELADOS:
        _cerrar_sin_resultado(db, v, f"partido {estado}", ahora)
    elif d and estado in APLAZADOS:
        v.estado = "aplazado"
        if ahora >= limite + timedelta(days=HORIZONTE_DIAS):
            _cerrar_sin_resultado(db, v, f"aplazado más de {HORIZONTE_DIAS} días", ahora, marca="PST")
        else:
            _reprogramar(v, ahora, dias=1)
    elif ahora >= limite:
        _cerrar_sin_resultado(db, v, v.ultimo_error or f"sin resultado tras {HORIZONTE_DIAS} días", ahora, marca="SIN_DATO")
    else:
        v.estado = "en_juego" if estado in EN_JUEGO else "pendiente"
        _reprogramar(v, ahora)
    return v.estado


async def procesar_vencidas(db: Session, client: httpx.AsyncClient | None, ahora: datetime | None = None, fuente: Fuente | None = None,
                            limite: int = LIMITE_POR_CORRIDA) -> dict:
    """Verifica todo lo vencido (lo más atrasado primero). Idempotente: una corrida perdida se recupera en la siguiente sin duplicar nada."""
    ahora = _ahora(ahora)
    fuente = fuente or FuenteReal(db)
    vencidas = (db.query(Verificacion).filter(Verificacion.estado.in_(ESTADOS_ABIERTOS), Verificacion.proximo_intento <= a_texto_utc(ahora))
                .order_by(Verificacion.proximo_intento.asc()).limit(limite).all())
    resumen = {"revisadas": len(vencidas), "final": 0, "en_juego": 0, "pendiente": 0, "aplazado": 0, "sin_resultado": 0}
    for v in vencidas:
        estado = await verificar_uno(db, client, v, fuente, ahora)
        resumen[estado] = resumen.get(estado, 0) + 1
        db.commit()
    resumen["atrasadas"] = estado_cola(db, ahora)["atrasadas"]
    return resumen


# ─────────────────────────────────────────────── rescate y estado
def sembrar_pendientes(db: Session, dias: int = 14, ahora: datetime | None = None, tope: int = 500) -> int:
    """Pone en la cola lo que quedó sin resultado antes de existir la cola (comparativos y observaciones del laboratorio de los últimos `dias`)."""
    ahora = _ahora(ahora)
    desde = (ahora - timedelta(days=dias)).strftime("%Y-%m-%d")
    nuevos = 0
    comparativos = db.query(AnalisisComparativo).filter(AnalisisComparativo.resultado_real.is_(None), AnalisisComparativo.fecha >= desde).limit(tope).all()
    experimentales = db.query(PronosticoExperimental).filter(PronosticoExperimental.resultado_real.is_(None)).order_by(PronosticoExperimental.id.desc()).limit(tope).all()   # `fecha_partido` llega en dos formatos (AAAA-MM-DD y AAAAMMDD): no se filtra por texto
    for origen, filas in (("bot", comparativos), ("laboratorio", experimentales)):
        for f in filas:
            fecha = getattr(f, "fecha", None) or getattr(f, "fecha_partido", None)
            if db.get(Verificacion, str(f.partido_id)) is None and encolar_seguro(db, partido_id=f.partido_id, fecha_partido=fecha, local=f.local, visitante=f.visitante,
                                                                              liga=f.liga, inicio_utc=None, origen=origen, ahora=ahora):
                nuevos += 1
    return nuevos


def estado_cola(db: Session, ahora: datetime | None = None) -> dict:
    """Conteo por estado y cuántas verificaciones llevan más de 90 min vencidas (la señal de que el verificador no está corriendo)."""
    ahora = _ahora(ahora)
    por_estado = {e: n for e, n in db.query(Verificacion.estado, func.count()).group_by(Verificacion.estado).all()}
    limite = a_texto_utc(ahora - timedelta(minutes=ATRASO_ALARMA_MIN))
    atrasadas = db.query(Verificacion).filter(Verificacion.estado.in_(ESTADOS_ABIERTOS), Verificacion.proximo_intento <= limite).count()
    return {"por_estado": por_estado, "atrasadas": atrasadas, "total": sum(por_estado.values())}
