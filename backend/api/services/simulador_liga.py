"""
services/simulador_liga.py — Simulador de liga Monte Carlo.

Idea tomada de la auditoría de proyectos de referencia (`docs/referencia/proyectos-externos/
soccer-prediction-model.md`, §5.1 "Simulador de liga con Monte Carlo") — la única pieza de valor
real de ese repo externo (el resto: modelo XGBoost degenerado, 36.7% accuracy). La idea en sí es
matemática pura sobre datos que Laplace YA produce: no hace falta ningún dato ni modelo nuevo,
solo agregar las probabilidades 1X2 que ya calcula `services/pronostico.py` (vía
`services/motor.py::analizar_partido`) sobre el resto de partidos pendientes de una temporada.

Dos funciones, dos responsabilidades:
  - `simular_temporada()` — pura, sin I/O. Recibe probabilidades YA resueltas y una tabla de
    puntos actual, corre N simulaciones Monte Carlo y agrega probabilidades de campeón/copa/
    descenso. Testeable sin red ni BD (ver `backend/tests/test_simulador_liga.py`).
  - `simular_liga_actual()` — orquestador async. Arma `partidos_pendientes`/`tabla_actual` reales
    (fixtures + standings de api-football, mismo patrón que ya usa `services/top_picks.py`) y
    llama a `simular_temporada()`.

Limitación conocida y documentada (no oculta — ver `.claude/rules/product-philosophy.md`): el
desempate entre equipos con los mismos puntos simulados es alfabético, no por diferencia de gol
(la tarea pedía sumar puntos de tabla 3-1-0 por simulación, no simular marcadores) — con miles de
simulaciones el sesgo de ese desempate sobre `prob_campeon`/`prob_copa`/`prob_descenso` es
marginal, pero existe y se documenta acá en vez de presentarlo como una probabilidad exacta.

## Descenso por promedio multi-temporada (Liga Profesional Argentina, AFA) — capa adicional

Investigado 2026-09-08 (ver `PLAN_ESTRATEGICO_2026-09.md` §1 ítem 3 y §5 ítem
12): la regla real de descenso del fútbol argentino no mira solo la tabla de la temporada actual
— desciende el equipo con el promedio más bajo de puntos-por-partido sobre una ventana de varias
temporadas (temporada actual + N previas). Confirmado EMPÍRICAMENTE (llamada real a
api-football, no solo lectura de docs) que el mecanismo para pedir standings de temporadas
anteriores YA EXISTE hoy: el endpoint `standings` de api-football ya acepta `season` como
parámetro arbitrario (mismo que usa `_tabla_y_posiciones()` para la temporada actual) y
efectivamente devuelve datos reales de temporadas pasadas — con una limitación real del plan
free vigente hoy (2026-09-08): solo expone una ventana rodante de temporadas ya completadas
(hoy: 2022-2024 — la temporada "actual" 2025/2026 da `errors.plan` en vez de datos, lo cual
además significa que TODO `simular_liga_actual()`, no solo esta capa nueva, depende de que
api-football cubra la temporada que se le pide). Esa ventana se corre con el tiempo (plan free
de api-football), así que se consulta en runtime, nunca se hardcodea qué temporadas están
disponibles — un equipo sin historial en la ventana vigente (recién ascendido, o temporada fuera
de rango) simplemente usa 0 puntos/0 partidos de esa temporada previa (equivalente real: un
equipo con menos de N temporadas de historia solo promedia las que tiene).

Por eso esta regla es una CAPA ADICIONAL (no reemplaza el Monte Carlo de la tabla actual):
`simular_temporada()` acepta `historial_multi_temporada`/`partidos_jugados_actual` opcionales
(`None` por defecto — CERO cambio de comportamiento para las demás ligas, que nunca pasan estos
parámetros) y, solo cuando vienen, agrega el campo extra `prob_descenso_por_promedio` por
equipo — una probabilidad Monte Carlo real (se recalcula en cada una de las N simulaciones,
combinando los puntos/partidos históricos reales con los puntos simulados de la temporada
actual), no un único valor determinístico basado en el promedio agregado.

`LIGA_ARGENTINA_SLUG`/`LIGA_ARGENTINA_LEAGUE_ID` (abajo) son locales a este archivo — el id 128
de api-football para la Liga Profesional Argentina NO está hoy en
`top_picks.LIGA_SLUG_POR_ID` (aunque sí está en `top_picks.LIGAS_PREMIUM`, usado para otra cosa).
Agregar esa entrada es un cambio de `top_picks.py`, fuera del alcance de esta ronda (alcance:
solo este archivo y sus tests) — queda pendiente para quien mantenga ese archivo.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from backend.api.services import motor
from backend.api.services.top_picks import _apif_get, _team_stats_cacheado, LIGA_SLUG_POR_ID

log = logging.getLogger("laplace.simulador_liga")

DEFAULT_N_SIMULACIONES = 10_000
DEFAULT_POSICIONES_COPA = 4
DEFAULT_POSICIONES_DESCENSO = 3
DEFAULT_N_TEMPORADAS_HISTORIAL_DESCENSO = 2

# Reverso de `top_picks.LIGA_SLUG_POR_ID` (id api-football -> slug) — mismo mapa, una sola
# fuente de verdad (no se duplica la tabla acá).
LEAGUE_ID_POR_SLUG: dict[str, int] = {slug: league_id for league_id, slug in LIGA_SLUG_POR_ID.items()}

# Liga Profesional Argentina (AFA) — id real de api-football, confirmado empíricamente 2026-09-08
# (llamada real a `standings?league=128&season=2024` -> "Liga Profesional Argentina"). Local a
# este archivo — ver docstring del módulo, sección "Descenso por promedio multi-temporada", para
# el porqué no vive en `top_picks.LIGA_SLUG_POR_ID`.
LIGA_ARGENTINA_SLUG = "liga_profesional"
LIGA_ARGENTINA_LEAGUE_ID = 128


def _resultado_ponderado(rng: random.Random, prob_local: float, prob_empate: float, prob_visitante: float) -> str:
    """Elige 'local'/'empate'/'visitante' ponderado por las 3 probabilidades. `random.choices`
    normaliza pesos automáticamente (no hace falta que sumen exactamente 1.0), pero si las tres
    llegan en 0 (dato roto) cae a equiprobable en vez de lanzar ValueError."""
    pesos = [max(prob_local, 0.0), max(prob_empate, 0.0), max(prob_visitante, 0.0)]
    if sum(pesos) <= 0:
        pesos = [1.0, 1.0, 1.0]
    return rng.choices(["local", "empate", "visitante"], weights=pesos)[0]


def _partidos_pendientes_por_equipo(partidos_pendientes: list[dict]) -> dict[str, int]:
    """Cuenta cuántos partidos pendientes tiene cada equipo — es el mismo para las
    `n_simulaciones` (no depende de qué resultado salga), así que se calcula una sola vez fuera
    del loop de Monte Carlo."""
    conteo: dict[str, int] = {}
    for p in partidos_pendientes:
        conteo[p["local"]] = conteo.get(p["local"], 0) + 1
        conteo[p["visitante"]] = conteo.get(p["visitante"], 0) + 1
    return conteo


def _equipos_en_zona_descenso_por_promedio(
    puntos_temporada_actual: dict[str, int],
    historial_multi_temporada: dict[str, dict[str, int]],
    partidos_totales_temporada_actual: dict[str, int],
    posiciones_descenso_promedio: int,
) -> set[str]:
    """Para UNA simulación: combina los puntos/partidos reales de temporadas previas
    (`historial_multi_temporada`) con los puntos simulados de la temporada actual
    (`puntos_temporada_actual`) y devuelve el conjunto de equipos en zona de descenso según el
    promedio de puntos-por-partido de la ventana completa — la regla real de descenso del fútbol
    argentino (AFA), en vez de la posición pura de la tabla de la temporada actual.

    Un equipo sin entrada en `historial_multi_temporada` (recién ascendido, o sin standings
    disponibles para esa temporada en el plan actual de api-football) promedia solo con los
    puntos/partidos de la temporada actual — mismo criterio real que usa AFA para equipos con
    menos de N temporadas de historia."""
    equipos = set(puntos_temporada_actual.keys())
    promedios: dict[str, float] = {}
    for equipo in equipos:
        historial = historial_multi_temporada.get(equipo, {"puntos": 0, "partidos": 0})
        puntos_ventana = historial.get("puntos", 0) + puntos_temporada_actual[equipo]
        partidos_ventana = historial.get("partidos", 0) + partidos_totales_temporada_actual.get(equipo, 0)
        # Sin partidos en toda la ventana (caso degenerado, no debería pasar en la práctica): se
        # manda al fondo de la tabla de promedios en vez de dividir por cero.
        promedios[equipo] = puntos_ventana / partidos_ventana if partidos_ventana > 0 else -1.0

    orden = sorted(equipos, key=lambda e: promedios[e])
    n = max(0, min(posiciones_descenso_promedio, len(orden)))
    return set(orden[:n])


def simular_temporada(
    partidos_pendientes: list[dict],
    tabla_actual: dict[str, int],
    n_simulaciones: int = DEFAULT_N_SIMULACIONES,
    posiciones_copa: int = DEFAULT_POSICIONES_COPA,
    posiciones_descenso: int = DEFAULT_POSICIONES_DESCENSO,
    seed: int | None = None,
    historial_multi_temporada: dict[str, dict[str, int]] | None = None,
    partidos_jugados_actual: dict[str, int] | None = None,
) -> dict[str, dict]:
    """Monte Carlo puro: dado el resto de partidos de la temporada (con las 3 probabilidades
    1X2 ya resueltas) y la tabla de puntos actual, simula `n_simulaciones` temporadas completas
    y devuelve, por equipo, la fracción de simulaciones en las que terminó campeón / en zona de
    copa continental / en zona de descenso, más su posición promedio.

    `partidos_pendientes`: lista de `{local, visitante, prob_local, prob_empate, prob_visitante}`.
    `tabla_actual`: `{equipo: puntos_actuales}` — un equipo sin partidos pendientes ni entrada acá
    se ignora (no puede pasar en la práctica: `simular_liga_actual()` arma ambos desde la misma
    fuente real).
    `posiciones_copa`: cuántos puestos desde arriba cuentan como clasificación a copa (top N).
    `posiciones_descenso`: cuántos puestos desde el fondo cuentan como descenso (últimos N).
    `seed`: fija `random.Random(seed)` para simulaciones determinísticas (tests); `None` usa
    entropía real del sistema (uso en producción vía `simular_liga_actual()`).

    `historial_multi_temporada`/`partidos_jugados_actual`: CAPA ADICIONAL opcional (ver docstring
    del módulo) — solo la usa `simular_liga_actual()` para la Liga Profesional Argentina. Cuando
    `historial_multi_temporada` es `None` o vacío (default), el comportamiento es IDÉNTICO al de
    antes de esta capa — ninguna liga existente cambia. Cuando viene con datos, cada equipo
    devuelto agrega `prob_descenso_por_promedio`: la fracción de simulaciones en las que ese
    equipo queda en la zona de descenso por promedio de puntos-por-partido multi-temporada (usa
    la misma cantidad de puestos que `posiciones_descenso`, para no introducir un parámetro
    adicional sin una regla AFA vigente confirmada que justifique un número distinto).
    """
    equipos = set(tabla_actual.keys())
    for p in partidos_pendientes:
        equipos.add(p["local"])
        equipos.add(p["visitante"])
    equipos = sorted(equipos)
    n_equipos = len(equipos)

    if n_equipos == 0 or n_simulaciones <= 0:
        return {}

    rng = random.Random(seed)

    contador_campeon = {e: 0 for e in equipos}
    contador_copa = {e: 0 for e in equipos}
    contador_descenso = {e: 0 for e in equipos}
    suma_posiciones = {e: 0 for e in equipos}

    posiciones_copa_clamped = max(0, min(posiciones_copa, n_equipos))
    posiciones_descenso_clamped = max(0, min(posiciones_descenso, n_equipos))
    umbral_descenso = n_equipos - posiciones_descenso_clamped  # posición (1-based) desde la que ya es descenso

    usar_descenso_por_promedio = bool(historial_multi_temporada)
    if usar_descenso_por_promedio:
        pendientes_por_equipo = _partidos_pendientes_por_equipo(partidos_pendientes)
        jugados_actual = partidos_jugados_actual or {}
        partidos_totales_temporada_actual = {
            e: jugados_actual.get(e, 0) + pendientes_por_equipo.get(e, 0) for e in equipos
        }
        contador_descenso_promedio = {e: 0 for e in equipos}

    for _ in range(n_simulaciones):
        puntos = {e: tabla_actual.get(e, 0) for e in equipos}

        for partido in partidos_pendientes:
            resultado = _resultado_ponderado(
                rng, partido["prob_local"], partido["prob_empate"], partido["prob_visitante"]
            )
            if resultado == "local":
                puntos[partido["local"]] += 3
            elif resultado == "visitante":
                puntos[partido["visitante"]] += 3
            else:
                puntos[partido["local"]] += 1
                puntos[partido["visitante"]] += 1

        # Desempate alfabético — ver limitación documentada en el docstring del módulo.
        tabla_final = sorted(equipos, key=lambda e: (-puntos[e], e))

        for posicion, equipo in enumerate(tabla_final, start=1):
            suma_posiciones[equipo] += posicion
            if posicion == 1:
                contador_campeon[equipo] += 1
            if posicion <= posiciones_copa_clamped:
                contador_copa[equipo] += 1
            if posicion > umbral_descenso:
                contador_descenso[equipo] += 1

        if usar_descenso_por_promedio:
            zona_promedio = _equipos_en_zona_descenso_por_promedio(
                puntos, historial_multi_temporada, partidos_totales_temporada_actual, posiciones_descenso_clamped
            )
            for equipo in zona_promedio:
                contador_descenso_promedio[equipo] += 1

    return {
        equipo: {
            "prob_campeon": round(contador_campeon[equipo] / n_simulaciones, 4),
            "prob_copa": round(contador_copa[equipo] / n_simulaciones, 4),
            "prob_descenso": round(contador_descenso[equipo] / n_simulaciones, 4),
            "posicion_promedio": round(suma_posiciones[equipo] / n_simulaciones, 2),
            **(
                {"prob_descenso_por_promedio": round(contador_descenso_promedio[equipo] / n_simulaciones, 4)}
                if usar_descenso_por_promedio
                else {}
            ),
        }
        for equipo in equipos
    }


def _construir_payload_motor(fixture: dict, liga_nombre: str, posiciones: dict[str, int],
                              goles_avg: dict[str, dict[str, float]]) -> dict:
    """Arma el dict de entrada de `motor.analizar_partido()` (mismo contrato que
    `AnalisisInput`/lo que ya arma `top_picks._analizar_candidato()`) a partir de un fixture
    pendiente de api-football + tabla de posiciones + promedios de gol por equipo (cacheados)."""
    local = fixture.get("teams", {}).get("home", {}).get("name", "Local")
    visitante = fixture.get("teams", {}).get("away", {}).get("name", "Visitante")

    stats_local = goles_avg.get(local, {})
    stats_visit = goles_avg.get(visitante, {})

    return {
        "local": local,
        "visitante": visitante,
        "liga": liga_nombre,
        "partido_id": str(fixture.get("fixture", {}).get("id", "")),
        "goles_local_avg": stats_local.get("favor"),
        "goles_visit_avg": stats_visit.get("favor"),
        "goles_contra_local_avg": stats_local.get("contra"),
        "goles_contra_visit_avg": stats_visit.get("contra"),
        "pos_local": posiciones.get(local, 10),
        "pos_visit": posiciones.get(visitante, 10),
        # H2H/odds no se resuelven acá (costaría 1-2 llamadas extra a api-football por partido
        # pendiente, sobre una temporada completa) — `motor.analizar_partido()` ya maneja esto
        # vía `validar_h2h`/`validar_odds` (skip limpio, no lanza), y el módulo poisson (el que
        # usa este simulador) no los necesita para calcular prob_local/prob_empate/prob_visitante.
        "h2h_disponible": False,
        "odds_disponibles": False,
    }


async def _tabla_y_posiciones(
    client: httpx.AsyncClient, league_id: int, season: int
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Standings reales de api-football: `(tabla_actual, posiciones, partidos_jugados)` —
    `tabla_actual` son los puntos actuales por equipo (semilla de `simular_temporada`),
    `posiciones` es el rank actual (se usa como input del módulo `tabla` de `pronostico.py` vía
    `pos_local`/`pos_visit`), `partidos_jugados` es el campo `all.played` de standings — solo lo
    usa hoy la capa de descenso por promedio multi-temporada (Liga Argentina), se extrae siempre
    acá para no duplicar esta misma llamada a api-football."""
    data = (await _apif_get(client, f"standings?league={league_id}&season={season}")).get("response") or []
    grupos = (data[0].get("league", {}).get("standings") or [[]]) if data else [[]]
    filas = grupos[0] if grupos else []

    tabla_actual = {fila["team"]["name"]: fila.get("points", 0) for fila in filas if fila.get("team")}
    posiciones = {fila["team"]["name"]: fila.get("rank", 10) for fila in filas if fila.get("team")}
    partidos_jugados = {
        fila["team"]["name"]: (fila.get("all") or {}).get("played", 0) for fila in filas if fila.get("team")
    }
    return tabla_actual, posiciones, partidos_jugados


