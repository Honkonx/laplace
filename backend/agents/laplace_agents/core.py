"""laplace_agents/core.py — Auto-evaluación diaria del motor: Laplace se analiza a sí mismo,
sin depender de que un usuario real pida algo.

Reubicado 2026-09-10 desde `services/laplace_agents.py` — el usuario pidió que este
sistema tenga su propia carpeta en la raíz del repo, separada físicamente del backend, porque
NO es "el bot" — es una extensión/agente que el bot nunca debe necesitar para funcionar (mismo
principio que ya se verificó con evidencia real para el motor/IA, ver
el registro de decisiones del proyecto). El paquete `laplace_agents` importa funciones reales del backend
(`backend.api.services.analisis_completo`, `gateway`, `ligas`, `backend.api.db.analisis_repo`)
— la dependencia va en un solo sentido: `laplace-agents` → `backend`, nunca al revés. El
backend (`main.py`, `routers/scheduler.py`) es quien orquesta CUÁNDO correr este ciclo (cron
diario + endpoint manual), pero la lógica real de qué hacer vive acá.

Hallazgo real que motiva este módulo (2026-09-09, ver el registro de decisiones del proyecto): el verificador
de resultados (`services/resultados_scheduler.py`) solo VERIFICA partidos que YA tienen una
fila en `analisis_comparativo` — y esa tabla, antes de este módulo, solo se poblaba cuando
`services/analisis_completo.py::procesar_job` corría, lo que solo pasaba disparado por un
usuario real (bot de Telegram, app, o `POST /api/v1/prediccion-web`). Sin usuarios preguntando
por un partido, ese partido nunca se analizaba, nunca se guardaba, y nunca se podía verificar —
la calibración del motor (`services/calibracion.py`) dependía 100% del tráfico real de
usuarios, en vez de que el sistema se auto-evalúe.

Este módulo corre una vez al día (cron, ver `backend/api/main.py`), independiente de cualquier
usuario:
1. Pide los fixtures reales del día (misma caché/cascada ya existente, `gateway.
   obtener_fixtures_cascada` — no dispara llamadas nuevas si ya se pidieron hoy).
2. Filtra a las ligas que el sistema conoce de verdad (`ligas.es_liga_conocida`) — analizar un
   partido de una liga desconocida solo gastaría cálculo sin dato real de referencia.
3. Para cada partido NUEVO (que nadie pidió todavía hoy, `analisis_repo.existe_comparativo`),
   corre el MISMO núcleo real de análisis que usa un request de usuario
   (`analisis_completo.analizar_y_persistir`, sin IA — esto es para calibración y para
   pre-calentar la caché, no para generar contenido editorial) y lo persiste en
   `analisis_comparativo` — el mismo lugar que ya lee el verificador de resultados, sin
   ningún caso especial.

Efecto secundario deseado (no solo calibración): un usuario que después pregunte por ESE mismo
partido lo encuentra ya resuelto en caché (fixture/standings/odds/H2H) y, si `analisis_repo.
existe_comparativo` ya está poblado, `verificar_partido_completo`/`leer_top_picks_app` pueden
servirlo sin volver a correr el motor — carga más rápido para el usuario real.

Nunca envía nada a Telegram, nunca actualiza `jobs` (no hay un job de usuario detrás) — es
estrictamente análisis + persistencia, igual que `top_picks.py` no le manda un mensaje al
usuario que nunca preguntó.

Ver `README.md` de este paquete para la visión completa (roadmap) del proyecto Laplace-Agents
más allá de este módulo — este archivo cubre solo la pieza ya construida y verificada."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

# Bootstrap de sys.path — este paquete vive fuera de `backend/`, así que si alguna vez se
# importa/corre sin pasar primero por `backend/api/main.py` (que ya agrega la raíz del repo a
# sys.path), los imports de `backend.*` de abajo fallarían. Idempotente (no duplica la entrada
# si ya está), mismo patrón que usan los scripts de `backend/scripts/*.py`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.api.db import analisis_repo  # noqa: E402
from backend.api.services import analisis_completo, gateway, ligas  # noqa: E402

from laplace_agents import consistencia, deriva, memoria, seleccion, votos  # noqa: E402

log = logging.getLogger("laplace_agents.core")

# Tope real de partidos analizados por corrida — protección contra un día con volumen inusual
# de partidos en ligas conocidas; con la cobertura real de hoy (~3-30 partidos/día en ligas
# conocidas, ver el registro de decisiones del proyecto) este tope no debería alcanzarse en la práctica, pero
# existe para no gastar cuota de API sin límite si `LIGAS` crece mucho.
CAP_PARTIDOS_POR_CORRIDA = 40

USUARIO_SISTEMA = "sistema_laplace_agents"

# `tipo_evento` reales que escribe este módulo en `laplace_agents.memoria` (ver
# `backend/api/models/laplace_agents.py::LaplaceAgentMemoria`) — constantes acá para que
# `deriva.py` y un futuro dashboard lean el mismo string exacto, sin repetirlo suelto.
TIPO_EVENTO_CICLO_DIARIO = "ciclo_diario"
TIPO_EVENTO_DERIVA_DETECTADA = "deriva_detectada"
# 2026-09-10 — este identificador ahora también tiene una fila real en `usuarios`
# (device_id="sistema_laplace_agents", rol="agente", ver backend/api/models/usuarios.py §v7)
# creada a mano contra la BD real — antes era solo un string suelto usado como `usuario_id` en
# `analisis_comparativo`/`jobs` (esas columnas no tienen FK a `usuarios`, ver
# INVESTIGACION_ARQUITECTURA_AGENTES_2026-09.md, así que el agente ya
# funcionaba sin esta fila) — se agrega para que el agente tenga una identidad real y
# listable en el futuro dashboard de admin, no solo un string.


def _partidos_candidatos(stages: list[dict]) -> list[dict]:
    """Un dict {match_id, local, visitante, liga} por partido real de liga conocida — mismo
    criterio de `es_liga_conocida` que ya usa el filtro de calidad de `top_picks.py`."""
    candidatos: list[dict] = []
    for stage in stages:
        liga = stage.get("Snm") or stage.get("CompN") or "Competición"
        if not ligas.es_liga_conocida(liga):
            continue
        for evento in stage.get("Events", []):
            match_id = str(evento.get("Eid") or "")
            if not match_id:
                continue
            local = (evento.get("T1") or [{}])[0].get("Nm", "Local")
            visitante = (evento.get("T2") or [{}])[0].get("Nm", "Visitante")
            candidatos.append({"match_id": match_id, "local": local, "visitante": visitante, "liga": liga})
    return candidatos


async def _ejecutar_un_dia(db: Session, client: httpx.AsyncClient, fecha: str) -> dict:
    """Ciclo real para UN día de fixtures (`fecha`, YYYY-MM-DD) — extraído 2026-09-10 de lo que
    antes era el cuerpo completo de `ejecutar_ciclo_autoevaluacion`, para poder correrlo dos
    veces (hoy + mañana) sin duplicar código, ver esa función más abajo. Nunca lanza: un fallo
    analizando UN partido no debe frenar el resto de la corrida (mismo criterio que
    `resultados_scheduler.py`)."""
    # `fecha` decide SOLO qué día de fixtures pedir — el chequeo de "ya existe" abajo usa una
    # fecha DISTINTA a propósito. `analisis_repo.guardar_analisis_multimodelo` (llamado vía
    # `analizar_y_persistir` más abajo) ignora cualquier `fecha` que se le pase y siempre
    # estampa `datetime.now()` real (fecha de negocio, campo deliberadamente no tocado por la
    # normalización a UTC de 2026-09-09 — ver docstring de `_now_str` en `analisis_repo.py`) —
    # es "cuándo se hizo el análisis", no "de qué día es el partido". Comparar
    # `existe_comparativo` contra `fecha` (que podría no ser hoy, ej. al procesar mañana) daría
    # siempre "no existe" y duplicaría filas — confirmado con un test real (`test_core.py`).
    fecha_livescore = fecha.replace("-", "")
    fecha_registro = datetime.now().strftime("%Y-%m-%d")

    stages, fuente_fixtures = await gateway.obtener_fixtures_cascada(db, client, fecha_livescore)
    candidatos = _partidos_candidatos(stages)

    # Filtrar "ya existe" ANTES de puntuar riqueza (2026-09-10) — es una consulta sync barata a
    # la BD local, y evita gastar llamadas reales de `gateway.buscar_fixture_id` (dentro de
    # `seleccion.priorizar_candidatos`) en partidos que de todas formas no se van a re-analizar.
    nuevos = [c for c in candidatos if not analisis_repo.existe_comparativo(db, c["match_id"], fecha_registro)]
    # Priorización por riqueza de datos (roadmap del README, 2026-09-10) — ver
    # `seleccion.py::priorizar_candidatos` para el criterio completo. Con el volumen real de hoy
    # (~3-30 partidos/día en ligas conocidas) el cap de abajo casi nunca se alcanza, así que esto
    # es sobre todo orden de prioridad, no exclusión — si algún día el volumen supera el cap, los
    # partidos con más datos reales ya quedaron analizados.
    nuevos_priorizados = await seleccion.priorizar_candidatos(db, client, nuevos, fecha_livescore)
    a_procesar = nuevos_priorizados[:CAP_PARTIDOS_POR_CORRIDA]

    analizados, errores = 0, 0
    detalle: list[dict] = []
    for c in a_procesar:
        # Trazabilidad de `fuente_goles` (detector de uniformidad, roadmap del README) — ver
        # docstring de `consistencia.obtener_fuente_goles` para por qué esto vuelve a llamar a
        # `h2h_fetch.obtener_h2h` en vez de leerlo de `analizar_y_persistir`. Se hace ANTES del
        # try/except de abajo a propósito: es una lectura de trazabilidad, no debe verse afectada
        # por si el análisis real termina en error.
        fuente_goles = await consistencia.obtener_fuente_goles(db, client, c)
        try:
            resultado = await analisis_completo.analizar_y_persistir(
                db, client,
                match_id=c["match_id"], local=c["local"], visitante=c["visitante"], liga=c["liga"],
                fecha=fecha_livescore, con_ia=False, usuario_id=USUARIO_SISTEMA,
            )
            analizados += 1
            detalle.append({
                "match_id": c["match_id"], "liga": c["liga"], "estado": "analizado",
                "pick_final": resultado.get("pick_final"), "fuente_goles": fuente_goles,
            })
        except Exception:
            errores += 1
            log.warning(
                "laplace_agents: fallo auto-analizando match_id=%s (%s vs %s, liga=%s)",
                c["match_id"], c["local"], c["visitante"], c["liga"], exc_info=True,
            )
            detalle.append({
                "match_id": c["match_id"], "liga": c["liga"], "estado": "error",
                "fuente_goles": fuente_goles,
            })

    resumen = {
        "fecha": fecha, "fuente_fixtures": fuente_fixtures,
        "candidatos_liga_conocida": len(candidatos), "ya_existian": len(candidatos) - len(nuevos),
        "nuevos_capados_a": len(a_procesar), "analizados": analizados, "errores": errores,
        "detalle": detalle,
    }
    resumen.update(consistencia.detectar_uniformidad(detalle))

    # Deriva entre corridas (roadmap del README, 2026-09-10) — compara la distribución de picks
    # de ESTA corrida contra la última registrada en la memoria propia del agente, ANTES de
    # sobreescribir esa memoria con la corrida actual (si no, se compararía contra sí misma).
    anterior = memoria.leer_ultimo_evento(db, tipo_evento=TIPO_EVENTO_CICLO_DIARIO)
    distribucion_anterior = anterior["resumen"].get("distribucion_picks") if anterior else None
    total_anterior = anterior["resumen"].get("total_analizados_con_pick") if anterior else None
    resumen["deriva"] = deriva.detectar_deriva(
        resumen["distribucion_picks"], distribucion_anterior,
        total_actual=resumen["total_analizados_con_pick"], total_anterior=total_anterior,
    )

    memoria.guardar_evento(
        db, tipo_evento=TIPO_EVENTO_CICLO_DIARIO, fecha=fecha,
        resumen={
            "distribucion_picks": resumen["distribucion_picks"],
            "total_analizados_con_pick": resumen["total_analizados_con_pick"],
            "alerta_uniformidad": resumen["alerta_uniformidad"],
        },
    )
    if resumen["deriva"]["alerta_deriva"]:
        memoria.guardar_evento(db, tipo_evento=TIPO_EVENTO_DERIVA_DETECTADA, fecha=fecha, resumen=resumen["deriva"])
        log.warning(
            "laplace_agents: DERIVA detectada fecha=%s pick=%s deltas=%s",
            fecha, resumen["deriva"]["pick_con_mayor_delta"], resumen["deriva"]["deltas"],
        )

    log.info(
        "laplace_agents: fecha=%s candidatos=%d ya_existian=%d analizados=%d errores=%d "
        "alerta_uniformidad=%s alerta_deriva=%s",
        fecha, len(candidatos), resumen["ya_existian"], analizados, errores,
        resumen["alerta_uniformidad"], resumen["deriva"]["alerta_deriva"],
    )
    return resumen


async def ejecutar_ciclo_autoevaluacion(
    db: Session, client: httpx.AsyncClient, fecha: str | None = None,
) -> dict:
    """Punto de entrada único — llamado por el cron diario (`backend/api/main.py`) y por el
    endpoint manual (`backend/api/routers/scheduler.py`).

    Con `fecha` explícita (uso de tests / disparo manual puntual): comportamiento sin cambios,
    un solo día — devuelve el resumen plano de `_ejecutar_un_dia`.

    Sin `fecha` (uso real del cron diario, 2026-09-10): procesa HOY y MAÑANA en la misma
    corrida, reusando `_ejecutar_un_dia` dos veces — verificar mañana además de hoy deja más
    partidos pre-analizados/cacheados antes de que un usuario real pregunte por ellos. El dict
    devuelto trae las claves planas de siempre (`analizados`, `candidatos_liga_conocida`,
    `errores`, etc.) como AGREGADO hoy+mañana — se preservan a propósito con los mismos nombres
    porque `backend/api/main.py::_job_laplace_agents` y `backend/api/routers/scheduler.py::
    disparar_laplace_agents` ya las leen en forma plana (confirmado leyendo ambos archivos
    2026-09-10) y esta ronda de trabajo no puede tocarlos (fuera del alcance de archivos
    permitidos) — más las claves `"hoy"`/`"mañana"` anidadas con el resumen completo de cada
    día por separado (incluye su propio detector de uniformidad — mezclar hoy+mañana en una
    sola distribución de picks escondería una anomalía real de un solo día).

    En ambas ramas se agrega `comparacion_usuarios_vs_motor` (roadmap del README, 2026-09-10) —
    lee los votos reales de `/encuesta` (tabla `predicciones_usuario`) para partidos YA
    resueltos y los compara contra el acierto real del motor. Se calcula UNA sola vez acá (no
    dentro de `_ejecutar_un_dia`, que corre hasta dos veces por corrida) porque no depende de
    `fecha` — recorre todos los partidos con voto real, sin filtro de día (ver
    `votos.comparar_votos_vs_motor`)."""
    if fecha is not None:
        resumen = await _ejecutar_un_dia(db, client, fecha)
        resumen["comparacion_usuarios_vs_motor"] = votos.comparar_votos_vs_motor(db)
        return resumen

    hoy = datetime.now().strftime("%Y-%m-%d")
    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    resumen_hoy = await _ejecutar_un_dia(db, client, hoy)
    resumen_manana = await _ejecutar_un_dia(db, client, manana)

    return {
        "candidatos_liga_conocida": resumen_hoy["candidatos_liga_conocida"] + resumen_manana["candidatos_liga_conocida"],
        "ya_existian": resumen_hoy["ya_existian"] + resumen_manana["ya_existian"],
        "nuevos_capados_a": resumen_hoy["nuevos_capados_a"] + resumen_manana["nuevos_capados_a"],
        "analizados": resumen_hoy["analizados"] + resumen_manana["analizados"],
        "errores": resumen_hoy["errores"] + resumen_manana["errores"],
        "detalle": resumen_hoy["detalle"] + resumen_manana["detalle"],
        "hoy": resumen_hoy,
        "mañana": resumen_manana,
        "comparacion_usuarios_vs_motor": votos.comparar_votos_vs_motor(db),
    }
