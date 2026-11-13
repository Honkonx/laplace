"""entrenamiento.py — modelo propio: ratings Elo + tasas de gol con memoria exponencial → regresión logística multinomial propia.

Todo en librería estándar (entrenar y servir sin numpy). Las características de cada partido se calculan SOLO con lo anterior a su
fecha (walk-forward, sin fuga). El resultado se compara siempre con la tasa base, Dixon-Coles y, si hay cuotas, el mercado
(`evaluar_comparando`). El modelo nunca decide publicar: devuelve probabilidades y goles esperados.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from backend.api.ml import dixon_coles, metricas
from backend.api.ml.laplace import goles, variables

K_ELO, VENTAJA_ELO, ALFA_GOLES, L2 = 24.0, 60.0, 0.12, 1e-3
N_MIN_EQUIPO = 5
CLASES = ("H", "D", "A")
NOMBRES_FEATURES = ("sesgo", "dif_elo", "log_lambda_local", "log_lambda_visitante", "dif_experiencia")
ALFA_FORMA = 0.15
PUNTOS_POR_PARTIDO = 1.35
N_FEATURES_TIROS = 4  # las variables de tiros van siempre al final del vector de características
EXTRAS_VALIDOS = ("abs_elo", "forma", "localia", "tiros")
# Generación 2 (afinación M3, 2026-11-10): elegida SOLO con validación (2021-07..2023-07) sobre 24.584 partidos reales de 49 ligas y confirmada en prueba (>= 2023-07):
# log loss 1,01927 -> 1,0164 en validación y 1,02197 -> 1,0192 en prueba. Las constantes K_ELO y ALFA_GOLES quedan con los valores de la generación 1 para leer los artefactos viejos.
HIPER_DEFECTO = {"k_elo": 8.0, "alfa": 0.08, "extras": ["abs_elo", "forma"]}
# Versión 1.1 (MM-10): g3 + estadísticas de tiros. Medido el 2026-11-11 en 17 ligas con tiros: −0,0055 de log loss (z = 8,1) frente a g3 con las mismas ligas
# (el plan de mejoras (repo de trabajo)). Las ligas sin tiros (y los partidos de la capa en vivo, que no los traen) las sigue pronosticando como g3: las 4 variables valen 0.
HIPER_V11 = {"k_elo": 8.0, "alfa": 0.08, "extras": ["abs_elo", "forma", "tiros"]}
# Candidata MM-12 (localía por equipo); NO es una versión servida: solo se mide con `comparar_versiones_modelo.py`.
HIPER_LOCALIA = {"k_elo": 8.0, "alfa": 0.08, "extras": ["abs_elo", "forma", "localia"]}
HIPERS = {"g3": HIPER_DEFECTO, "v1.1": HIPER_V11, "localia": HIPER_LOCALIA}
GENERACION_MODELO = "g3"  # g3 (2026-11-10): mismo 1X2 que g2 + mercados de goles calibrados y validados (`goles.py`)
FRACCION_CALENTAMIENTO = 8  # se descarta 1/8 inicial del entrenamiento: sin memoria las características son ruido


@dataclass
class EstadoLiga:
    """Memoria que se va actualizando partido a partido. Se serializa tal cual dentro del artefacto del modelo."""

    elo: dict[str, float] = field(default_factory=dict)
    gf: dict[str, float] = field(default_factory=dict)
    gc: dict[str, float] = field(default_factory=dict)
    n: dict[str, int] = field(default_factory=dict)
    media_local: float = 1.4
    media_visita: float = 1.1
    total_partidos: int = 0
    forma: dict[str, float] = field(default_factory=dict)  # puntos por partido con memoria exponencial
    t_for: dict[str, float] = field(default_factory=dict)  # tiros a favor y en contra por equipo (memoria exponencial); solo si el partido trae tiros
    t_con: dict[str, float] = field(default_factory=dict)
    a_for: dict[str, float] = field(default_factory=dict)  # tiros a puerta
    a_con: dict[str, float] = field(default_factory=dict)
    media_t: float = 0.0  # media de tiros por equipo y partido de la liga (0 = la liga no trae tiros)
    media_a: float = 0.0
    n_tiros: int = 0
    dev_h: dict[str, float] = field(default_factory=dict)  # localía por equipo (MM-12): diferencia de goles en casa menos la de la liga, con memoria exponencial
    dev_a: dict[str, float] = field(default_factory=dict)  # ídem como visitante
    k_elo: float = K_ELO
    alfa: float = ALFA_GOLES
    extras: tuple[str, ...] = ()

    def lambdas(self, local: str, visitante: str) -> tuple[float, float]:
        m = (self.media_local + self.media_visita) / 2
        gf_h, gc_h = self.gf.get(local, m), self.gc.get(local, m)
        gf_a, gc_a = self.gf.get(visitante, m), self.gc.get(visitante, m)
        lam_h = self.media_local * (gf_h / m) * (gc_a / m)
        lam_a = self.media_visita * (gf_a / m) * (gc_h / m)
        return min(5.0, max(0.15, lam_h)), min(5.0, max(0.15, lam_a))

    def features(self, local: str, visitante: str) -> list[float]:
        lam_h, lam_a = self.lambdas(local, visitante)
        dif = (self.elo.get(local, 1500.0) + VENTAJA_ELO - self.elo.get(visitante, 1500.0)) / 400.0
        exp = (min(self.n.get(local, 0), 20) - min(self.n.get(visitante, 0), 20)) / 20.0
        x = [1.0, dif, math.log(lam_h), math.log(lam_a), exp]
        if "abs_elo" in self.extras:
            x.append(abs(dif))  # la brecha de fuerza sin signo: distingue partidos parejos (más empates) de los desparejos
        if "forma" in self.extras:
            x.append((self.forma.get(local, PUNTOS_POR_PARTIDO) - self.forma.get(visitante, PUNTOS_POR_PARTIDO)) / 3.0)
        if "localia" in self.extras:
            x += [self.dev_h.get(local, 0.0), self.dev_a.get(visitante, 0.0)]  # van antes de los tiros: las variables de tiros siempre cierran el vector
        if "tiros" in self.extras:
            x += self._features_tiros(local, visitante)
        return x

    def _features_tiros(self, local: str, visitante: str) -> list[float]:
        """log(λ de tiros / media de la liga) del local y del visitante, para tiros y para tiros a puerta; 0 (neutro) si la liga no trae tiros o un equipo no tiene historia de tiros."""
        if self.n_tiros < 1 or local not in self.t_for or visitante not in self.t_for:
            return [0.0, 0.0, 0.0, 0.0]
        mt, ma = self.media_t, self.media_a

        def razon(a_favor: dict, en_contra: dict, atacante: str, defensor: str, media: float) -> float:
            return math.log(max(a_favor.get(atacante, media), 0.5) / media) + math.log(max(en_contra.get(defensor, media), 0.5) / media)

        return [razon(self.t_for, self.t_con, local, visitante, mt), razon(self.t_for, self.t_con, visitante, local, mt),
                razon(self.a_for, self.a_con, local, visitante, ma), razon(self.a_for, self.a_con, visitante, local, ma)]

    def conoce(self, equipo: str) -> bool:
        return self.n.get(equipo, 0) >= N_MIN_EQUIPO

    def actualizar(self, local: str, visitante: str, gl: int, gv: int, tiros: tuple[float, float, float, float] | None = None) -> None:
        eh, ea = self.elo.get(local, 1500.0), self.elo.get(visitante, 1500.0)
        esperado = 1 / (1 + 10 ** (-(eh + VENTAJA_ELO - ea) / 400))
        real = 1.0 if gl > gv else 0.5 if gl == gv else 0.0
        delta = self.k_elo * (1 + 0.25 * min(abs(gl - gv), 3)) * (real - esperado)
        self.elo[local], self.elo[visitante] = eh + delta, ea - delta
        m = (self.media_local + self.media_visita) / 2
        for eq, a_favor, en_contra in ((local, gl, gv), (visitante, gv, gl)):
            self.gf[eq] = (1 - self.alfa) * self.gf.get(eq, m) + self.alfa * a_favor
            self.gc[eq] = (1 - self.alfa) * self.gc.get(eq, m) + self.alfa * en_contra
            puntos = 3.0 if a_favor > en_contra else 1.0 if a_favor == en_contra else 0.0
            self.forma[eq] = (1 - ALFA_FORMA) * self.forma.get(eq, PUNTOS_POR_PARTIDO) + ALFA_FORMA * puntos
            self.n[eq] = self.n.get(eq, 0) + 1
        if "localia" in self.extras:
            gd, ref = gl - gv, self.media_local - self.media_visita
            self.dev_h[local] = (1 - self.alfa) * self.dev_h.get(local, 0.0) + self.alfa * (gd - ref)
            self.dev_a[visitante] = (1 - self.alfa) * self.dev_a.get(visitante, 0.0) + self.alfa * (ref - gd)
        if tiros is not None:  # (tiros local, tiros visitante, a puerta local, a puerta visitante)
            tl, tv, al, av = tiros
            self.n_tiros += 1
            paso = 1 / min(self.n_tiros + 10, 400)
            if self.n_tiros == 1:
                self.media_t, self.media_a = (tl + tv) / 2, max((al + av) / 2, 0.5)
            else:
                self.media_t += ((tl + tv) / 2 - self.media_t) * paso
                self.media_a += (max((al + av) / 2, 0.5) - self.media_a) * paso
            for eq, tf, tc, af, ac in ((local, tl, tv, al, av), (visitante, tv, tl, av, al)):
                self.t_for[eq] = (1 - self.alfa) * self.t_for.get(eq, self.media_t) + self.alfa * tf
                self.t_con[eq] = (1 - self.alfa) * self.t_con.get(eq, self.media_t) + self.alfa * tc
                self.a_for[eq] = (1 - self.alfa) * self.a_for.get(eq, self.media_a) + self.alfa * af
                self.a_con[eq] = (1 - self.alfa) * self.a_con.get(eq, self.media_a) + self.alfa * ac
        self.total_partidos += 1
        t = self.total_partidos
        # se parte de una media previa de la liga con peso de 10 partidos: con los primeros marcadores (p. ej. 0-0) la media no puede colapsar a cero
        self.media_local += (gl - self.media_local) / min(t + 10, 400)
        self.media_visita += (gv - self.media_visita) / min(t + 10, 400)

    def a_dict(self) -> dict:
        return {"elo": self.elo, "gf": self.gf, "gc": self.gc, "n": self.n, "media_local": self.media_local,
                "media_visita": self.media_visita, "total_partidos": self.total_partidos, "forma": self.forma, "k_elo": self.k_elo, "alfa": self.alfa,
                "extras": list(self.extras), "t_for": self.t_for, "t_con": self.t_con, "a_for": self.a_for, "a_con": self.a_con,
                "media_t": self.media_t, "media_a": self.media_a, "n_tiros": self.n_tiros, "dev_h": self.dev_h, "dev_a": self.dev_a}

    @classmethod
    def de_dict(cls, d: dict) -> EstadoLiga:
        base = {k: d[k] for k in ("elo", "gf", "gc", "n", "media_local", "media_visita", "total_partidos")}
        # los artefactos anteriores a M3 no traen estos campos: se leen con los valores con los que se entrenaron
        return cls(**base, forma=d.get("forma", {}), k_elo=d.get("k_elo", K_ELO), alfa=d.get("alfa", ALFA_GOLES), extras=tuple(d.get("extras", ())),
                   t_for=d.get("t_for", {}), t_con=d.get("t_con", {}), a_for=d.get("a_for", {}), a_con=d.get("a_con", {}),
                   media_t=d.get("media_t", 0.0), media_a=d.get("media_a", 0.0), n_tiros=d.get("n_tiros", 0),
                   dev_h=d.get("dev_h", {}), dev_a=d.get("dev_a", {}))


def _softmax(z: list[float]) -> list[float]:
    m = max(z)
    e = [math.exp(x - m) for x in z]
    s = sum(e)
    return [x / s for x in e]


def probs_lineal(pesos: list[list[float]], x: list[float]) -> tuple[float, float, float]:
    p = _softmax([sum(w * xi for w, xi in zip(fila, x)) for fila in pesos])
    return p[0], p[1], p[2]


def ajustar_logistica(X: list[list[float]], y: list[str], epocas: int = 300, lr: float = 0.5, l2: float = L2,
                      ancla: list[list[float]] | None = None, l2_ancla: float = 0.0, pesos_muestra: list[float] | None = None) -> list[list[float]]:
    """Regresión logística multinomial (3 clases × d características) por L-BFGS. Determinista.

    `ancla` + `l2_ancla` tiran de los pesos hacia otros ya conocidos (los universales): así una liga con pocos partidos se parece al modelo universal
    y solo se aparta cuando tiene evidencia propia. Entrenar usa numpy; servir no lo necesita (`probs_lineal`)."""
    import numpy as np
    from scipy.optimize import minimize

    Xa, k = np.asarray(X, dtype=float), np.array([CLASES.index(c) for c in y])
    n, d = Xa.shape
    Y = np.zeros((n, 3))
    Y[np.arange(n), k] = 1.0
    A = np.asarray(ancla if ancla is not None else np.zeros((3, d)), dtype=float)
    mascara = np.ones(d)
    mascara[0] = 0.0  # el sesgo no se regulariza hacia cero
    # MP-3: peso por muestra (p. ej. más peso a lo reciente), normalizado a media 1 para que la regularización pese igual; sin pesos, todo vale 1 y el resultado es el de siempre
    w = np.ones(n) if pesos_muestra is None else np.asarray(pesos_muestra, dtype=float) / np.mean(pesos_muestra)

    def f(v):
        W = v.reshape(3, d)
        Z = Xa @ W.T
        Z -= Z.max(axis=1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(axis=1, keepdims=True)
        ll = (-np.log(np.clip(P[np.arange(n), k], 1e-12, None)) * w).mean()
        reg = 0.5 * l2 * ((W * mascara) ** 2).sum() + 0.5 * l2_ancla * (((W - A) * mascara) ** 2).sum()
        grad = ((P - Y) * w[:, None]).T @ Xa / n + l2 * W * mascara + l2_ancla * (W - A) * mascara
        return ll + reg, grad.ravel()

    r = minimize(f, A.ravel(), jac=True, method="L-BFGS-B", options={"maxiter": max(epocas, 50)})
    return r.x.reshape(3, d).tolist()


def tiros_de(p: dict) -> tuple[float, float, float, float] | None:
    """(tiros local, tiros visitante, a puerta local, a puerta visitante) del partido, o None si no los trae completos."""
    t = (p.get("tl"), p.get("tv"), p.get("al"), p.get("av"))
    return t if all(v is not None for v in t) else None  # type: ignore[return-value]


def recorrer(partidos: list[dict], hiper: dict | None = None, goles_out: list | None = None) -> tuple[list[tuple[list[float], str]], EstadoLiga]:
    """Recorre en orden de fecha: (características ANTES del partido, resultado) y el estado final.

    Si se pasa `goles_out`, agrega por partido (λ local, λ visitante, media local, media visitante, goles local, goles visitante) con el estado de ANTES: es lo que calibra los mercados de goles."""
    h = hiper or {}
    estado = EstadoLiga(k_elo=h.get("k_elo", K_ELO), alfa=h.get("alfa", ALFA_GOLES), extras=tuple(h.get("extras", ())))
    filas = []
    for p in sorted(partidos, key=lambda x: (x["dia"], x["local"])):
        filas.append((estado.features(p["local"], p["visitante"]), p["resultado"]))
        if goles_out is not None:
            lam_h, lam_a = estado.lambdas(p["local"], p["visitante"])
            goles_out.append((lam_h, lam_a, estado.media_local, estado.media_visita, p["gl"], p["gv"]))
        estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], tiros_de(p))
    return filas, estado


def sin_margen(cuotas: tuple[float, float, float]) -> tuple[float, float, float]:
    inv = [1 / c for c in cuotas]
    s = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


def ece(predicciones: list[tuple[tuple[float, float, float], str]], bins: int = 10) -> float | None:
    """Error de calibración esperado de la clase más probable."""
    if not predicciones:
        return None
    cubos: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, r in predicciones:
        k = max(range(3), key=lambda i: p[i])
        cubos[min(int(p[k] * bins), bins - 1)].append((p[k], 1 if CLASES[k] == r else 0))
    n = len(predicciones)
    return sum(len(c) / n * abs(sum(a for a, _ in c) / len(c) - sum(b for _, b in c) / len(c)) for c in cubos if c)


def entrenar(partidos: list[dict], fecha_corte: int, epocas: int = 300) -> dict:
    """Entrena con los partidos ANTERIORES a `fecha_corte` y devuelve el artefacto (pesos + estado a esa fecha)."""
    previos = [p for p in partidos if p["dia"] < fecha_corte]
    if len(previos) < 60:
        raise ValueError(f"muy pocos partidos para entrenar ({len(previos)} < 60)")
    filas, estado = recorrer(previos)
    entrenables = filas[len(filas) // FRACCION_CALENTAMIENTO:]
    pesos = ajustar_logistica([x for x, _ in entrenables], [r for _, r in entrenables], epocas)
    base = [sum(1 for _, r in entrenables if r == c) / len(entrenables) for c in CLASES]
    return {"familia": "logistica-elo-goles", "caracteristicas": list(NOMBRES_FEATURES), "pesos": pesos, "estado": estado.a_dict(),
            "tasa_base": base, "n_entrenamiento": len(entrenables), "fecha_corte": fecha_corte}


def predecir_1x2(artefacto: dict, local: str, visitante: str) -> dict:
    estado = EstadoLiga.de_dict(artefacto["estado"])
    return {"p1x2": probs_lineal(artefacto["pesos"], estado.features(local, visitante)), "lambdas": estado.lambdas(local, visitante),
            "conoce_local": estado.conoce(local), "conoce_visitante": estado.conoce(visitante)}


def _resumen(preds: list) -> dict:
    return {"n": len(preds), "log_loss": round(metricas.promedio(metricas.log_loss, preds), 5), "rps": round(metricas.promedio(metricas.rps, preds), 5),
            "brier": round(metricas.promedio(metricas.brier, preds), 5), "ece": round(ece(preds) or 0.0, 5)}


def evaluar_comparando(partidos: list[dict], fecha_corte: int, epocas: int = 300) -> dict:
    """Walk-forward: ajusta con lo anterior a `fecha_corte` y evalúa lo posterior avanzando el estado (sin reentrenar los pesos).

    Compara con: tasa base del entrenamiento, Dixon-Coles reajustado cada 7 días, el mercado (si hay cuotas) y el oráculo (si hay verdad)."""
    art = entrenar(partidos, fecha_corte, epocas)
    estado = EstadoLiga.de_dict(art["estado"])
    prueba = sorted((p for p in partidos if p["dia"] >= fecha_corte), key=lambda x: (x["dia"], x["local"]))
    if not prueba:
        raise ValueError("no hay partidos de prueba posteriores al corte")
    historial = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in partidos if p["dia"] < fecha_corte]
    propio, refs = [], {"tasa_base": [], "dixon_coles": [], "mercado": [], "oraculo": []}
    modelo_dc, dia_dc = None, None
    for p in prueba:
        r = p["resultado"]
        propio.append((probs_lineal(art["pesos"], estado.features(p["local"], p["visitante"])), r))
        refs["tasa_base"].append((tuple(art["tasa_base"]), r))
        if dia_dc is None or p["dia"] - dia_dc >= 7:
            modelo_dc, dia_dc = dixon_coles.ajustar(historial, p["dia"]), p["dia"]
        if modelo_dc:
            refs["dixon_coles"].append((dixon_coles.probabilidades(modelo_dc, p["local"], p["visitante"]), r))
        cuotas = p.get("cuotas") or (p.get("ap_prom") if isinstance(p.get("ap_prom"), tuple) else None)
        if cuotas:
            refs["mercado"].append((sin_margen(cuotas), r))
        if p.get("verdad"):
            refs["oraculo"].append((tuple(p["verdad"]), r))
        estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], tiros_de(p))
        historial.append((p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]))
    informe = {"n_entrenamiento": art["n_entrenamiento"], "n_prueba": len(prueba), "fecha_corte": fecha_corte,
               "propio": _resumen(propio), "referencias": {k: _resumen(v) for k, v in refs.items() if v}}
    for nombre in ("tasa_base", "dixon_coles", "mercado"):
        ref = informe["referencias"].get(nombre)
        informe[f"mejora_log_loss_sobre_{nombre}"] = round(ref["log_loss"] - informe["propio"]["log_loss"], 5) if ref else None
    return {"artefacto": art, "informe": informe}


# ---------- modelo jerárquico: universal + especialización por liga ----------
MIN_PARTIDOS_LIGA = 800   # por debajo, la liga usa los pesos universales
ANCLA_LIGA = 20.0         # fuerza con la que los pesos de una liga se mantienen cerca de los universales
FAMILIA_JERARQUICA = "logistica-jerarquica"


def _filas_entrenables(partidos: list[dict], hiper: dict | None = None, goles_out: list | None = None, dias_out: list | None = None) -> tuple[list[tuple[list[float], str]], EstadoLiga]:
    filas, estado = recorrer(partidos, hiper, goles_out)
    if goles_out is not None:
        del goles_out[:len(goles_out) - len(filas) + len(filas) // FRACCION_CALENTAMIENTO]
    if dias_out is not None:  # el día de cada fila entrenable, en el mismo orden que `recorrer` (para el peso por recencia)
        dias_out.extend(p["dia"] for p in sorted(partidos, key=lambda x: (x["dia"], x["local"]))[len(filas) // FRACCION_CALENTAMIENTO:])
    return filas[len(filas) // FRACCION_CALENTAMIENTO:], estado


def linaje_de(previos: dict[str, list[dict]], hiper: dict) -> dict:
    """Con qué se entrenó (MM-01): huella de los datos y de las variables. El entrenamiento no tiene azar (L-BFGS determinista, submuestreo regular), así que `semilla` es 0 por construcción;
    con los mismos datos y el mismo código el artefacto sale idéntico (prueba de reproducibilidad). `hash_codigo` lo agrega el script de reentreno (el commit)."""
    h = hashlib.sha256()
    for codigo in sorted(previos):
        for fila in sorted((p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in previos[codigo]):
            h.update(f"{codigo}|{fila[0]}|{fila[1]}|{fila[2]}|{fila[3]}|{fila[4]}\n".encode())
    return {"semilla": 0, "hash_datos": h.hexdigest(), "version_variables": variables.version_variables(hiper.get("extras", ())), "hash_codigo": None}


def entrenar_jerarquico(por_liga: dict[str, list[dict]], fecha_corte: int, especializar: bool = False, hiper: dict | None = None, con_goles: bool = True) -> dict:
    """Un modelo UNIVERSAL con todas las ligas y, para las que tienen suficientes partidos, pesos propios anclados a los universales.

    Cada liga conserva su propio estado (Elo, tasas de gol, media de goles): ahí vive el conocimiento de la liga. Especializar además los pesos (`especializar=True`)
    se midió el 2026-11-10 con 43.602 partidos reales de 49 ligas y NO mejora (log loss 1,02202 vs 1,02197 del universal), por eso está apagado por defecto."""
    hiper = HIPER_DEFECTO if hiper is None else hiper
    previos = {c: [p for p in ps if p["dia"] < fecha_corte] for c, ps in por_liga.items()}
    previos = {c: ps for c, ps in previos.items() if len(ps) >= 60}
    if not previos:
        raise ValueError("ninguna liga tiene partidos suficientes para entrenar")
    entrenables, estados, filas_goles, dias = {}, {}, {}, {}
    for codigo, ps in previos.items():
        filas_goles[codigo], dias[codigo] = [], []
        entrenables[codigo], estados[codigo] = _filas_entrenables(ps, hiper, filas_goles[codigo], dias[codigo])
    todas = [f for fs in entrenables.values() for f in fs]
    vida = hiper.get("recencia_dias")  # MP-3: semivida (en días) del peso de cada partido; sin ella, todos pesan igual (g3)

    def pesos_de_ligas(ligas_: list[str] | None = None) -> list[float] | None:
        return [0.5 ** ((fecha_corte - d) / vida) for c in (ligas_ if ligas_ is not None else entrenables) for d in dias[c]] if vida else None

    universal = ajustar_logistica([x for x, _ in todas], [r for _, r in todas], pesos_muestra=pesos_de_ligas())
    respaldo = None
    if "tiros" in hiper.get("extras", ()):
        # v1.1: los pesos universales se ajustan solo con las ligas que traen tiros; las que no, usan los pesos de la versión sin tiros (g3) rellenos con ceros
        # (medido el 2026-11-11: con pesos únicos algunas ligas sin tiros empeoraban hasta 0,005 de log loss, z = −3,6).
        ligas_con_tiros = [c for c in entrenables if estados[c].n_tiros > 0]
        if ligas_con_tiros:
            filas_t = [f for c in ligas_con_tiros for f in entrenables[c]]
            universal = ajustar_logistica([x for x, _ in filas_t], [r for _, r in filas_t], pesos_muestra=pesos_de_ligas(ligas_con_tiros))
            sin_tiros = ajustar_logistica([x[:-N_FEATURES_TIROS] for x, _ in todas], [r for _, r in todas], pesos_muestra=pesos_de_ligas())
            respaldo = [fila + [0.0] * N_FEATURES_TIROS for fila in sin_tiros]
    filas_universal = filas_t if respaldo is not None else todas
    try:  # MM-14: covarianza de los pesos universales para los intervalos; accesorio, un fallo no impide entrenar
        from backend.api.ml.laplace import incertidumbre

        cov = incertidumbre.covarianza_pesos([x for x, _ in filas_universal], universal, L2)
    except Exception:  # noqa: BLE001
        cov = None
    ligas = {}
    for codigo, fs in entrenables.items():
        propios = None
        if especializar and len(fs) >= MIN_PARTIDOS_LIGA:
            propios = ajustar_logistica([x for x, _ in fs], [r for _, r in fs], ancla=universal, l2_ancla=ANCLA_LIGA)
        ligas[codigo] = {"estado": estados[codigo].a_dict(), "pesos": propios, "n": len(fs),
                         "tasa_base": [sum(1 for _, r in fs if r == c) / len(fs) for c in CLASES]}
        if respaldo is not None and estados[codigo].n_tiros == 0:
            ligas[codigo]["pesos"], ligas[codigo]["pesos_de_respaldo"] = respaldo, True
    calibracion = goles.calibrar(filas_goles) if con_goles else None  # `con_goles=False`: comparaciones de versiones, donde la calibración de goles no se usa
    if calibracion:
        for codigo, tasas in calibracion.pop("tasas_liga").items():
            ligas[codigo]["tasas_goles"] = tasas
    return {"familia": FAMILIA_JERARQUICA, "caracteristicas": list(NOMBRES_FEATURES), "universal": universal, "ligas": ligas,
            "fecha_corte": fecha_corte, "n_entrenamiento": len(todas), "hiper": hiper, "generacion": GENERACION_MODELO, "goles": calibracion,
            "incertidumbre": {"covarianza": cov, "n": len(filas_universal), "metodo": "delta sobre el Hessiano de los pesos universales"} if cov else None,
            "linaje": linaje_de(previos, hiper)}


def pesos_de(artefacto: dict, liga: str) -> list[list[float]]:
    info = artefacto["ligas"].get(liga) or {}
    return info.get("pesos") or artefacto["universal"]


def predecir_liga(artefacto: dict, liga: str, local: str, visitante: str, estado: EstadoLiga | None = None) -> dict | None:
    """Pronóstico con el estado y los pesos de la liga; None si la liga no está en el modelo. `estado` (opcional) es el estado al día de la base (`estado_vivo.py`) en lugar del del artefacto."""
    info = artefacto["ligas"].get(liga)
    if info is None:
        return None
    estado = estado or EstadoLiga.de_dict(info["estado"])
    return {"p1x2": probs_lineal(pesos_de(artefacto, liga), estado.features(local, visitante)), "lambdas": estado.lambdas(local, visitante),
            "medias": (estado.media_local, estado.media_visita), "tasas_goles": info.get("tasas_goles"), "goles": artefacto.get("goles"),
            "conoce_local": estado.conoce(local), "conoce_visitante": estado.conoce(visitante), "especializado": bool(info.get("pesos")) and not info.get("pesos_de_respaldo")}


def comparaciones_pareadas(pareados: list) -> dict:
    """Significancia de la versión evaluada frente a cada referencia, sobre los MISMOS partidos (`ml/comparacion.py`): positiva = el modelo es mejor. Bloques = semanas."""
    from backend.api.ml import comparacion

    if len(pareados) < 30:
        return {}
    salida = {}
    for nombre, idx in (("tasa_base", 3), ("dixon_coles", 4), ("mercado", 5)):
        filas = [f for f in pareados if f[idx] is not None]
        if len(filas) >= 30:
            ref = [(f[idx], f[6]) for f in filas]
            mod = [(f[1], f[6]) for f in filas]
            salida[f"modelo_vs_{nombre}"] = comparacion.comparar_predicciones(ref, mod, bloques=[f[0] for f in filas], n_boot=300)
    filas = pareados
    salida["modelo_vs_universal"] = comparacion.comparar_predicciones([(f[2], f[6]) for f in filas], [(f[1], f[6]) for f in filas], bloques=[f[0] for f in filas], n_boot=300)
    return salida


def evaluar_jerarquico(por_liga: dict[str, list[dict]], fecha_corte: int, con_dixon_coles: bool = True, hiper: dict | None = None,
                       hasta: int | None = None, especializar: bool = True) -> dict:
    """Walk-forward por liga con variantes sobre los mismos partidos: solo universal, universal + especialización por liga, y las referencias
    (tasa base, Dixon-Coles semanal y mercado). El resultado dice si especializar mejora de verdad."""
    art = entrenar_jerarquico(por_liga, fecha_corte, especializar=especializar, hiper=hiper)  # por defecto SÍ se especializa: es lo que se compara con el universal
    w_uni = art["universal"]
    agregado: dict[str, list] = {"universal": [], "jerarquico": [], "tasa_base": [], "dixon_coles": [], "mercado": []}
    por_liga_inf = {}
    pareados: list = []  # (semana, jerárquico, universal, tasa base, Dixon-Coles | None, mercado | None, resultado): alineados por partido para las pruebas de significancia
    for codigo, info in art["ligas"].items():
        prueba = sorted((p for p in por_liga[codigo] if fecha_corte <= p["dia"] < (hasta or 10**9)), key=lambda x: (x["dia"], x["local"]))
        if len(prueba) < 100:
            continue
        estado = EstadoLiga.de_dict(info["estado"])
        w_jer = pesos_de(art, codigo)
        historial = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in por_liga[codigo] if p["dia"] < fecha_corte]
        loc: dict[str, list] = {k: [] for k in agregado}
        modelo_dc, dia_dc = None, None
        for p in prueba:
            x, r = estado.features(p["local"], p["visitante"]), p["resultado"]
            loc["universal"].append((probs_lineal(w_uni, x), r))
            loc["jerarquico"].append((probs_lineal(w_jer, x), r))
            loc["tasa_base"].append((tuple(info["tasa_base"]), r))
            pdc = None
            if con_dixon_coles:
                if dia_dc is None or p["dia"] - dia_dc >= 7:
                    modelo_dc, dia_dc = dixon_coles.ajustar(historial, p["dia"]), p["dia"]
                if modelo_dc:
                    pdc = dixon_coles.probabilidades(modelo_dc, p["local"], p["visitante"])
                    loc["dixon_coles"].append((pdc, r))
            c = p.get("cuotas") or (p.get("ap_prom") if isinstance(p.get("ap_prom"), tuple) else None)
            if c:
                loc["mercado"].append((sin_margen(c), r))
            pareados.append((p["dia"] // 7, loc["jerarquico"][-1][0], loc["universal"][-1][0], tuple(info["tasa_base"]), pdc, sin_margen(c) if c else None, r))
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], tiros_de(p))
            historial.append((p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]))
        por_liga_inf[codigo] = {"n_prueba": len(prueba), "especializada": bool(info.get("pesos")), **{k: _resumen(v) for k, v in loc.items() if v}}
        for k, v in loc.items():
            agregado[k] += v
    resumen = {k: _resumen(v) for k, v in agregado.items() if v}
    return {"artefacto": art, "informe": {"fecha_corte": fecha_corte, "n_prueba": len(agregado["universal"]), "ligas": len(por_liga_inf),
                                          "resumen": resumen, "por_liga": por_liga_inf, "comparaciones": comparaciones_pareadas(pareados)}}