async def _historial_multi_temporada(
    client: httpx.AsyncClient, league_id: int, season_actual: int, n_temporadas: int
) -> dict[str, dict[str, int]]:
    """Suma puntos y partidos jugados de las `n_temporadas` temporadas ANTERIORES a
    `season_actual` (season_actual-1, season_actual-2, ...) para `league_id`, vía el mismo
    endpoint `standings` que ya usa `_tabla_y_posiciones()` — el parámetro `season` ya es
    genérico ahí, no hace falta ningún endpoint nuevo (confirmado empíricamente 2026-09-08, ver
    docstring del módulo). Una temporada sin datos disponibles en el plan actual de api-football
    (`response` vacío) se salta en silencio — un equipo sin ninguna temporada disponible queda
    simplemente sin entrada en el dict devuelto (`_equipos_en_zona_descenso_por_promedio` ya
    maneja ese caso: promedia solo con la temporada actual)."""
    acumulado: dict[str, dict[str, int]] = {}
    for offset in range(1, n_temporadas + 1):
        season = season_actual - offset
        data = (await _apif_get(client, f"standings?league={league_id}&season={season}")).get("response") or []
        grupos = (data[0].get("league", {}).get("standings") or [[]]) if data else [[]]
        filas = grupos[0] if grupos else []
        for fila in filas:
            equipo = (fila.get("team") or {}).get("name")
            if not equipo:
                continue
            entry = acumulado.setdefault(equipo, {"puntos": 0, "partidos": 0})
            entry["puntos"] += fila.get("points", 0) or 0
            entry["partidos"] += (fila.get("all") or {}).get("played", 0) or 0
    return acumulado


