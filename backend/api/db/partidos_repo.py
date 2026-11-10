"""
db/partidos_repo.py — Acceso a `partidos_dia` (caché lazy de fixtures del día).

Reemplaza `leer_ligas_cache`/`guardar_ligas_cache`/`guardar_partidos_dia`/`leer_partidos_dia`
de db_query.py — antes se llamaban vía `subprocess` desde
gateway_unificado.py (`ejecutar_db_query`); acá es una llamada SQLAlchemy directa (misma
sesión de la request, sin el overhead ni el riesgo de timeout de un subprocess nuevo).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services.fechas_bd import FechaBdInvalida, normalizar_fecha_bd

log = logging.getLogger("laplace.partidos_repo")


def _fecha_iso_o_original(fecha: str) -> str:
    try:
        return normalizar_fecha_bd(fecha)
    except FechaBdInvalida:
        return fecha


def leer_ligas_cache(db: Session, fecha_bd: str) -> dict:
    """Devuelve {'hit': bool, 'total': int, 'ligas': {slug: {...}}} agrupando por liga_slug —
    mismo shape que devolvía `leer_ligas_cache` en db_query.py, consumido por
    `gateway._bd_stages`."""
    fecha_norm = _fecha_iso_o_original(fecha_bd)
    filas = (
        db.query(PartidoDia)
        .filter(PartidoDia.fecha.in_({fecha_bd, fecha_norm}), PartidoDia.cache_invalidado == 0)
        .all()
    )
    if not filas:
        return {"hit": False, "total": 0, "ligas": {}}

    ligas: dict[str, dict] = {}
    for fila in filas:
        slug = fila.liga_slug or "otras"
        if slug not in ligas:
            ligas[slug] = {"nombre": fila.liga_nombre or slug, "logo": fila.liga_logo, "partidos": []}
        ligas[slug]["partidos"].append(
            {
                "match_id": fila.match_id,
                "local": fila.local,
                "visitante": fila.visitante,
                "hora_chile": fila.hora_chile,
                "kick_off_utc": fila.kick_off_utc,
                "logo_local": fila.logo_local,
                "logo_visitante": fila.logo_visitante,
            }
        )
    return {"hit": True, "total": len(filas), "ligas": ligas}


def guardar_ligas_cache(db: Session, fecha_bd: str, partidos: list[dict]) -> int:
    """Upsert de una lista de partidos en `partidos_dia`. Devuelve cuántos se guardaron.

    Solo se llama con datos que vienen de un fetch REAL a una fuente externa —
    `gateway.guardar_stages_en_cache` corta antes de llamar acá si `fuente == "bd"` (ver
    services/gateway.py). `creado_en` es por lo tanto el timestamp real de "cuándo se
    consultó a la API real" (piece 1 del pedido de caché con timestamp explícito) y se
    refresca en CADA guardado, no solo al crear la fila.

    Bug real corregido 2026-09-09 (confirmado empíricamente, no solo leyendo el código): la
    rama `existente` no reseteaba `cache_invalidado` a 0. Una vez que un sweep (`invalidar_
    cache_dia_anterior`/`invalidar_partidos_terminados`) marcaba una fecha/partido como
    invalidado, un re-fetch real de esa MISMA fecha/match_id volvía a upsertear la fila
    existente sin limpiar la bandera — `leer_ligas_cache` (que filtra `cache_invalidado==0`)
    nunca volvía a dar HIT para esa fecha, forzando la cascada de red completa en TODAS las
    consultas siguientes de por vida, exactamente lo opuesto del objetivo de esta caché.

    `creado_en` normalizado a UTC 2026-09-09 (ver docstring de `jobs_repo._now_str`) — filas
    anteriores a este commit pueden estar en hora local de Chile."""
    fecha_bd = normalizar_fecha_bd(fecha_bd)  # rechaza claves basura (`2026--0-9-`), no guarda en silencio
    ahora = utc_ahora().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for p in partidos:
        match_id = str(p.get("match_id", "")).strip()
        if not match_id:
            continue
        existente = db.get(PartidoDia, (fecha_bd, match_id))
        if existente is None:
            db.add(
                PartidoDia(
                    fecha=fecha_bd,
                    match_id=match_id,
                    liga_slug=p.get("liga_slug"),
                    liga_nombre=p.get("liga_nombre"),
                    liga_codigo=p.get("liga_codigo"),
                    liga_logo=p.get("liga_logo"),
                    local=p.get("local"),
                    visitante=p.get("visitante"),
                    hora_chile=p.get("hora_chile"),
                    logo_local=p.get("logo_local"),
                    logo_visitante=p.get("logo_visitante"),
                    status=p.get("status", "scheduled"),
                    creado_en=ahora,
                    kick_off_utc=p.get("kick_off_utc"),
                    cache_invalidado=0,
                )
            )
        else:
            existente.liga_slug = p.get("liga_slug", existente.liga_slug)
            existente.liga_nombre = p.get("liga_nombre", existente.liga_nombre)
            existente.liga_logo = p.get("liga_logo", existente.liga_logo)
            existente.local = p.get("local", existente.local)
            existente.visitante = p.get("visitante", existente.visitante)
            existente.kick_off_utc = p.get("kick_off_utc", existente.kick_off_utc)
            existente.creado_en = ahora
            existente.cache_invalidado = 0
        n += 1
    db.commit()
    return n


def leer_partidos_dia(db: Session, fecha_bd: str) -> list[PartidoDia]:
    return db.query(PartidoDia).filter(PartidoDia.fecha == fecha_bd).all()


def guardar_partidos_dia(db: Session, fecha_bd: str, partidos: list[dict]) -> int:
    """Variante de `guardar_ligas_cache` que además acepta `goles_local`/`goles_visitante`/
    `apifootball_fixture_id` — mismo `INSERT OR REPLACE` semántico que `guardar_partidos_dia`
    en db_query.py, misma tabla `partidos_dia` (no hay dos tablas paralelas:
    ese `guardar_partidos_dia` original y `guardar_ligas_cache`/`leer_ligas_cache` operan
    sobre la MISMA tabla, solo con distinto subconjunto de columnas). `creado_en` normalizado
    a UTC 2026-09-09, mismo criterio que `guardar_ligas_cache`."""
    fecha_bd = normalizar_fecha_bd(fecha_bd)  # rechaza claves basura (`2026--0-9-`), no guarda en silencio
    ahora = utc_ahora().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for p in partidos:
        match_id = str(p.get("match_id", "")).strip()
        if not match_id:
            continue
        existente = db.get(PartidoDia, (fecha_bd, match_id))
        if existente is None:
            db.add(
                PartidoDia(
                    fecha=fecha_bd,
                    match_id=match_id,
                    liga_slug=p.get("liga_slug"),
                    liga_nombre=p.get("liga_nombre"),
                    liga_codigo=p.get("liga_codigo"),
                    liga_logo=p.get("liga_logo"),
                    local=p.get("local"),
                    visitante=p.get("visitante"),
                    hora_chile=p.get("hora_chile"),
                    logo_local=p.get("logo_local"),
                    logo_visitante=p.get("logo_visitante"),
                    status=p.get("status", "scheduled"),
                    goles_local=p.get("goles_local"),
                    goles_visitante=p.get("goles_visitante"),
                    creado_en=ahora,
                    kick_off_utc=p.get("kick_off_utc"),
                    cache_invalidado=0,
                    apifootball_fixture_id=p.get("apifootball_fixture_id"),
                )
            )
        else:
            existente.liga_slug = p.get("liga_slug", existente.liga_slug)
            existente.liga_nombre = p.get("liga_nombre", existente.liga_nombre)
            existente.liga_codigo = p.get("liga_codigo", existente.liga_codigo)
            existente.liga_logo = p.get("liga_logo", existente.liga_logo)
            existente.local = p.get("local", existente.local)
            existente.visitante = p.get("visitante", existente.visitante)
            existente.hora_chile = p.get("hora_chile", existente.hora_chile)
            existente.logo_local = p.get("logo_local", existente.logo_local)
            existente.logo_visitante = p.get("logo_visitante", existente.logo_visitante)
            existente.status = p.get("status", existente.status)
            existente.goles_local = p.get("goles_local", existente.goles_local)
            existente.goles_visitante = p.get("goles_visitante", existente.goles_visitante)
            existente.kick_off_utc = p.get("kick_off_utc", existente.kick_off_utc)
            existente.apifootball_fixture_id = p.get("apifootball_fixture_id", existente.apifootball_fixture_id)
            # Mismo fix que guardar_ligas_cache (ver su docstring): un re-guardado real no
            # debe dejar la fila atascada como invalidada para siempre.
            existente.creado_en = ahora
            existente.cache_invalidado = 0
        n += 1
    db.commit()
    return n


def _es_pronosticable(fila) -> bool:
    """El bot tiene modelo histórico para este partido (liga y equipos): la app puede ofrecerlo primero."""
    from backend.api.services import modelo_historico

    try:
        return bool(modelo_historico.validar_historico(
            {"liga": fila.liga_nombre or "", "local": fila.local or "", "visitante": fila.visitante or ""})[0])
    except Exception:  # noqa: BLE001 — un fallo del histórico nunca debe romper el listado
        log.debug("partidos_repo: validación histórica falló", exc_info=True)
        return False


def leer_partidos_dia_agrupado(db: Session, fecha_bd: str, liga_slug: str | None = None) -> dict:
    """Equivalente a `leer_partidos_dia` original (db_query.py) — con `liga_slug` devuelve
    lista plana de esa liga; sin él, estructura agrupada por liga (`buttons`/`ligas`),
    consumida por el reemplazo de la acción `juegos` de WF-A2."""
    fecha_norm = _fecha_iso_o_original(fecha_bd)
    query = db.query(PartidoDia).filter(PartidoDia.fecha.in_({fecha_bd, fecha_norm}))
    if liga_slug:
        query = query.filter(PartidoDia.liga_slug == liga_slug)
    filas = query.order_by(PartidoDia.liga_slug.asc(), PartidoDia.hora_chile.asc()).all()

    if not filas:
        return {"buttons": [], "ligas": {}, "total": 0, "from_local_db": True}

    buttons = []
    ligas: dict[str, dict] = {}
    for f in filas:
        partido = {
            "match_id": f.match_id, "local": f.local, "visitante": f.visitante,
            "hora_chile": f.hora_chile, "status": f.status,
            # Claves que lee la app Android (HomeScreen/MatchesScreen/CalendarScreen): sin ellas tocar un partido navegaba con
            # matchId vacío y la hora salía en blanco. Se conservan las claves originales para la web.
            "id": f.match_id, "hora": f.hora_chile,
            "gol_local": None if f.goles_local is None else str(f.goles_local),
            "gol_visitante": None if f.goles_visitante is None else str(f.goles_visitante),
            "goles_local": f.goles_local, "goles_visitante": f.goles_visitante,
            "logo_local": f.logo_local, "logo_visitante": f.logo_visitante,
            "pronosticable": _es_pronosticable(f),
        }
        buttons.append(partido)
        slug = f.liga_slug or "otras"
        if slug not in ligas:
            ligas[slug] = {"nombre": f.liga_nombre or slug, "logo": f.liga_logo, "partidos": []}
        ligas[slug]["partidos"].append(partido)

    try:
        delta = (datetime.now() - datetime.strptime(fecha_norm, "%Y-%m-%d")).days
        stale = delta > 2
    except ValueError:
        stale = False

    return {"buttons": buttons, "ligas": ligas, "total": len(buttons), "from_local_db": True,
            "stale": stale, "fecha": fecha_norm}


def limpiar_partidos_dia_viejos(db: Session, dias: int = 90) -> int:
    limite = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    filas = db.query(PartidoDia).filter(PartidoDia.fecha < limite).all()
    n = len(filas)
    for fila in filas:
        db.delete(fila)
    db.commit()
    return n


def invalidar_partido_cache(db: Session, fecha_bd: str, match_id: str) -> None:
    fecha_norm = _fecha_iso_o_original(fecha_bd)
    fila = db.get(PartidoDia, (fecha_norm, match_id)) or db.get(PartidoDia, (fecha_bd, match_id))
    if fila is not None:
        fila.cache_invalidado = 1
        db.commit()


def invalidar_partidos_terminados(db: Session, antes_de_utc: str) -> int:
    """Invalida partidos cuyo kick_off_utc + ventana ya pasó — mismo criterio de sweep que
    actualizar_resultados.py (kick_off_utc + 115min < ahora)."""
    filas = (
        db.query(PartidoDia)
        .filter(PartidoDia.kick_off_utc < antes_de_utc, PartidoDia.cache_invalidado == 0)
        .all()
    )
    for fila in filas:
        fila.cache_invalidado = 1
    db.commit()
    return len(filas)


def invalidar_cache_dia_anterior(db: Session, fecha: str) -> int:
    """Invalida TODOS los partidos de una fecha pasada (`fecha` = ayer, formato de
    `partidos_dia.fecha`). Port de `db_query.py::invalidar_cache_dia_anterior` (L3710) —
    corre a medianoche/al inicio del día, complementa el sweep por hora de
    `invalidar_partidos_terminados` (que corre cada 2h)."""
    fecha_norm = _fecha_iso_o_original(fecha)
    filas = db.query(PartidoDia).filter(PartidoDia.fecha.in_({fecha, fecha_norm}), PartidoDia.cache_invalidado == 0).all()
    for fila in filas:
        fila.cache_invalidado = 1
    db.commit()
    return len(filas)


def leer_kick_off_utc(db: Session, match_id: str, fecha: str) -> str | None:
    """Devuelve el `kick_off_utc` real cacheado de `partidos_dia` para un partido puntual, o
    `None` si no está (no es un fallo — muchos partidos de ligas desconocidas nunca se cachean
    con este detalle). Usado por `services/analisis_completo.py` para decidir un TTL de odds más
    corto cerca del kickoff (2026-09-09) — necesita el dato para CUALQUIER origen de job (app o
    telegram), no solo cuando venía embebido en el evento de la cascada de fixtures."""
    fecha_norm = _fecha_iso_o_original(fecha)
    row = (
        db.query(PartidoDia.kick_off_utc)
        .filter(
            ((PartidoDia.match_id == match_id) | (PartidoDia.apifootball_fixture_id == match_id))
            & (PartidoDia.fecha.in_({fecha, fecha_norm})),
        )
        .first()
    )
    return row[0] if row and row[0] else None


def leer_pendientes_ventana(db: Session, fecha: str, minutos_min: int = 105, minutos_max: int = 240) -> list[dict]:
    """Partidos de `analisis_comparativo` sin `resultado_real` cuyo kickoff (`partidos_dia.
    kick_off_utc`) cayó hace entre `minutos_min` y `minutos_max` — ahorra cuota de API
    consultando solo partidos que probablemente ya terminaron. Sin `kick_off_utc` conocido se
    incluye igual (no se puede descartar sin datos) — mismo criterio que
    `db_query.py::leer_pendientes_ventana` (L1436).

    `fecha` en formato YYYY-MM-DD (igual que `analisis_comparativo.fecha`)."""
    ahora_utc = utc_ahora()
    filas = (
        db.query(AnalisisComparativo, PartidoDia.kick_off_utc)
        .outerjoin(
            PartidoDia,
            ((PartidoDia.match_id == AnalisisComparativo.partido_id)
             | (PartidoDia.apifootball_fixture_id == AnalisisComparativo.partido_id))
            & (PartidoDia.fecha == fecha),
        )
        .filter(AnalisisComparativo.fecha == fecha, AnalisisComparativo.resultado_real.is_(None))
        .order_by(AnalisisComparativo.hora_kickoff.asc())
        .all()
    )

    pendientes: list[dict] = []
    for ac, kick_off_utc in filas:
        base = {
            "fixture_id": ac.partido_id, "local": ac.local, "visitante": ac.visitante,
            "liga": ac.liga, "hora_kickoff": ac.hora_kickoff,
        }
        if not kick_off_utc:
            pendientes.append({**base, "kick_off_utc": None, "en_ventana": None})
            continue
        try:
            ko_dt = datetime.strptime(kick_off_utc[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pendientes.append({**base, "kick_off_utc": kick_off_utc, "en_ventana": None})
            continue
        if ko_dt + timedelta(minutes=minutos_min) <= ahora_utc <= ko_dt + timedelta(minutes=minutos_max):
            pendientes.append({**base, "kick_off_utc": kick_off_utc, "en_ventana": True})

    return pendientes


# ─── Colector diario de resultados (services/colector_resultados.py) ──────────

# Rango de "avance" de un estado: un partido nunca retrocede de rango (terminado -> en juego ->
# programado). CANC/PST/ABD (suspendido o aplazado) no son terminados: solo pueden ser
# reemplazados por un estado terminado o por otro del mismo rango.
ESTADOS_TERMINADOS_REPO = frozenset({"finished", "FT", "AET", "PEN", "AWD"})
ESTADOS_ANULADOS_REPO = frozenset({"CANC", "PST", "ABD"})
ESTADOS_PROGRAMADOS_REPO = frozenset({"scheduled", "NS", ""})


def rango_estado(status: str | None) -> int:
    """3 = terminado, 2 = anulado/aplazado, 1 = en juego, 0 = programado."""
    s = (status or "").strip()
    if s in ESTADOS_TERMINADOS_REPO:
        return 3
    if s in ESTADOS_ANULADOS_REPO:
        return 2
    if s in ESTADOS_PROGRAMADOS_REPO:
        return 0
    return 1


def guardar_partidos_sin_retroceso(db: Session, fecha_bd: str, partidos: list[dict]) -> dict:
    """Upsert para el colector diario: persiste estado y marcador SIN pisar datos mejores ya guardados.

    Diferencias deliberadas frente a `guardar_partidos_dia` (que sobreescribe todo y resetea
    `cache_invalidado` a 0, lo correcto para una lectura cacheada de la API pero no para un
    colector que repasa fechas pasadas):
      - un estado nunca retrocede de rango (ver `rango_estado`): un partido terminado no vuelve a
        'scheduled' ni a 'en juego', y conserva su marcador aunque la fuente traiga otro distinto
        (se cuenta como `conflictos_marcador`, no se pisa);
      - `cache_invalidado` de una fila existente NO se resetea (solo pasa a 1 al terminar el
        partido); una fila nueva nace invalidada si ya terminó o es de una fecha pasada
        (`invalidar_pasado=True`), para que la caché de fixtures no sirva un día viejo como vigente;
      - nombres, logos, hora y kick-off existentes se conservan (solo se rellenan si estaban vacíos);
      - `creado_en` de una fila existente no se refresca (no es una lectura nueva del fixture).

    Idempotente: ejecutarla dos veces con los mismos datos no cambia nada la segunda vez.
    Devuelve contadores {insertados, actualizados, sin_cambio, no_retrocedidos, conflictos_marcador}."""
    fecha_bd = normalizar_fecha_bd(fecha_bd)
    ahora = utc_ahora().strftime("%Y-%m-%d %H:%M:%S")
    hoy_chile = utc_ahora() - timedelta(hours=4)
    es_pasada = fecha_bd < hoy_chile.strftime("%Y-%m-%d")
    cuenta = {"insertados": 0, "actualizados": 0, "sin_cambio": 0, "no_retrocedidos": 0, "conflictos_marcador": 0}
    for p in partidos:
        match_id = str(p.get("match_id", "")).strip()
        if not match_id:
            continue
        nuevo_estado = p.get("status") or "scheduled"
        existente = db.get(PartidoDia, (fecha_bd, match_id))
        if existente is None:
            terminado = rango_estado(nuevo_estado) == 3
            db.add(PartidoDia(
                fecha=fecha_bd, match_id=match_id, liga_slug=p.get("liga_slug"), liga_nombre=p.get("liga_nombre"),
                liga_codigo=p.get("liga_codigo"), liga_logo=p.get("liga_logo"), local=p.get("local"),
                visitante=p.get("visitante"), hora_chile=p.get("hora_chile"), logo_local=p.get("logo_local"),
                logo_visitante=p.get("logo_visitante"), status=nuevo_estado, goles_local=p.get("goles_local"),
                goles_visitante=p.get("goles_visitante"), creado_en=ahora, kick_off_utc=p.get("kick_off_utc"),
                cache_invalidado=1 if (terminado or es_pasada) else 0,
            ))
            cuenta["insertados"] += 1
            continue
        cambios = _aplicar_a_existente(existente, p, nuevo_estado, cuenta)
        cuenta["actualizados" if cambios else "sin_cambio"] += 1
    db.commit()
    return cuenta


def _aplicar_a_existente(existente: PartidoDia, p: dict, nuevo_estado: str, cuenta: dict) -> bool:
    """Aplica `p` sobre la fila `existente` sin retroceder; True si cambió algún campo."""
    antes = (existente.status, existente.goles_local, existente.goles_visitante, existente.cache_invalidado,
             existente.hora_chile, existente.liga_nombre, existente.local, existente.visitante)
    rango_actual, rango_nuevo = rango_estado(existente.status), rango_estado(nuevo_estado)
    gl, gv = p.get("goles_local"), p.get("goles_visitante")
    if rango_nuevo < rango_actual:
        cuenta["no_retrocedidos"] += 1
    elif rango_actual == 3 and rango_nuevo == 3:
        if existente.goles_local is None or existente.goles_visitante is None:
            existente.goles_local, existente.goles_visitante = gl, gv
        elif (gl, gv) != (existente.goles_local, existente.goles_visitante) and gl is not None and gv is not None:
            cuenta["conflictos_marcador"] += 1
    else:
        existente.status = nuevo_estado
        if gl is not None and gv is not None:
            existente.goles_local, existente.goles_visitante = gl, gv
        if rango_nuevo == 3:
            existente.cache_invalidado = 1
    for campo in ("hora_chile", "liga_nombre", "liga_slug", "liga_logo", "local", "visitante", "logo_local",
                  "logo_visitante", "kick_off_utc"):
        if not getattr(existente, campo) and p.get(campo):
            setattr(existente, campo, p[campo])
    despues = (existente.status, existente.goles_local, existente.goles_visitante, existente.cache_invalidado,
               existente.hora_chile, existente.liga_nombre, existente.local, existente.visitante)
    return antes != despues
