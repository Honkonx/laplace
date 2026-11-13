"""ml/sintetico.py — mundos sintéticos con VERDAD CONOCIDA para pruebas de sandbox del motor.

Una liga inventada tiene fuerzas de ataque/defensa reales (que el motor no conoce), de modo que se puede
medir qué tan lejos queda cada pronóstico de la probabilidad verdadera (el "oráculo") y de los resultados
simulados. Sirve para tres cosas: (1) ver en qué punto exacto del pipeline se declara "sin datos",
(2) medir cuántos partidos necesita un modelo para empezar a ser útil (arranque en frío) y (3) probar el
motor con entradas corruptas sin tocar APIs ni la BD real. Solo librería estándar (+ `dixon_coles` para
probabilidades); la generación es determinista dada la semilla.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from backend.api.ml import dixon_coles

NOMBRES = (
    "Alfa", "Bravo", "Delta", "Eco", "Fenix", "Gama", "Halcon", "Icaro", "Jupiter", "Kappa", "Lince", "Mistral",
    "Nova", "Obelisco", "Pampa", "Quasar", "Rayo", "Sirio", "Titan", "Urano", "Vortice", "Zafiro",
)
RHO_SINTETICO = 0.0  # el generador es Poisson independiente: la verdad no tiene corrección de baja puntuación


@dataclass
class LigaSintetica:
    codigo: str
    nombre: str
    mu: float
    gamma: float
    ataque: dict[str, float]
    defensa: dict[str, float]
    equipos: list[str] = field(default_factory=list)
    rho: float = RHO_SINTETICO  # corrección de baja puntuación de la verdad (0 = Poisson independiente)
    deriva: float = 0.0  # desviación estándar de la fuerza de cada equipo entre temporadas (0 = fuerzas fijas)

    def lambdas(self, local: str, visitante: str) -> tuple[float, float]:
        lam_h = math.exp(self.mu + self.gamma + self.ataque[local] - self.defensa[visitante])
        lam_a = math.exp(self.mu + self.ataque[visitante] - self.defensa[local])
        return lam_h, lam_a

    def probs_verdaderas(self, local: str, visitante: str) -> tuple[float, float, float]:
        """Probabilidad 1X2 REAL del partido (el oráculo)."""
        lam_h, lam_a = self.lambdas(local, visitante)
        return dixon_coles.probabilidades_desde_lambdas(lam_h, lam_a, self.rho)


def generar_liga(semilla: int, n_equipos: int = 16, sd_fuerza: float = 0.30, mu: float = 0.15, gamma: float = 0.28,
                 codigo: str = "ZZZ1", nombre: str = "Liga Sintetica", rho: float = RHO_SINTETICO,
                 deriva: float = 0.0) -> LigaSintetica:
    rng = random.Random(semilla)
    equipos = [f"Club {NOMBRES[i % len(NOMBRES)]}{'' if i < len(NOMBRES) else ' B'}" for i in range(n_equipos)]
    return LigaSintetica(
        codigo=codigo, nombre=nombre, mu=mu, gamma=gamma, equipos=equipos,
        ataque={e: rng.gauss(0, sd_fuerza) for e in equipos}, defensa={e: rng.gauss(0, sd_fuerza) for e in equipos},
        rho=rho, deriva=deriva,
    )


def _poisson(lam: float, rng: random.Random) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def _marcador_dixon_coles(lam_h: float, lam_a: float, rho: float, rng: random.Random) -> tuple[int, int]:
    """Marcador muestreado de la matriz de goles con corrección de baja puntuación (solo si rho != 0)."""
    from backend.api.ml.laplace.pronostico import matriz_goles

    u, acum = rng.random(), 0.0
    for i, fila in enumerate(matriz_goles(lam_h, lam_a, rho)):
        for j, p in enumerate(fila):
            acum += p
            if u < acum:
                return i, j
    return 0, 0


def calendario(liga: LigaSintetica, inicio: date, ida_y_vuelta: bool = True) -> list[list[tuple[str, str]]]:
    """Fechas (rondas) de todos contra todos por el método del círculo. Cada ronda: [(local, visitante), ...]."""
    equipos = list(liga.equipos)
    if len(equipos) % 2:
        equipos.append("")  # descanso
    n = len(equipos)
    rondas = []
    for r in range(n - 1):
        ronda = []
        for i in range(n // 2):
            a, b = equipos[i], equipos[n - 1 - i]
            if a and b:
                ronda.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rondas.append(ronda)
        equipos = [equipos[0], equipos[-1], *equipos[1:-1]]
    if ida_y_vuelta:
        rondas += [[(v, l) for l, v in ronda] for ronda in rondas]
    return rondas


def cuotas_mercado(probs: tuple[float, float, float], rng: random.Random, margen: float = 0.06,
                   ruido: float = 0.04) -> tuple[float, float, float]:
    """Cuotas decimales de una casa que conoce la verdad con ruido (en logits) y cobra `margen` de overround."""
    logits = [math.log(max(p, 1e-9)) + rng.gauss(0, ruido) for p in probs]
    m = max(logits)
    exp = [math.exp(x - m) for x in logits]
    total = sum(exp)
    con_margen = [(e / total) * (1 + margen) for e in exp]
    return tuple(round(1.0 / p, 2) for p in con_margen)  # type: ignore[return-value]


def simular_temporada(liga: LigaSintetica, inicio: date, semilla: int, temporada: str = "2025/2026") -> list[dict]:
    """Partidos simulados en el esquema de `ml/datos.py` (con `ronda` y la probabilidad verdadera de cada uno).

    Con `liga.deriva > 0` la fuerza de cada equipo se perturba una vez en esta temporada (flujo aleatorio aparte,
    así el flujo de goles con deriva 0 no cambia); con `liga.rho != 0` los goles salen de la matriz Dixon-Coles.
    """
    rng = random.Random(semilla)
    if liga.deriva > 0:
        rng_d = random.Random(f"deriva-{semilla}")
        liga = replace(liga, ataque={e: v + rng_d.gauss(0, liga.deriva) for e, v in liga.ataque.items()},
                       defensa={e: v + rng_d.gauss(0, liga.deriva) for e, v in liga.defensa.items()})
    partidos = []
    for numero, ronda in enumerate(calendario(liga, inicio), start=1):
        fecha = inicio + timedelta(days=7 * (numero - 1))
        for local, visitante in ronda:
            if liga.rho:
                gl, gv = _marcador_dixon_coles(*liga.lambdas(local, visitante), liga.rho, rng)
            else:
                gl, gv = (_poisson(x, rng) for x in liga.lambdas(local, visitante))
            verdad = liga.probs_verdaderas(local, visitante)
            partidos.append({
                "liga": liga.codigo, "liga_nombre": liga.nombre, "temporada": temporada, "fecha": fecha,
                "dia": fecha.toordinal(), "ronda": numero, "local": local, "visitante": visitante, "gl": gl, "gv": gv,
                "resultado": "H" if gl > gv else "A" if gv > gl else "D", "verdad": verdad,
                "ap_prom": cuotas_mercado(verdad, rng),
                **{k: None for k in ("ap_b365", "ap_pinnacle", "ap_max", "ci_b365", "ci_pinnacle", "ci_max", "ci_prom")},
            })
    return partidos


def tabla_hasta(partidos: list[dict], dia: int) -> dict[str, dict]:
    """Posiciones y puntos con los partidos jugados ANTES de `dia` (sin fuga)."""
    pts: dict[str, dict] = {}
    for p in partidos:
        if p["dia"] >= dia:
            continue
        for equipo, favor, contra in ((p["local"], p["gl"], p["gv"]), (p["visitante"], p["gv"], p["gl"])):
            fila = pts.setdefault(equipo, {"pj": 0, "pts": 0, "gf": 0, "gc": 0, "forma": []})
            fila["pj"] += 1
            fila["gf"] += favor
            fila["gc"] += contra
            ganado = 3 if favor > contra else 1 if favor == contra else 0
            fila["pts"] += ganado
            fila["forma"].append(ganado)
    orden = sorted(pts, key=lambda e: (-pts[e]["pts"], -(pts[e]["gf"] - pts[e]["gc"]), -pts[e]["gf"]))
    for i, equipo in enumerate(orden, start=1):
        pts[equipo]["pos"] = i
    return pts
