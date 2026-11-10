"""laplace_agents/consistencia.py — detector de uniformidad de picks + trazabilidad de
`fuente_goles`, automatizando el chequeo que se hizo A MANO el 2026-09-10 (ver `.memory/
decisiones.md` y `README.md` de este paquete: 92.6% → 56.7% de picks "Empate" en un día real,
tras conectar `team_stats_fetch.py` como fallback intermedio).

## Por qué `obtener_fuente_goles` vuelve a llamar a `h2h_fetch.obtener_h2h`

Se leyó completo `backend/api/services/analisis_completo.py` (2026-09-10) para decidir el punto
de integración con menor acoplamiento posible. Resultado real: `fuente_goles` (la clave que
arma `services/h2h_fetch.py::obtener_h2h` — "h2h_real" > "stats_equipo_real" > "liga_generico")
se USA dentro de `_enriquecer_partido` (para elegir `goles_local_avg`/`goles_visit_avg`) pero
la clave en sí NUNCA sale de esa función: no está en el dict `d` que arma `_enriquecer_partido`,
no está en el resultado que devuelve `analizar_y_persistir`, y no se persiste en ninguna
columna de `AnalisisComparativo`/`AnalisisModulo` (confirmado leyendo `_persistir()` y
`motor.py::analizar_partido` completos). No hay ningún punto de integración existente que la
exponga sin tocar `backend/` — y esta ronda de trabajo tiene ese archivo fuera de alcance (solo
lectura permitida). La única forma real de leer `fuente_goles` desde acá es volver a llamar a
`h2h_fetch.obtener_h2h` con los mismos argumentos que ya usa `_enriquecer_partido` — es la
función pública real (mismo contrato que ya prueba `backend/tests/test_h2h_fetch.py`), no una
reimplementación de su lógica interna.

**Costo real aceptado, medido leyendo el código fuente de `h2h_fetch.py`:** cuando el partido SÍ
tiene H2H real (vía api-football, cacheado 7 días) o cuando cae al fallback de stats de equipo
(vía `team_stats_fetch.py`, cacheado 24h), esta llamada extra pega caché — el trabajo real ya lo
hizo la primera vez que se resuelve (sea acá o dentro de `analizar_y_persistir`, el orden no
importa, ambas rutas comparten la misma caché en `stats_cache`). El único caso con costo real
duplicado es cuando NO hay H2H real: `_apifootball_h2h` solo cachea si encontró fixtures (nunca
cachea un resultado vacío) y `_bsd_h2h` no cachea nunca — así que un partido sin H2H real paga 2
llamadas HTTP de más (api-football H2H + BSD H2H) por esta función. Se acepta a propósito con el
volumen real de hoy (~3-30 partidos/día en ligas conocidas, ver el registro de decisiones del proyecto) — la
alternativa correcta de fondo (exponer `fuente_goles` en el retorno real de `analizar_y_persistir`,
un cambio de una línea en `analisis_completo.py`) queda fuera de alcance de esta ronda por la
restricción de archivos tocables; si el volumen crece mucho, ESE es el fix real, no optimizar
esta función."""
from __future__ import annotations

from collections import Counter

import httpx
from sqlalchemy.orm import Session

from backend.api.services import h2h_fetch, ligas

# Sin muestra mínima, un batch de 1-2 partidos con el mismo pick dispararía una alerta sin
# significado real (con 2 partidos, "100% Local" no dice nada sobre uniformidad del motor).
MUESTRA_MINIMA_PARA_ALERTA = 5
# 75%: entre el 70-80% que pidió el roadmap — documentado como punto medio, no un valor
# calibrado con datos reales (no hay volumen real todavía para calibrarlo empíricamente).
UMBRAL_PORCENTAJE_ALERTA = 0.75

FUENTE_GOLES_DESCONOCIDA = "desconocido"


async def obtener_fuente_goles(
    db: Session, client: httpx.AsyncClient, candidato: dict, liga_avg_input: float = 2.60,
) -> str:
    """`candidato` debe traer `fixture_info` (ya lo agrega `seleccion.priorizar_candidatos`) y
    `local`/`visitante`/`liga`. Nunca lanza — un fallo acá es solo pérdida de trazabilidad para
    el reporte de esta corrida, no debe frenar el análisis real del partido (mismo criterio que
    el resto de `core.py`: un fallo aislado no frena el resto)."""
    fixture_info = candidato.get("fixture_info") or {}
    liga = candidato["liga"]
    league_id = fixture_info.get("apifootball_league_id")
    season = fixture_info.get("apifootball_season")
    liga_avg, _tabla, _odds = ligas.resolver_liga_por_id(league_id, liga, liga_avg_input)
    try:
        resultado = await h2h_fetch.obtener_h2h(
            client, db,
            fixture_info.get("apifootball_team_home"), fixture_info.get("apifootball_team_away"),
            candidato["local"], candidato["visitante"], liga, liga_avg,
            league_id=league_id, season=season,
        )
        return resultado.get("fuente_goles", FUENTE_GOLES_DESCONOCIDA)
    except Exception:
        return FUENTE_GOLES_DESCONOCIDA


def detectar_uniformidad(detalle: list[dict]) -> dict:
    """Distribución real de `pick_final` (y de `fuente_goles`) entre los partidos ANALIZADOS de
    esta corrida (`estado == "analizado"`), más una alerta si el pick dominante supera
    `UMBRAL_PORCENTAJE_ALERTA` — solo si la muestra es de al menos `MUESTRA_MINIMA_PARA_ALERTA`
    partidos (con menos, no hay muestra suficiente para que la alerta signifique algo real, ver
    docstring de `MUESTRA_MINIMA_PARA_ALERTA`)."""
    analizados = [d for d in detalle if d.get("estado") == "analizado" and d.get("pick_final")]
    total = len(analizados)
    distribucion_picks = dict(Counter(d["pick_final"] for d in analizados))
    distribucion_fuente_goles = dict(
        Counter(d.get("fuente_goles", FUENTE_GOLES_DESCONOCIDA) for d in analizados)
    )

    alerta_uniformidad = False
    pick_dominante = None
    if total >= MUESTRA_MINIMA_PARA_ALERTA and distribucion_picks:
        pick_dominante, conteo_dominante = max(distribucion_picks.items(), key=lambda kv: kv[1])
        if conteo_dominante / total >= UMBRAL_PORCENTAJE_ALERTA:
            alerta_uniformidad = True
        else:
            pick_dominante = None

    return {
        "total_analizados_con_pick": total,
        "distribucion_picks": distribucion_picks,
        "alerta_uniformidad": alerta_uniformidad,
        "pick_dominante_si_hay_alerta": pick_dominante,
        "distribucion_fuente_goles": distribucion_fuente_goles,
    }
