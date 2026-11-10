"""ml/senales.py — reconstruye, SIN fuga del futuro, las entradas históricas de los módulos del consenso.

Por qué existe (ronda 2026-10-06, agente F): forma, h2h y tabla pesan 28% del consenso y nunca se
habían medido porque nadie reconstruía lo que el bot en producción les entrega. Este módulo arma,
para cada partido del histórico, el mismo diccionario `d` que `analisis_completo.py` le pasa a los
módulos de `services/` (campos y semántica verificados en `standings_fetch.extraer_posicion_y_forma`,
`h2h_fetch._ponderar_y_resumir` y `team_stats_fetch.extraer_goles_promedio`), usando SOLO partidos
estrictamente anteriores a la fecha del partido (los del mismo día no cuentan: no se conoce el orden
de salida). Python puro: no necesita numpy.

Uso típico (el orden de los partidos debe ser temporal):

    c = ConstructorSenales()
    for dia, partidos_del_dia in agrupar_por_dia(partidos):
        for p in partidos_del_dia:
            d = c.construir(p)          # solo lee estado anterior
        for p in partidos_del_dia:
            c.registrar(p)              # recién ahora el resultado entra al estado

Lo que NO se puede reconstruir (se excluye del consenso histórico): `bsd_ml` (predicción CatBoost de un
proveedor externo, no existe histórica) y `xg_local/xg_visit` (el histórico de football-data.co.uk no
trae xG). Hay además tres diferencias conocidas respecto a producción, documentadas en el informe:
H2H solo con partidos de la misma liga del dataset (producción usa api-football, todas las
competiciones); tabla = clasificación reconstruida con los partidos del dataset (en ligas con
Apertura/Clausura es acumulada); forma = últimos 5 de la misma temporada.

Orientación del H2H: `h2h_fetch._ponderar_y_resumir` cuenta `h2h_local_wins` como victorias del
LOCAL DE CADA PARTIDO HISTÓRICO, sin reorientar al local del partido actual. `orientacion="produccion"`
replica eso tal cual; `orientacion="corregida"` cuenta desde la perspectiva del local actual.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator

# Mismo valor que `services/h2h_fetch.MEDIA_VIDA_DIAS` (ese módulo exige sqlalchemy/httpx y no
# se importa aquí; un test lo compara). Los goles del H2H se ponderan por antigüedad.
MEDIA_VIDA_H2H_DIAS = 180
H2H_MAX_PARTIDOS = 10  # api-football `last=10`
MIN_PJ_TABLA = 3  # la tabla de producción llega con jornadas jugadas; menos es ruido de arranque
MIN_PJ_STATS = 1  # `teams/statistics` devuelve promedios con al menos un partido jugado

LIGA_GOLES_AVG_POR_DEFECTO = 2.6
ORIENTACIONES = ("produccion", "corregida")


def agrupar_por_dia(partidos: Iterable[dict]) -> Iterator[tuple[int, list[dict]]]:
    """Agrupa una secuencia ya ordenada por `dia` en bloques del mismo día."""
    bloque: list[dict] = []
    actual: int | None = None
    for p in partidos:
        if actual is not None and p["dia"] != actual:
            yield actual, bloque
            bloque = []
        actual = p["dia"]
        bloque.append(p)
    if bloque:
        yield actual, bloque  # type: ignore[misc]


class _EstadoEquipo:
    __slots__ = ("pts", "gf", "gc", "pj", "forma")

    def __init__(self) -> None:
        self.pts = self.gf = self.gc = self.pj = 0
        self.forma: deque[str] = deque(maxlen=5)  # 'W'/'D'/'L' de los últimos 5 de la temporada


class ConstructorSenales:
    """Estado acumulado (liga, temporada, equipo) y (liga, par de equipos); solo se lee antes de `registrar`."""

    def __init__(self, orientacion: str = "produccion") -> None:
        if orientacion not in ORIENTACIONES:
            raise ValueError(f"orientacion debe ser una de {ORIENTACIONES}")
        self.orientacion = orientacion
        self._equipos: dict[tuple[str, str, str], _EstadoEquipo] = defaultdict(_EstadoEquipo)
        self._temporada: dict[tuple[str, str], set[str]] = defaultdict(set)  # equipos vistos
        self._h2h: dict[tuple[str, frozenset], list[tuple[int, str, str, int, int]]] = defaultdict(list)
        self._ranking: dict[tuple[str, str], dict[str, int]] = {}

    # --- estado ---------------------------------------------------------------------------------
    def registrar(self, p: dict) -> None:
        liga, temp = p["liga"], p["temporada"]
        gl, gv = p["gl"], p["gv"]
        for equipo, favor, contra in ((p["local"], gl, gv), (p["visitante"], gv, gl)):
            e = self._equipos[(liga, temp, equipo)]
            e.gf += favor
            e.gc += contra
            e.pj += 1
            if favor > contra:
                e.pts += 3
                e.forma.append("W")
            elif favor == contra:
                e.pts += 1
                e.forma.append("D")
            else:
                e.forma.append("L")
            self._temporada[(liga, temp)].add(equipo)
        self._h2h[(liga, frozenset((p["local"], p["visitante"])))].append((p["dia"], p["local"], p["visitante"], gl, gv))
        self._ranking.pop((liga, temp), None)

    def _posiciones(self, liga: str, temp: str) -> dict[str, int]:
        clave = (liga, temp)
        if clave not in self._ranking:
            filas = []
            for equipo in self._temporada.get(clave, ()):
                e = self._equipos[(liga, temp, equipo)]
                filas.append((-e.pts, -(e.gf - e.gc), -e.gf, equipo))
            filas.sort()
            self._ranking[clave] = {f[3]: i + 1 for i, f in enumerate(filas)}
        return self._ranking[clave]

    # --- piezas de `d` ---------------------------------------------------------------------------
    def _forma_y_tabla(self, p: dict) -> dict:
        liga, temp = p["liga"], p["temporada"]
        el = self._equipos.get((liga, temp, p["local"]))
        ev = self._equipos.get((liga, temp, p["visitante"]))
        forma_ok = bool(el and ev and el.pj >= 1 and ev.pj >= 1)
        tabla_ok = bool(el and ev and el.pj >= MIN_PJ_TABLA and ev.pj >= MIN_PJ_TABLA)
        pos_l = pos_v = 10
        if tabla_ok:
            ranking = self._posiciones(liga, temp)
            pos_l, pos_v = ranking[p["local"]], ranking[p["visitante"]]
        return {
            "pos_local": pos_l, "pos_visit": pos_v,
            "forma_local_wins": el.forma.count("W") if forma_ok else 2,
            "forma_visit_wins": ev.forma.count("W") if forma_ok else 2,
            "forma_datos_reales": forma_ok,
        }

    def _h2h_previos(self, p: dict) -> list[tuple[int, str, str, int, int]]:
        previos = self._h2h.get((p["liga"], frozenset((p["local"], p["visitante"]))), [])
        return previos[-H2H_MAX_PARTIDOS:][::-1]  # más reciente primero, como la API

    def _bloque_h2h(self, p: dict, previos: list, orientar: bool) -> dict:
        """Mismo contenido que `h2h_fetch._ponderar_y_resumir`, con antigüedad medida contra la fecha del partido."""
        pesos = [math.exp(-max(0, p["dia"] - dia) / MEDIA_VIDA_H2H_DIAS) for dia, *_ in previos]
        peso_total = sum(pesos) or 1.0
        gl_pond = gv_pond = 0.0
        local_wins = visit_wins = empates = 0
        for peso, (_, hl, _hv, gl, gv) in zip(pesos, previos):
            if orientar and hl != p["local"]:  # el local actual jugó de visitante: se invierten los lados
                gl, gv = gv, gl
            gl_pond += gl * peso
            gv_pond += gv * peso
            if gl > gv:
                local_wins += 1
            elif gv > gl:
                visit_wins += 1
            else:
                empates += 1
        total = len(previos)
        favor_l, favor_v = round(gl_pond / peso_total, 2), round(gv_pond / peso_total, 2)
        return {
            "h2h_disponible": True, "h2h_local_wins": local_wins, "h2h_visit_wins": visit_wins,
            "h2h_empates": empates, "h2h_total": total,
            "goles_local_avg": favor_l, "goles_visit_avg": favor_v,
            "goles_contra_local_avg": favor_v, "goles_contra_visit_avg": favor_l,
            "fuente_goles": "h2h_real",
        }

    def _bloque_stats_equipo(self, p: dict) -> dict | None:
        el = self._equipos.get((p["liga"], p["temporada"], p["local"]))
        ev = self._equipos.get((p["liga"], p["temporada"], p["visitante"]))
        if not el or not ev or el.pj < MIN_PJ_STATS or ev.pj < MIN_PJ_STATS:
            return None
        return {
            "h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0, "h2h_total": 0,
            "goles_local_avg": el.gf / el.pj, "goles_visit_avg": ev.gf / ev.pj,
            "goles_contra_local_avg": el.gc / el.pj, "goles_contra_visit_avg": ev.gc / ev.pj,
            "fuente_goles": "stats_equipo_real",
        }

    @staticmethod
    def _bloque_generico() -> dict:
        medio = LIGA_GOLES_AVG_POR_DEFECTO / 2
        return {
            "h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0, "h2h_total": 0,
            "goles_local_avg": medio, "goles_visit_avg": medio * 0.85,
            "goles_contra_local_avg": medio * 0.85, "goles_contra_visit_avg": medio,
            "fuente_goles": "liga_generico",
        }

    # --- API pública -----------------------------------------------------------------------------
    def construir(self, p: dict, orientacion: str | None = None) -> dict:
        """`d` para el partido `p` con el estado acumulado hasta ANTES de su día. No incluye cuotas
        (se agregan aparte con `agregar_cuotas`): su presencia es un escenario, no un dato histórico."""
        orientar = (orientacion or self.orientacion) == "corregida"
        previos = self._h2h_previos(p)
        # Cascada de `h2h_fetch.obtener_h2h`: H2H real → promedios de temporada de cada equipo → genérico.
        bloque = (self._bloque_h2h(p, previos, orientar) if previos
                  else self._bloque_stats_equipo(p) or self._bloque_generico())
        d = {
            "partido_id": f"{p['liga']}-{p['dia']}-{p['local']}-{p['visitante']}",
            "local": p["local"], "visitante": p["visitante"], "liga": p["liga_nombre"],
            "liga_goles_avg": LIGA_GOLES_AVG_POR_DEFECTO,
        }
        d.update(self._forma_y_tabla(p))
        d.update(bloque)
        d.update(sin_cuotas())
        return d


def sin_cuotas() -> dict:
    return {"odds_disponibles": False, "odds_local": 0.0, "odds_empate": 0.0, "odds_visit": 0.0}


def con_cuotas(d: dict, cuotas: tuple[float, float, float] | None) -> dict:
    """Copia de `d` con las cuotas 1X2 (o sin ellas si `cuotas` es None)."""
    nuevo = dict(d)
    nuevo.update(sin_cuotas() if cuotas is None else
                 {"odds_disponibles": True, "odds_local": cuotas[0], "odds_empate": cuotas[1], "odds_visit": cuotas[2]})
    return nuevo


ETIQUETAS = ("Local", "Empate", "Visitante")


def resultado_historico(probs: tuple[float, float, float]) -> dict:
    """Resultado del módulo `historico` con el mismo contrato y la misma fórmula de confianza que
    `services/modelo_historico.analizar` (no se llama a esa función: leería los artefactos entrenados
    con TODO el histórico, que sería fuga). Un test compara ambas fórmulas."""
    mejor = max(range(3), key=lambda i: probs[i])
    score = int(max(25, min(80, 40 + 100 * (probs[mejor] - 1 / 3))))
    return {
        "ok": True, "modulo": "historico", "pick": ETIQUETAS[mejor],
        "prob_local": round(probs[0], 4), "prob_empate": round(probs[1], 4), "prob_visitante": round(probs[2], 4),
        "confianza_score": score,
    }


def ejecutar_modulos(d: dict, historico: tuple[float, float, float] | None = None) -> dict[str, dict]:
    """Réplica de `services/motor.ejecutar_modulos` (misma compuerta por módulo y mismas funciones
    `validar_*`/`analizar`), sin `bsd_ml` y con `historico` recibido ya calculado walk-forward.
    Un test compara esta compuerta contra el motor real."""
    from backend.api.services import form_recent, h2h, odds, pronostico, tabla_pos

    resultados: dict[str, dict] = {}
    fuente_goles = d.get("fuente_goles")
    h2h_corto = fuente_goles == "h2h_real" and int(d.get("h2h_total") or 0) < 3
    if not (fuente_goles == "liga_generico" or h2h_corto):
        resultados["poisson"] = pronostico.analizar(d)
    if d.get("forma_datos_reales", False):
        resultados["forma"] = form_recent.analizar(d)
    if h2h.validar_h2h(d)[0]:
        resultados["h2h"] = h2h.analizar(d)
    if odds.validar_odds(d)[0]:
        resultados["odds"] = odds.analizar(d)
    if tabla_pos.validar_tabla(d)[0]:
        resultados["tabla"] = tabla_pos.analizar(d)
    if historico is not None:
        resultados["historico"] = resultado_historico(historico)
    return resultados
