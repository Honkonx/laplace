"""services/tabla_propia.py — tabla de posiciones construida con los resultados propios (maestro + resultados actuales + los del bot).

El plan gratis de API-Football no trae la temporada en curso y football-data.org necesita clave: sin ellos el módulo `tabla` casi nunca aportaba (4 de 29 ligas en los análisis guardados). Con los
resultados que ya tenemos se calcula la misma tabla, con la forma de `standings` de football-data.org para que el resto del flujo no cambie.

Solo se devuelve una tabla cuando se puede confiar en ella: la liga es de todos contra todos y la temporada anterior estaba completa (así se sabe cuántos equipos son), la actual ya tiene a todos y su
último resultado es reciente. Si algo falla, devuelve None y el análisis sigue sin tabla, como antes: una tabla incompleta daría posiciones falsas.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

log = logging.getLogger("laplace.tabla_propia")

MAX_ATRASO_DIAS = 10  # si el último resultado de la liga es más viejo, la tabla sería de otro momento
FORMA_PARTIDOS = 5


def _resultado(gf: int, gc: int) -> str:
    return "W" if gf > gc else "D" if gf == gc else "L"


def construir(local: str, visitante: str, liga: str, hoy: date | None = None, partidos: list[dict] | None = None) -> dict | None:
    """Tabla en forma de `standings` de football-data.org con `fuente: resultados_propios`, o None si no se puede confiar en ella.

    Los dos equipos del partido aparecen con los nombres del partido actual (así el cruce posterior es exacto); el resto, con su nombre canónico."""
    from backend.api.services import modelo_historico, simulador_propio

    try:
        r = modelo_historico._resolver({"liga": liga, "local": local, "visitante": visitante})  # noqa: SLF001 — mismo resolutor del consenso
        if not r or not r[0]:
            return None
        codigo, _modelo, canon_local, canon_visitante = r
        todos = [p for p in (partidos if partidos is not None else simulador_propio._partidos()) if p["liga"] == codigo]  # noqa: SLF001
        if not todos:
            return None
        actual = max(p["temporada"] for p in todos)
        jugados = sorted((p for p in todos if p["temporada"] == actual), key=lambda p: (p["dia"], p["local"]))
        if (hoy or date.today()).toordinal() - jugados[-1]["dia"] > MAX_ATRASO_DIAS:
            return None
        previas = sorted({p["temporada"] for p in todos if p["temporada"] < actual}, reverse=True)
        n_esperado = next((n for t in previas if (n := simulador_propio._temporada_completa([p for p in todos if p["temporada"] == t]))), None)  # noqa: SLF001
        equipos = {p["local"] for p in jugados} | {p["visitante"] for p in jugados}
        if not n_esperado or len(equipos) != n_esperado or canon_local not in equipos or canon_visitante not in equipos:
            return None
        filas: dict[str, dict] = defaultdict(lambda: {"pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "forma": []})
        for p in jugados:
            for eq, gf, gc in ((p["local"], p["gl"], p["gv"]), (p["visitante"], p["gv"], p["gl"])):
                f = filas[eq]
                f["pj"] += 1
                f["gf"] += gf
                f["gc"] += gc
                res = _resultado(gf, gc)
                f["g" if res == "W" else "e" if res == "D" else "p"] += 1
                f["forma"].append(res)
        orden = sorted(filas, key=lambda eq: (-(3 * filas[eq]["g"] + filas[eq]["e"]), -(filas[eq]["gf"] - filas[eq]["gc"]), -filas[eq]["gf"], eq))
        nombres = {canon_local: local, canon_visitante: visitante}
        tabla = [{"position": i, "team": {"name": nombres.get(eq, eq)}, "playedGames": f["pj"], "won": f["g"], "draw": f["e"], "lost": f["p"], "points": 3 * f["g"] + f["e"],
                  "goalsFor": f["gf"], "goalsAgainst": f["gc"], "goalDifference": f["gf"] - f["gc"], "form": ",".join(f["forma"][-FORMA_PARTIDOS:])}
                 for i, eq in enumerate(orden, start=1) for f in (filas[eq],)]
        return {"standings": [{"type": "TOTAL", "table": tabla}], "fuente": "resultados_propios", "liga_codigo": codigo, "temporada": actual,
                "datos_hasta": date.fromordinal(jugados[-1]["dia"]).isoformat()}
    except Exception:  # noqa: BLE001 — una pieza de respaldo: sin ella el análisis sigue sin tabla
        log.warning("tabla propia no disponible", exc_info=True)
        return None