async def _goles_avg_por_equipo(db: Session, client: httpx.AsyncClient, equipos_ids: dict[str, int],
                                 league_id: int, season: int) -> dict[str, dict[str, float]]:
    """Promedio de goles a favor/en contra por equipo, vía el mismo caché de
    `top_picks._team_stats_cacheado()` (TTL 48h) — evita repetir la llamada a
    `teams/statistics` cuando el mismo equipo aparece en varios partidos pendientes."""
    resultado: dict[str, dict[str, float]] = {}
    for nombre_equipo, team_id in equipos_ids.items():
        if not team_id:
            continue
        st = await _team_stats_cacheado(db, client, team_id, league_id, season)
        if not st:
            continue
        gf = st.get("goals", {}).get("for", {}).get("average", {}).get("total")
        ga = st.get("goals", {}).get("against", {}).get("average", {}).get("total")
        resultado[nombre_equipo] = {
            "favor": float(gf) if gf else None,
            "contra": float(ga) if ga else None,
        }
    return resultado


async def simular_liga_actual(
    db: Session,
    client: httpx.AsyncClient,
    liga_slug: str,
    n_simulaciones: int = DEFAULT_N_SIMULACIONES,
    posiciones_copa: int = DEFAULT_POSICIONES_COPA,
    posiciones_descenso: int = DEFAULT_POSICIONES_DESCENSO,
    n_temporadas_historial: int = DEFAULT_N_TEMPORADAS_HISTORIAL_DESCENSO,
) -> dict:
    """Orquestador real: arma `partidos_pendientes`/`tabla_actual` de la liga+temporada actual
    (fixtures NS + standings de api-football, mismo patrón de fetch que `services/top_picks.py`)
    y llama a `simular_temporada()`. Sin `seed` — usa entropía real (a diferencia de los tests,
    que sí fijan seed para ser determinísticos).

    Devuelve `{"ok": False, "razon": ...}` si el slug no mapea a una liga conocida o no hay
    standings/fixtures pendientes disponibles — nunca lanza (mismo criterio que
    `standings_fetch.obtener_standings()`).

    `n_temporadas_historial`: solo aplica cuando `liga_slug == LIGA_ARGENTINA_SLUG` — cuántas
    temporadas previas se suman para la capa de descenso por promedio multi-temporada (ver
    docstring del módulo). Ignorado para el resto de las ligas."""
    league_id = LEAGUE_ID_POR_SLUG.get(liga_slug)
    if league_id is None and liga_slug == LIGA_ARGENTINA_SLUG:
        league_id = LIGA_ARGENTINA_LEAGUE_ID
    if league_id is None:
        return {"ok": False, "razon": f"liga_slug desconocido: {liga_slug}"}

    season = datetime.now().year

    tabla_actual, posiciones, partidos_jugados = await _tabla_y_posiciones(client, league_id, season)
    if not tabla_actual:
        return {"ok": False, "razon": "Sin standings disponibles para esta liga/temporada"}

    fixtures_data = await _apif_get(client, f"fixtures?league={league_id}&season={season}&status=NS")
    fixtures = fixtures_data.get("response", [])
    if not fixtures:
        return {"ok": False, "razon": "Sin partidos pendientes para esta liga/temporada"}

    liga_nombre = fixtures[0].get("league", {}).get("name", liga_slug)

    equipos_ids: dict[str, int] = {}
    for f in fixtures:
        home, away = f.get("teams", {}).get("home", {}), f.get("teams", {}).get("away", {})
        if home.get("name") and home.get("id"):
            equipos_ids[home["name"]] = home["id"]
        if away.get("name") and away.get("id"):
            equipos_ids[away["name"]] = away["id"]

    goles_avg = await _goles_avg_por_equipo(db, client, equipos_ids, league_id, season)

    partidos_pendientes = []
    for f in fixtures:
        payload = _construir_payload_motor(f, liga_nombre, posiciones, goles_avg)
        resultado = motor.analizar_partido(payload)
        poisson = resultado["modulos"]["poisson"]
        partidos_pendientes.append({
            "local": payload["local"],
            "visitante": payload["visitante"],
            "prob_local": poisson["prob_local"],
            "prob_empate": poisson["prob_empate"],
            "prob_visitante": poisson["prob_visitante"],
        })

    es_liga_argentina = liga_slug == LIGA_ARGENTINA_SLUG
    historial_multi_temporada = None
    if es_liga_argentina:
        historial_multi_temporada = await _historial_multi_temporada(
            client, league_id, season, n_temporadas_historial
        )

    tabla_simulada = simular_temporada(
        partidos_pendientes, tabla_actual, n_simulaciones, posiciones_copa, posiciones_descenso,
        historial_multi_temporada=historial_multi_temporada,
        partidos_jugados_actual=partidos_jugados,
    )

    resultado = {
        "ok": True,
        "liga_slug": liga_slug,
        "liga_nombre": liga_nombre,
        "season": season,
        "n_simulaciones": n_simulaciones,
        "partidos_pendientes": len(partidos_pendientes),
        "posiciones_copa": posiciones_copa,
        "posiciones_descenso": posiciones_descenso,
        "tabla": tabla_simulada,
    }

    if es_liga_argentina:
        resultado["n_temporadas_historial"] = n_temporadas_historial
        resultado["descenso_por_promedio_multi_temporada"] = bool(historial_multi_temporada)
        if not historial_multi_temporada:
            # Honesto en vez de silencioso (ver `.claude/rules/product-philosophy.md`): no hay
            # standings de temporadas anteriores disponibles hoy (ventana rodante del plan free
            # de api-football, ver docstring del módulo) — la tabla sigue siendo el Monte Carlo
            # normal de la temporada actual, sin `prob_descenso_por_promedio` por equipo.
            resultado["aviso_descenso_por_promedio"] = (
                "Sin standings de temporadas anteriores disponibles hoy para esta liga en el "
                "plan actual de api-football — prob_descenso_por_promedio no se calculó."
            )

    return resultado
