"""services/simulador_propio.py — simulador de liga PÚBLICO (solo planes pro/max y administradores) con el motor propio y los datos propios.

Qué hace: toma TODO el histórico de la liga más los resultados recientes (capa en vivo), construye la tabla actual de la temporada, deduce los partidos que faltan (en una liga todos-contra-todos a
ida y vuelta, cada par local/visitante que aún no se jugó), estima los goles esperados de cada uno con el estado del modelo Laplace (Elo + tasas de gol, actualizado partido a partido) y simula el resto de
la temporada con `ml/laplace/liga.py` (núcleo en Go si está compilado, Python si no; incertidumbre de la fuerza de cada equipo, validada con un backtest de 57 temporadas).
Antes dependía de los standings de API-Football, que el plan gratis no da para la temporada actual (H-018). Es una estimación, no una certeza ni un consejo de apuesta.

No es lo mismo que las simulaciones internas de desarrollo (backtests y pruebas, ver `docs/backend/SIMULADOR_PUBLICO.md`): aquí hay tope de simulaciones y solo entra quien tiene plan.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import date

from backend.api.ml import datos
from backend.api.ml.laplace import entrenamiento as e
from backend.api.ml.laplace import liga

log = logging.getLogger("laplace.simulador_propio")

# slug público → código de liga del conjunto de datos (solo ligas todos-contra-todos a ida y vuelta)
SLUGS: dict[str, tuple[str, str]] = {
    "premier": ("E0", "Premier League"), "laliga": ("SP1", "La Liga"), "seriea": ("I1", "Serie A"), "bundesliga": ("D1", "Bundesliga"), "ligue1": ("F1", "Ligue 1"),
    "eredivisie": ("N1", "Eredivisie"), "primeirliga": ("P1", "Primeira Liga"), "superlig": ("T1", "Süper Lig"), "championship": ("E1", "Championship"),
    "pro_league": ("B1", "Pro League"), "scottish": ("SC0", "Premiership escocesa"), "brasileirao": ("BRA", "Brasileirão"),
}
N_SIM_DEFECTO, N_SIM_MAX = 10_000, 20_000
POSICIONES_COPA, POSICIONES_DESCENSO = 4, 3
TTL_DATOS_SEGUNDOS = 600
_cache: dict = {"t": 0.0, "partidos": None}


def _partidos() -> list[dict]:
    """Maestro + capa en vivo, en memoria 10 minutos (cargar el conjunto completo cuesta unos segundos)."""
    ahora = time.monotonic()
    if _cache["partidos"] is None or ahora - _cache["t"] > TTL_DATOS_SEGUNDOS:
        try:
            _cache["partidos"], _ = datos.cargar_partidos_con_vivo()
        except FileNotFoundError:
            # La instalación pública no trae los datos históricos (licencias de terceros): sin ellos el simulador lo dice, no se cae (H-028: `GET /api/v1/simulador` daba 500). El fallo no se guarda en la caché: al aparecer los datos funciona sin reiniciar.
            return []
        _cache["t"] = ahora
    return _cache["partidos"]


def limpiar_cache() -> None:
    _cache.update({"t": 0.0, "partidos": None})


def _temporada_completa(ps: list[dict]) -> int | None:
    """Cantidad de equipos si los partidos forman un todos-contra-todos a ida y vuelta COMPLETO; None si no."""
    equipos = {p["local"] for p in ps} | {p["visitante"] for p in ps}
    n = len(equipos)
    return n if n >= 8 and len({(p["local"], p["visitante"]) for p in ps}) == len(ps) == n * (n - 1) else None


def preparar(codigo: str, partidos: list[dict] | None = None) -> dict:
    """Tabla actual, partidos pendientes, estado del modelo y metadatos de la temporada en curso de `codigo`; `{"ok": False, "razon": …}` si no se puede estimar con honestidad."""
    todos = [p for p in (partidos if partidos is not None else _partidos()) if p["liga"] == codigo]
    if not todos:
        return {"ok": False, "razon": "Esa liga no tiene datos propios todavía."}
    todos.sort(key=lambda p: (p["dia"], p["local"]))
    actual = todos[-1]["temporada"]
    jugados = [p for p in todos if p["temporada"] == actual]
    previas = sorted({p["temporada"] for p in todos if p["temporada"] < actual})
    n_esperado = None
    for t in reversed(previas):
        n_esperado = _temporada_completa([p for p in todos if p["temporada"] == t])
        if n_esperado:
            break
    equipos = sorted({p["local"] for p in jugados} | {p["visitante"] for p in jugados})
    if not n_esperado:
        return {"ok": False, "razon": "No hay una temporada anterior completa para saber cuántos equipos tiene esta liga."}
    if len(equipos) != n_esperado:
        return {"ok": False, "razon": f"La temporada {actual} aún no tiene datos de los {n_esperado} equipos ({len(equipos)} vistos): no se estima para no inventar la tabla."}
    pares_jugados = {(p["local"], p["visitante"]) for p in jugados}
    if len(pares_jugados) != len(jugados):
        return {"ok": False, "razon": "La liga no es de todos contra todos a ida y vuelta (hay partidos repetidos): no se puede deducir lo que falta."}
    pendientes = [{"local": a, "visitante": b} for a in equipos for b in equipos if a != b and (a, b) not in pares_jugados]
    tabla: dict[str, dict] = defaultdict(lambda: {"pj": 0, "pts": 0, "gf": 0, "gc": 0})
    for p in jugados:
        for eq, gf, gc in ((p["local"], p["gl"], p["gv"]), (p["visitante"], p["gv"], p["gl"])):
            f = tabla[eq]
            f["pj"] += 1
            f["gf"] += gf
            f["gc"] += gc
            f["pts"] += 3 if gf > gc else 1 if gf == gc else 0
    estado = e.EstadoLiga(k_elo=e.HIPER_DEFECTO["k_elo"], alfa=e.HIPER_DEFECTO["alfa"], extras=tuple(e.HIPER_DEFECTO["extras"]))
    for p in todos:
        estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], e.tiros_de(p))
    return {"ok": True, "temporada": actual, "equipos": equipos, "tabla": [{"equipo": eq, **tabla.get(eq, {"pj": 0, "pts": 0, "gf": 0, "gc": 0})} for eq in equipos], "pendientes": pendientes,
            "estado": estado, "datos_hasta": date.fromordinal(todos[-1]["dia"]).isoformat(), "partidos_jugados": len(jugados),
            "equipos_poca_historia": sorted(eq for eq in equipos if estado.n.get(eq, 0) < e.N_MIN_EQUIPO)}


def simular(slug: str, n_sim: int = N_SIM_DEFECTO, posiciones_copa: int = POSICIONES_COPA, posiciones_descenso: int = POSICIONES_DESCENSO, partidos: list[dict] | None = None) -> dict:
    """Respuesta del simulador público (misma forma que usa la web: `tabla` por equipo) más los puntos esperados y la procedencia."""
    if slug not in SLUGS:
        return {"ok": False, "razon": f"liga desconocida: {slug}"}
    codigo, nombre = SLUGS[slug]
    base = preparar(codigo, partidos)
    if not base["ok"]:
        return {**base, "liga_slug": slug, "liga_nombre": nombre}
    n_sim = max(100, min(int(n_sim), N_SIM_MAX))
    n = len(base["equipos"])
    cupos = [{"etiqueta": "campeon", "posiciones": [1, 1]}]
    if 0 < posiciones_copa < n:
        cupos.append({"etiqueta": "copa", "posiciones": [1, posiciones_copa]})
    if 0 < posiciones_descenso < n:
        cupos.append({"etiqueta": "descenso", "posiciones": [n - posiciones_descenso + 1, n]})
    estado = base["estado"]
    r = liga.simular_temporada(base["tabla"], base["pendientes"], lambda a, b: estado.lambdas(a, b), n_sim=n_sim, cupos=cupos)
    res = r["resultado"]
    tabla = {}
    for eq in base["equipos"]:
        pos = res["posiciones"][eq]
        ev = res["eventos"][eq]
        tabla[eq] = {"prob_campeon": ev.get("campeon", 0.0), "prob_copa": ev.get("copa", 0.0), "prob_descenso": ev.get("descenso", 0.0),
                     "posicion_promedio": round(sum((k + 1) * p for k, p in enumerate(pos)), 2),
                     "puntos": {k: round(v, 1) if isinstance(v, float) else v for k, v in res["puntos"][eq].items()}}
    return {"ok": True, "liga_slug": slug, "liga_nombre": nombre, "temporada": base["temporada"], "n_simulaciones": n_sim, "partidos_pendientes": len(base["pendientes"]),
            "partidos_jugados": base["partidos_jugados"], "datos_hasta": base["datos_hasta"], "tabla": tabla, "motor": r["motor"], "validado": r["validado"],
            "equipos_poca_historia": base["equipos_poca_historia"], "error_montecarlo": round(r["error_montecarlo"]["max_evento"], 4),
            "aviso": "Estimación estadística con el modelo propio y los resultados hasta la fecha indicada; no es una certeza ni un consejo de apuesta."}


def ligas_disponibles(partidos: list[dict] | None = None) -> list[dict]:
    """Ligas que hoy se pueden simular (con su temporada y hasta qué fecha llegan los datos) y las que no, con el motivo."""
    salida = []
    for slug, (codigo, nombre) in SLUGS.items():
        b = preparar(codigo, partidos)
        salida.append({"slug": slug, "nombre": nombre, "disponible": b["ok"], **({"temporada": b["temporada"], "datos_hasta": b["datos_hasta"], "partidos_pendientes": len(b["pendientes"])} if b["ok"] else {"motivo": b["razon"]})})
    return salida


ALIAS_LIGAS = {
    "premier": "premier", "premier league": "premier", "liga inglesa": "premier", "inglaterra": "premier", "laliga": "laliga", "la liga": "laliga", "liga espanola": "laliga", "espana": "laliga",
    "serie a": "seriea", "seriea": "seriea", "liga italiana": "seriea", "italia": "seriea", "bundesliga": "bundesliga", "liga alemana": "bundesliga", "alemania": "bundesliga",
    "ligue 1": "ligue1", "ligue1": "ligue1", "liga francesa": "ligue1", "francia": "ligue1", "eredivisie": "eredivisie", "holanda": "eredivisie", "primeira liga": "primeirliga",
    "liga portuguesa": "primeirliga", "portugal": "primeirliga", "super lig": "superlig", "turquia": "superlig", "championship": "championship", "pro league": "pro_league", "belgica": "pro_league",
    "brasileirao": "brasileirao", "liga brasilena": "brasileirao", "brasil": "brasileirao",
}


def _normalizar(texto: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c))


# «la liga chilena», «la liga de Argentina»…: «la liga» + otra nacionalidad o país NO es La Liga de España (antes «tabla de la liga chilena» se resolvía como España)
_OTRA_LIGA = re.compile(r"la liga (?:chilena|argentina|mexicana|colombiana|peruana|uruguaya|ecuatoriana|paraguaya|boliviana|venezolana|holandesa|turca|belga|escocesa|de (?!espana)[a-z]+)")


def liga_de_texto(texto_normalizado: str) -> str | None:
    """Liga que menciona un texto ya sin acentos y en minúsculas («quien sera campeon de la liga espanola» → `laliga`); el alias más largo manda. None si no hay ninguna."""
    for alias in sorted(ALIAS_LIGAS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", texto_normalizado):
            if alias == "la liga" and _OTRA_LIGA.search(texto_normalizado):
                continue  # «la liga chilena»: ese «la liga» no es la de España
            return ALIAS_LIGAS[alias]
    return None


def texto_resumen(r: dict, tope: int = 3) -> str:
    """Resumen corto (Telegram y agente) de una simulación: los más probables a campeón, a copa y a descenso, con su procedencia."""
    if not r.get("ok"):
        return r.get("razon") or "No se pudo simular esa liga ahora."

    def mejores(clave: str) -> str:
        orden = sorted(r["tabla"].items(), key=lambda kv: -kv[1][clave])[:tope]
        return ", ".join(f"{eq} {v[clave] * 100:.0f} %" for eq, v in orden)

    return (f"{r['liga_nombre']} {r['temporada']} — {r['n_simulaciones']:,} simulaciones, datos hasta {r['datos_hasta']}\n".replace(",", ".")
            + f"Campeón: {mejores('prob_campeon')}\nCopa: {mejores('prob_copa')}\nDescenso: {mejores('prob_descenso')}\nEstimación, no certeza.")
