"""services/colector_resultados.py — Colector diario de resultados, independiente del tráfico de usuarios.

Por qué existe (2026-10-07, medido en la BD real): el bot solo guardaba el marcador de los partidos que
alguien consultaba o analizaba. En 14 días `partidos_dia` tenía ~5.400 filas pero las ligas con modelo
(Chile, Colombia, Perú, Uruguay, Paraguay, Brasil Serie B, Argentina...) aportaban un puñado de
partidos terminados: los modelos Dixon-Coles de las ligas hispanohablantes se quedaban en 2024. El hueco
NO era de cobertura de la fuente (LiveScore6 trae esas ligas con marcador final también para fechas
pasadas) sino de falta de consultas: `guardar_stages_en_cache` descarta `Eps`/`Tr1`/`Tr2` y guarda todo
como 'scheduled', y WF-E solo verifica los partidos con una predicción.

Diseño:
  - Una petición a LiveScore6 (`list-by-date`) trae TODO el día con estado y marcador. Para cada fecha en
    [hoy-3 ... mañana] se persiste el día completo en `partidos_dia` (todas las ligas, igual que la
    cascada: guardar solo un subconjunto dejaría una caché del día incompleta para los usuarios) con
    `guardar_partidos_sin_retroceso` (un terminado nunca vuelve atrás, `cache_invalidado` se respeta).
  - Los terminados (FT, 90 minutos) de ligas CON modelo se registran además en `resultados_partidos`, con
    la liga calificada por país ("Primera A: Clausura (Colombia)") para que `ml/vivo` la resuelva sin
    ambigüedad. Las ligas sin modelo (o con el mismo nombre en otro país: "Premier League (Jamaica)") se
    ignoran en esa tabla.
  - Presupuesto: tope diario de peticiones (`LAPLACE_COLECTOR_MAX_PETICIONES_DIA`, defecto 8) contado en
    `stats_cache`. Una fecha pasada queda "sellada" (no se vuelve a pedir) cuando todos sus partidos ya
    son terminales o cuando ya tiene 2 o más días; mañana se pide una sola vez al día. En régimen son
    ~4-5 peticiones/día (≈150/mes de la cuota de LiveScore6, que se comparte con el bot).
  - api-football NO se usa: su plan gratuito (100/día) es compartido con el bot en vivo. Si LiveScore6
    falla, la fecha queda como fallida y se reintenta en la corrida siguiente; nunca se lanza.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.config import settings
from backend.api.db import partidos_repo
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.models.partidos import ResultadoPartido
from backend.api.services import gateway
from backend.api.services._http_retry import get_con_reintento_429
from backend.api.services.fechas_bd import FechaBdInvalida, normalizar_fecha_bd

log = logging.getLogger("laplace.colector_resultados")

TZ_CHILE = ZoneInfo("America/Santiago")
ENV_MAX_PETICIONES = "LAPLACE_COLECTOR_MAX_PETICIONES_DIA"
ENV_ACTIVO = "LAPLACE_COLECTOR_ACTIVO"
ENV_EXPORTAR = "LAPLACE_COLECTOR_EXPORTAR"
MAX_PETICIONES_DIA_DEFECTO = 8
DIAS_ATRAS = 3
DIAS_ADELANTE = 1
MAX_DIAS_ATRAS_MANUAL = 7
MAX_DIAS_ADELANTE_MANUAL = 2
MAX_GOLES_CREIBLE = 20
MAX_EQUIPOS_REPORTADOS = 25
_FALSOS = {"0", "false", "no", "off", "n", ""}

# Fuente: (client, "YYYYMMDD") -> (stages | None, cuota_restante_api | None). Lanza si la fuente falla.
Fuente = Callable[[httpx.AsyncClient, str], Awaitable[tuple[list[dict] | None, str | None]]]
# (nombre_liga, pais, local, visitante) -> (codigo_liga_con_modelo | None, ambos_equipos_resueltos)
ClasificadorLiga = Callable[[str, str, str, str], tuple[str | None, bool]]


def colector_activo() -> bool:
    return os.getenv(ENV_ACTIVO, "1").strip().lower() not in _FALSOS


def exportacion_activa() -> bool:
    return os.getenv(ENV_EXPORTAR, "1").strip().lower() not in _FALSOS


def tope_peticiones_dia() -> int:
    try:
        return max(0, int(os.getenv(ENV_MAX_PETICIONES, MAX_PETICIONES_DIA_DEFECTO)))
    except ValueError:
        return MAX_PETICIONES_DIA_DEFECTO


# ─── Estado y parseo de la fuente ────────────────────────────────────────────


def estado_desde_eps(eps: object) -> str:
    """Normaliza el `Eps` de LiveScore6 al vocabulario de `partidos_dia` (finished, scheduled, 1H, HT,
    2H, AET, PEN, PST, CANC, ABD, SUSP). Solo `FT` es 'finished': AET/PEN llevan prórroga o penales y no
    son comparables con el marcador de 90 minutos."""
    texto = str(eps or "").strip()
    bajo = texto.lower().rstrip(".")
    if bajo in ("ft",):
        return "finished"
    if bajo in ("ns", ""):
        return "scheduled"
    if bajo == "ht":
        return "HT"
    if bajo in ("aet", "aot"):
        return "AET"
    if bajo in ("ap", "pen", "aet pen"):
        return "PEN"
    if bajo in ("postp", "postponed"):
        return "PST"
    if bajo in ("canc", "cancelled", "canceled"):
        return "CANC"
    if bajo in ("aband", "abandoned"):
        return "ABD"
    if bajo in ("susp", "int", "interrupted", "suspended"):
        return "SUSP"
    minuto = "".join(c for c in texto.split("+")[0] if c.isdigit())
    if minuto:
        return "1H" if int(minuto) <= 45 else "2H"
    return "SUSP"


def _gol(valor: object) -> int | None:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= MAX_GOLES_CREIBLE else None


def parsear_stages(stages: list[dict], fecha_bd: str) -> tuple[list[dict], list[dict], dict]:
    """(partidos para `partidos_dia`, eventos con metadatos de liga, contadores de descartes).

    `partidos` usa el shape de `guardar_partidos_sin_retroceso`; `meta[i]` = {stage_nombre, pais} del
    partido `partidos[i]`. Se descartan los eventos sin id, sin equipos, o terminados sin marcador."""
    partidos: list[dict] = []
    meta: list[dict] = []
    descartes = {"sin_id": 0, "sin_equipos": 0, "terminado_sin_marcador": 0}
    for stage in stages or []:
        liga_nombre = stage.get("Snm") or "Otras"
        liga_logo = gateway._build_img(stage.get("Img") or stage.get("Logo") or stage.get("CompImg") or stage.get("badgeUrl") or "")
        for ev in stage.get("Events", []) or []:
            match_id = str(ev.get("Eid", "")).strip()
            local = ((ev.get("T1") or [{}])[0]).get("Nm")
            visitante = ((ev.get("T2") or [{}])[0]).get("Nm")
            if not match_id:
                descartes["sin_id"] += 1
                continue
            if not local or not visitante:
                descartes["sin_equipos"] += 1
                continue
            estado = estado_desde_eps(ev.get("Eps"))
            gl, gv = _gol(ev.get("Tr1")), _gol(ev.get("Tr2"))
            if partidos_repo.rango_estado(estado) == 3 and (gl is None or gv is None):
                descartes["terminado_sin_marcador"] += 1
                continue
            esd = str(ev.get("Esd", "") or "")
            partidos.append({
                "match_id": match_id, "liga_slug": gateway.slug_de_liga(liga_nombre), "liga_nombre": liga_nombre,
                "liga_logo": liga_logo, "local": local, "visitante": visitante,
                "hora_chile": f"{esd[8:10]}:{esd[10:12]}" if len(esd) >= 12 else "",
                "kick_off_utc": ev.get("kick_off_utc", "") or "",
                "logo_local": gateway._build_img(((ev.get("T1") or [{}])[0]).get("Img", "")),
                "logo_visitante": gateway._build_img(((ev.get("T2") or [{}])[0]).get("Img", "")),
                "status": estado,
                "goles_local": gl if estado != "scheduled" else None,
                "goles_visitante": gv if estado != "scheduled" else None,
            })
            meta.append({"stage_nombre": liga_nombre, "pais": str(stage.get("Cnm") or "")})
    return partidos, meta, descartes


# ─── Ligas con modelo ─────────────────────────────────────────────────────────


def clasificar_liga_con_modelo(nombre: str, pais: str, local: str, visitante: str) -> tuple[str | None, bool]:
    """Liga del histórico a la que pertenece (liga, país) y si ambos equipos se resuelven en su modelo.

    `ligas_candidatas` por sí sola da falsos positivos cuando el país no tiene modelo ("Premier League"
    de Jamaica -> E0): se exige además que el país de la liga candidata coincida con el país de la
    fuente. Devuelve (None, False) si no hay liga con modelo."""
    from backend.api.services import modelo_historico as mh

    art = mh._artefactos()
    if art is None or not pais:
        return None, False
    tabla = art["tabla_ligas"]
    pais_norm = mh._normalizar_liga(pais)
    pais_norm = tabla["sinonimos_pais"].get(pais_norm, pais_norm)
    candidatas = [
        c for c in mh.ligas_candidatas({"liga": nombre, "pais": pais, "liga_id": ""})
        if tabla["paises"].get(c) == pais_norm
    ]
    if not candidatas:
        return None, False
    codigo = candidatas[0]
    equipos_ok = bool(mh._resolver_equipo(art, codigo, local) and mh._resolver_equipo(art, codigo, visitante))
    return codigo, equipos_ok


# ─── Presupuesto y estado persistido (stats_cache) ───────────────────────────


def _clave_consumo(hoy: str) -> str:
    return f"consumo:colector:{hoy}"


def consumo_colector_hoy(db: Session, hoy: str) -> dict:
    return leer_stats_cache(db, _clave_consumo(hoy)) or {"peticiones": 0, "restante_api": None}


def _guardar_consumo(db: Session, hoy: str, peticiones: int, restante_api: str | None) -> None:
    guardar_stats_cache(db, _clave_consumo(hoy), "consumo",
                        {"peticiones": peticiones, "restante_api": restante_api}, ttl_horas_override=48)


def _registrar_peticion(db: Session, hoy: str) -> None:
    """Se cuenta ANTES de enviar: si el proceso muere a mitad de la petición, no se subestima el gasto."""
    actual = consumo_colector_hoy(db, hoy)
    _guardar_consumo(db, hoy, int(actual.get("peticiones", 0)) + 1, actual.get("restante_api"))


def _sellar(db: Session, fecha: str) -> None:
    guardar_stats_cache(db, f"colector:sellada:{fecha}", "colector", {"sellada": True}, ttl_horas_override=24 * 14)


def _marcar_programada(db: Session, fecha: str) -> None:
    guardar_stats_cache(db, f"colector:programada:{fecha}", "colector", {"pedida": True}, ttl_horas_override=20)


def fechas_por_defecto(hoy: datetime) -> list[str]:
    """Orden de prioridad bajo el tope: ayer, hoy, anteayer, hace 3 días y por último mañana."""
    offsets = [-1, 0, -2, -DIAS_ATRAS, DIAS_ADELANTE]
    return [(hoy + timedelta(days=d)).strftime("%Y-%m-%d") for d in offsets]


def _validar_fechas(fechas: list[str], hoy: datetime) -> tuple[list[str], list[dict]]:
    """Separa fechas válidas (calendario real y dentro de la ventana permitida) de las rechazadas."""
    desde = (hoy - timedelta(days=MAX_DIAS_ATRAS_MANUAL)).strftime("%Y-%m-%d")
    hasta = (hoy + timedelta(days=MAX_DIAS_ADELANTE_MANUAL)).strftime("%Y-%m-%d")
    validas: list[str] = []
    rechazadas: list[dict] = []
    for crudo in fechas:
        try:
            f = normalizar_fecha_bd(crudo)
        except FechaBdInvalida as exc:
            rechazadas.append({"fecha": str(crudo), "motivo": str(exc)})
            continue
        if not desde <= f <= hasta:
            rechazadas.append({"fecha": f, "motivo": f"fuera de la ventana permitida [{desde}, {hasta}]"})
        elif f not in validas:
            validas.append(f)
    return validas, rechazadas


# ─── Fuente real ──────────────────────────────────────────────────────────────


async def pedir_livescore6(client: httpx.AsyncClient, fecha_raw: str) -> tuple[list[dict] | None, str | None]:
    """Una petición a LiveScore6 `list-by-date`. Devuelve (stages, cuota restante del plan). Lanza si falla."""
    if not settings.LIVESCORE6_KEY:
        raise RuntimeError("LIVESCORE6_KEY no configurada")
    r = await get_con_reintento_429(
        client, gateway.LIVESCORE6_URL.format(fecha=fecha_raw), log=log, fuente="livescore6-colector",
        headers={"x-rapidapi-key": settings.LIVESCORE6_KEY, "x-rapidapi-host": "livescore6.p.rapidapi.com"},
        timeout=20,
    )
    r.raise_for_status()
    restante = r.headers.get("x-ratelimit-requests-remaining")
    return r.json().get("Stages") or None, restante


# ─── Registro en resultados_partidos ─────────────────────────────────────────


def _registrar_resultado(db: Session, partido: dict, liga_con_pais: str, fecha_bd: str) -> str:
    """Inserta el terminado en `resultados_partidos`. Devuelve 'nuevo', 'ya_registrado' o 'colision_id'.

    Los ids de LiveScore6 y los de api-football conviven en `fixture_id` (unique): si el id ya existe
    para OTRO partido (otra fecha o equipos distintos) no se pisa; si el mismo partido ya está bajo otro
    id (el bot lo registró con id de api-football) tampoco se duplica."""
    fixture_id = partido["match_id"]
    existente = db.query(ResultadoPartido).filter(ResultadoPartido.fixture_id == fixture_id).first()
    if existente is not None:
        mismo = (existente.fecha_partido == fecha_bd and (existente.local or "") == partido["local"]
                 and (existente.visitante or "") == partido["visitante"])
        return "ya_registrado" if mismo else "colision_id"
    mismo_otro_id = (
        db.query(ResultadoPartido.id)
        .filter(ResultadoPartido.fecha_partido == fecha_bd, ResultadoPartido.local == partido["local"],
                ResultadoPartido.visitante == partido["visitante"])
        .first()
    )
    if mismo_otro_id is not None:
        return "ya_registrado"
    gl, gv = partido["goles_local"], partido["goles_visitante"]
    db.add(ResultadoPartido(
        fixture_id=fixture_id, local=partido["local"], visitante=partido["visitante"], liga=liga_con_pais,
        goles_local=gl, goles_visitante=gv, ganador="local" if gl > gv else "visitante" if gv > gl else "empate",
        status_api="FT", fecha_partido=fecha_bd, actualizado_en=utc_ahora().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    return "nuevo"


def _registrar_terminados_con_modelo(
    db: Session, partidos: list[dict], meta: list[dict], fecha_bd: str, clasificar: ClasificadorLiga, resumen: dict
) -> None:
    for partido, m in zip(partidos, meta):
        if partido["status"] != "finished":
            continue
        codigo, equipos_ok = clasificar(m["stage_nombre"], m["pais"], partido["local"], partido["visitante"])
        if codigo is None:
            resumen["terminados_sin_modelo"] += 1
            continue
        resultado = _registrar_resultado(db, partido, f"{m['stage_nombre']} ({m['pais']})", fecha_bd)
        if resultado == "nuevo":
            resumen["resultados_registrados"] += 1
            resumen["por_liga"][codigo] = resumen["por_liga"].get(codigo, 0) + 1
        elif resultado == "colision_id":
            resumen["colisiones_id"] += 1
        else:
            resumen["resultados_ya_registrados"] += 1
        if not equipos_ok and resultado != "colision_id":
            for nombre in (partido["local"], partido["visitante"]):
                clave = f"{codigo}: {nombre}"
                if len(resumen["equipos_sin_resolver"]) < MAX_EQUIPOS_REPORTADOS and clave not in resumen["equipos_sin_resolver"]:
                    resumen["equipos_sin_resolver"].append(clave)
            resumen["terminados_equipo_sin_resolver"] += 1
    db.commit()


# ─── Orquestación ─────────────────────────────────────────────────────────────


def _resumen_inicial(tope: int) -> dict:
    return {
        "tope_dia": tope, "peticiones": 0, "fallidas": 0, "omitidas_por_tope": 0, "selladas_omitidas": 0,
        "programada_ya_pedida": 0, "fechas_pedidas": [], "fechas_fallidas": [], "fechas_rechazadas": [],
        "partidos_vistos": 0, "descartados": {"sin_id": 0, "sin_equipos": 0, "terminado_sin_marcador": 0},
        "partidos_dia": {"insertados": 0, "actualizados": 0, "sin_cambio": 0, "no_retrocedidos": 0, "conflictos_marcador": 0},
        "resultados_registrados": 0, "resultados_ya_registrados": 0, "colisiones_id": 0,
        "terminados_sin_modelo": 0, "terminados_equipo_sin_resolver": 0, "por_liga": {}, "equipos_sin_resolver": [],
        "restante_api": None,
    }


def _sumar(destino: dict, origen: dict) -> None:
    for clave, valor in origen.items():
        destino[clave] = destino.get(clave, 0) + valor


async def ejecutar_colector(
    db: Session,
    client: httpx.AsyncClient,
    ahora: datetime | None = None,
    fuente: Fuente = pedir_livescore6,
    fechas: list[str] | None = None,
    clasificar: ClasificadorLiga = clasificar_liga_con_modelo,
) -> dict:
    """Recoge resultados finales y programados dentro del presupuesto diario. Idempotente y a prueba de
    fallos de la fuente: una fecha que falla se cuenta en `fallidas` (el job la refleja en
    `scheduler_runs.ok`) y no impide las demás. `fechas` (YYYY-MM-DD o YYYYMMDD) reemplaza la ventana por
    defecto; las inválidas o fuera de [hoy-7, hoy+2] se rechazan sin gastar cuota."""
    hoy_dt = (ahora or datetime.now(TZ_CHILE)).astimezone(TZ_CHILE)
    hoy = hoy_dt.strftime("%Y-%m-%d")
    tope = tope_peticiones_dia()
    resumen = _resumen_inicial(tope)
    objetivo, resumen["fechas_rechazadas"] = _validar_fechas(fechas if fechas is not None else fechas_por_defecto(hoy_dt), hoy_dt)
    gastadas = int(consumo_colector_hoy(db, hoy).get("peticiones", 0))

    for fecha in objetivo:
        if fecha < hoy and leer_stats_cache(db, f"colector:sellada:{fecha}") is not None:
            resumen["selladas_omitidas"] += 1
            continue
        if fecha > hoy and leer_stats_cache(db, f"colector:programada:{fecha}") is not None:
            resumen["programada_ya_pedida"] += 1
            continue
        if gastadas >= tope:
            resumen["omitidas_por_tope"] += 1
            continue
        gastadas += 1
        resumen["peticiones"] += 1
        _registrar_peticion(db, hoy)
        try:
            stages, restante = await fuente(client, fecha.replace("-", ""))
        except Exception as exc:  # noqa: BLE001 — una fuente caída no debe tumbar el job ni las demás fechas
            log.warning("colector fecha=%s fuente fallo: %s", fecha, str(exc)[:150])
            resumen["fallidas"] += 1
            resumen["fechas_fallidas"].append(fecha)
            continue
        resumen["fechas_pedidas"].append(fecha)
        if restante is not None:
            resumen["restante_api"] = restante
            _guardar_consumo(db, hoy, int(consumo_colector_hoy(db, hoy).get("peticiones", 0)), restante)
        _procesar_fecha(db, fecha, hoy, hoy_dt, stages, clasificar, resumen)

    resumen["ok"] = resumen["fallidas"] == 0
    log.info("colector_resultados: %s", {k: v for k, v in resumen.items() if k not in ("equipos_sin_resolver",)})
    return resumen


def _procesar_fecha(
    db: Session, fecha: str, hoy: str, hoy_dt: datetime, stages: list[dict] | None,
    clasificar: ClasificadorLiga, resumen: dict,
) -> None:
    if not stages:
        return  # respuesta vacía: no se sella (puede ser transitoria) ni se marca como pedida
    partidos, meta, descartes = parsear_stages(stages, fecha)
    _sumar(resumen["descartados"], descartes)
    resumen["partidos_vistos"] += len(partidos)
    _sumar(resumen["partidos_dia"], partidos_repo.guardar_partidos_sin_retroceso(db, fecha, partidos))
    _registrar_terminados_con_modelo(db, partidos, meta, fecha, clasificar, resumen)
    if fecha > hoy:
        _marcar_programada(db, fecha)
    elif fecha < hoy:
        todo_terminal = all(partidos_repo.rango_estado(p["status"]) >= 2 for p in partidos)
        dias = (hoy_dt.date() - datetime.strptime(fecha, "%Y-%m-%d").date()).days
        if todo_terminal or dias >= 2:
            _sellar(db, fecha)


def detalle_corto(resumen: dict) -> str:
    return (
        f"{resumen['peticiones']} pet. (tope {resumen['tope_dia']}/día, {resumen['omitidas_por_tope']} omitidas, "
        f"{resumen['selladas_omitidas']} selladas, {resumen['fallidas']} fallidas); {resumen['partidos_vistos']} partidos, "
        f"{resumen['resultados_registrados']} resultados nuevos de ligas con modelo "
        f"({resumen['terminados_equipo_sin_resolver']} con equipo sin resolver)"
    )


# ─── Exportación de la capa en vivo (barata: sin numpy/scipy) ───────────────


def exportar_capa_vivo() -> dict:
    """Ejecuta `backend/scripts/exportar_resultados_vivos.py --aplicar` dentro del proceso. Esa exportación
    solo usa la librería estándar y `services/modelo_historico` (lectura de JSON), así que es barata y no
    requiere numpy/scipy; el reentrenamiento (que sí los requiere) queda en el job semanal de reajuste.
    Nunca lanza: devuelve {ok, detalle}."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "backend" / "scripts" / "exportar_resultados_vivos.py"
    if not exportacion_activa():
        return {"ok": True, "exportado": False, "detalle": "exportación desactivada (LAPLACE_COLECTOR_EXPORTAR)"}
    if not script.exists() or not settings.is_sqlite:
        return {"ok": True, "exportado": False, "detalle": "sin script de exportación o BD no SQLite"}
    from backend.api.services import modelo_historico

    if modelo_historico._artefactos() is None:  # noqa: SLF001
        # Instalación sin modelo entrenado (p. ej. el repo público): no hay contra qué resolver ligas y equipos; no es un error.
        return {"ok": True, "exportado": False, "detalle": "sin modelo histórico propio: no hay capa en vivo que exportar"}
    try:
        spec = importlib.util.spec_from_file_location("exportar_resultados_vivos", script)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        ruta_bd = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
        from backend.api.ml import datos

        resumen = modulo.exportar(ruta_bd, datos.RUTA_VIVO, aplicar=True)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — accesoria: ni una excepción ni un SystemExit deben romper el job programado
        log.warning("exportar_capa_vivo fallo: %s", str(exc)[:200])
        return {"ok": False, "exportado": False, "detalle": f"fallo: {type(exc).__name__}"}
    return {"ok": True, "exportado": True, "filas_totales": resumen["filas_totales"], "filas_nuevas": resumen["filas_nuevas"],
            "detalle": f"capa en vivo: {resumen['filas_totales']} filas ({resumen['filas_nuevas']:+d})"}
