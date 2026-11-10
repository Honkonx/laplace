"""backend/scripts/evaluar_consenso_historico.py — mide el CONSENSO REAL completo contra el mercado.

Reconstruye, sin fuga del futuro, la entrada de cada módulo (forma, h2h, tabla, odds, poisson,
historico) con `ml/senales.py` y corre el código real de producción (`services/*.analizar` y
`services/consenso.calcular_consenso`). Compara en el periodo de prueba (>= 2023-07-01) contra tasa
base y mercado, aprende pesos SOLO en desarrollo (< 2023-07-01) y calibra publicación/confianza.

Requiere numpy, scipy y scikit-learn (usar el Python del sistema, no el venv).
Uso:  python backend/scripts/evaluar_consenso_historico.py [--ligas E0 SP1 ...] [--rapido] [--seed 2026]
Salida: backend/data/resultados/evaluacion_consenso_historico.json (se sobrescribe; idempotente).
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluar_modelo_historico as emh  # noqa: E402
from backend.api.ml import datos, dixon_coles, mercado, metricas, senales  # noqa: E402
from backend.api.ml import evaluacion_consenso as ec  # noqa: E402
from backend.api.services import consenso, pronostico  # noqa: E402

CORTE = emh.CORTE_DEV_TEST
RESULTADOS = REPO / "backend" / "data" / "resultados"
SALIDA = RESULTADOS / "evaluacion_consenso_historico.json"
LIGAS_RAPIDO = ("E0", "SP1", "I1", "D1", "F1", "N1", "ARG", "BRA", "MEX", "USA")
MODULOS_CONSENSO = ("poisson", "historico", "forma", "h2h", "odds", "tabla")  # bsd_ml no es reconstruible
MODULOS_LR = ("poisson", "dc", "forma", "h2h", "tabla", "odds")
UMBRALES_PROB = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)


# ------------------------------------------------------------------ recorrido walk-forward
def _t(r: dict) -> tuple:
    return (r["prob_local"], r["prob_empate"], r["prob_visitante"], r["confianza_score"])


def _probs(r: dict) -> tuple[float, float, float]:
    return (r["prob_local"], r["prob_empate"], r["prob_visitante"])


def recorrer(por_liga: dict[str, list[dict]], hp: dict, desde: int) -> list[dict]:
    """Un registro por partido desde `desde`: probabilidades de cada señal y módulos de producción en
    dos escenarios (A: con cuotas de apertura si existen; B: las mismas sin cuotas)."""
    filas = emh.recorrer_dc(por_liga, hp["xi"], hp["ridge"], desde)
    dc_por_id = {id(f["p"]): f for f in filas}
    todos = sorted((p for ps in por_liga.values() for p in ps), key=lambda p: (p["dia"], p["liga"], p["local"]))
    constructor = senales.ConstructorSenales("produccion")
    base: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    apilador = emh.Apilador()
    registros: list[dict] = []
    for dia, bloque in senales.agrupar_por_dia(todos):
        nuevos_apilador = []
        for p in bloque:
            f = dc_por_id.get(id(p))
            if dia >= desde and f is not None:
                registros.append(_registro(p, f, hp, constructor, base, apilador, nuevos_apilador))
        for p in bloque:  # el resultado entra al estado solo al terminar el día
            constructor.registrar(p)
            base[p["liga"]][metricas.INDICE[p["resultado"]]] += 1
        for x, res in nuevos_apilador:
            apilador.actualizar(x, res)
    return registros


def _registro(p, f, hp, constructor, base, apilador, nuevos_apilador) -> dict:
    tasa = base[p["liga"]]
    total = sum(tasa)
    dc = dixon_coles.probabilidades_desde_lambdas(f["lam_h"], f["lam_a"], hp["rho"])
    ap = p["ap_prom"]
    shin = lambda c: mercado.quitar_margen_shin(*c) if c else None  # noqa: E731
    r = {
        "dia": p["dia"], "liga": p["liga"], "res": p["resultado"],
        "tb": tuple(x / total for x in tasa) if total >= 100 else None, "dc": dc,
        "m_ap_shin": shin(ap), "m_ap_prop": mercado.quitar_margen_proporcional(*ap) if ap else None,
        "m_ci_pin": shin(p["ci_pinnacle"]), "m_ci_prom": shin(p["ci_prom"]), "dcm": None,
    }
    d = constructor.construir(p)
    d_a = senales.con_cuotas(d, ap)
    hist_b = dc
    hist_a = dc
    if r["m_ap_shin"]:
        x = emh._caracteristicas(dc, r["m_ap_shin"])
        r["dcm"] = apilador.predecir(x, p["dia"])
        nuevos_apilador.append((x, p["resultado"]))
        hist_a = r["dcm"] or dc  # igual que producción: sin apilador entrenado queda el DC solo
    mods_a = senales.ejecutar_modulos(d_a, hist_a)
    mods_b = {m: v for m, v in mods_a.items() if m not in ("odds", "poisson", "historico")}
    if "poisson" in mods_a:  # sin cuotas el score de confianza del Poisson cambia (no sus probabilidades)
        mods_b["poisson"] = pronostico.analizar(d) if ap else mods_a["poisson"]
    mods_b["historico"] = senales.resultado_historico(hist_b)
    r["A"] = {m: _t(v) for m, v in mods_a.items()} if ap else None
    r["B"] = {m: _t(v) for m, v in mods_b.items()}
    # Variante con H2H orientado al local actual (producción cuenta desde el local del partido histórico).
    d_c = constructor.construir(p, "corregida")
    from backend.api.services import h2h as h2h_svc
    r["h2h_c"] = _t(h2h_svc.analizar(d_c)) if h2h_svc.validar_h2h(d_c)[0] else None
    es_poisson = d_c["fuente_goles"] != "liga_generico" and not (d_c["fuente_goles"] == "h2h_real" and d_c["h2h_total"] < 3)
    r["poisson_c"] = _t(pronostico.analizar(d_c)) if es_poisson else None
    return r


# ------------------------------------------------------------------ métricas (vectorizadas)
def _arr(filas: list[tuple]) -> np.ndarray:
    return np.asarray(filas, dtype=float)


def metricas_np(P: np.ndarray, y: np.ndarray) -> dict:
    """RPS, Brier, log-loss, accuracy medios (misma definición que `ml/metricas.py`) y vectores por partido."""
    n = len(y)
    O = np.eye(3)[y]
    rps = 0.5 * ((P[:, 0] - O[:, 0]) ** 2 + (np.cumsum(P, 1)[:, 1] - np.cumsum(O, 1)[:, 1]) ** 2)
    brier = ((P - O) ** 2).sum(1)
    ll = -np.log(np.maximum(P[np.arange(n), y], metricas.EPS))
    acc = (P.argmax(1) == y).astype(float)
    return {"n": n, "rps": rps, "brier": brier, "log_loss": ll, "acc": acc}


def resumen_np(m: dict) -> dict:
    return {"n": m["n"], "rps": round(float(m["rps"].mean()), 5), "brier": round(float(m["brier"].mean()), 5),
            "log_loss": round(float(m["log_loss"].mean()), 5), "accuracy": round(float(m["acc"].mean()), 4)}


def diferencia_bootstrap(a: np.ndarray, b: np.ndarray, rng, n_boot: int = 2000) -> dict:
    """Media de (a - b) por partido con IC 95% bootstrap pareado (negativo = `a` mejor, métricas de error)."""
    d = a - b
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    medias = d[idx].mean(1)
    lo, hi = np.percentile(medias, [2.5, 97.5])
    return {"dif_media": round(float(d.mean()), 5), "ic95": [round(float(lo), 5), round(float(hi), 5)],
            "mejora_significativa": bool(hi < 0), "empeora_significativa": bool(lo > 0)}


def _y(regs: list[dict]) -> np.ndarray:
    return np.array([metricas.INDICE[r["res"]] for r in regs])


def tabla_modelos(regs: list[dict], claves: dict[str, callable]) -> tuple[dict, dict]:
    """Métricas de cada modelo sobre los MISMOS partidos (los que todos tienen)."""
    ok = [r for r in regs if all(f(r) is not None for f in claves.values())]
    y = _y(ok)
    mm = {k: metricas_np(_arr([f(r)[:3] for r in ok]), y) for k, f in claves.items()}
    return {k: resumen_np(m) for k, m in mm.items()}, mm


# ------------------------------------------------------------------ consenso sobre los registros
def escenario_real(r: dict) -> dict:
    return r["A"] if r["A"] is not None else r["B"]


def consenso_de(r: dict, escenario: str, pesos: dict | None) -> dict | None:
    mods = escenario_real(r) if escenario == "real" else r[escenario]
    return ec.evaluar_consenso(mods, pesos)


def correr_consenso(regs: list[dict], escenario: str, pesos: dict | None) -> list[dict | None]:
    return [consenso_de(r, escenario, pesos) for r in regs]


def _con_consenso(regs, escenario, pesos):
    """Pares (registro, consenso) con consenso válido."""
    salida = []
    for r, c in zip(regs, correr_consenso(regs, escenario, pesos)):
        if c is not None:
            salida.append((r, c))
    return salida


# ------------------------------------------------------------------ pesos aprendidos
def _cols_pool(regs: list[dict], escenario: str, modulos: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Tensor (n, módulos, 3) de probabilidades y máscara de disponibilidad."""
    n = len(regs)
    X = np.zeros((n, len(modulos), 3))
    M = np.zeros((n, len(modulos)), dtype=bool)
    for i, r in enumerate(regs):
        mods = escenario_real(r) if escenario == "real" else r[escenario]
        for j, m in enumerate(modulos):
            if m in mods:
                X[i, j] = mods[m][:3]
                M[i, j] = True
    return X, M


def aprender_pool(regs: list[dict], escenario: str, modulos: tuple[str, ...]) -> dict:
    """Pesos de mezcla lineal (renormalizada entre módulos presentes) que minimizan log-loss. Es la forma
    exacta en que `consenso` mezcla probabilidades, sin los factores por score."""
    from scipy.optimize import minimize
    X, M = _cols_pool(regs, escenario, modulos)
    y = _y(regs)
    n, k = M.shape
    validos = M.any(1)
    X, M, y = X[validos], M[validos], y[validos]

    def log_loss(theta):
        w = np.exp(theta - theta.max())
        w = w / w.sum()
        pesos = M * w
        tot = pesos.sum(1, keepdims=True)
        P = (X * pesos[:, :, None]).sum(1) / tot
        return float(-np.log(np.maximum(P[np.arange(len(y)), y], 1e-12)).mean())

    mejor = None
    rng = np.random.default_rng(0)
    for inicio in [np.zeros(k)] + [rng.normal(size=k) for _ in range(4)]:
        res = minimize(log_loss, inicio, method="L-BFGS-B")
        if mejor is None or res.fun < mejor.fun:
            mejor = res
    w = np.exp(mejor.x - mejor.x.max())
    w = w / w.sum()
    return {"pesos": {m: round(float(v), 4) for m, v in zip(modulos, w)}, "log_loss_dev": round(float(mejor.fun), 5), "n_dev": int(len(y))}


def _features_lr(regs: list[dict], escenario: str, modulos: tuple[str, ...]) -> np.ndarray:
    filas = []
    for r in regs:
        mods = dict(escenario_real(r) if escenario == "real" else r[escenario])
        mods["dc"] = r["dc"]  # DC puro (el `historico` de producción en A ya incluye el mercado)
        cols = []
        for m in modulos:
            p = mods.get(m)
            if p is None or (m == "odds" and escenario == "B"):
                cols += [0.0, 0.0]
            else:
                cols += [math.log(max(p[0], 1e-6) / max(p[1], 1e-6)), math.log(max(p[2], 1e-6) / max(p[1], 1e-6))]
        filas.append(cols)
    return np.asarray(filas)


def ajustar_lr(dev: list[dict], escenario: str, modulos: tuple[str, ...]) -> dict:
    """Regresión logística multinomial regularizada; C por validación temporal (años 2020-22 dentro de desarrollo)."""
    from sklearn.linear_model import LogisticRegression
    X = _features_lr(dev, escenario, modulos)
    y = _y(dev)
    dias = np.array([r["dia"] for r in dev])
    cortes = [date(a, 7, 1).toordinal() for a in (2020, 2021, 2022, 2023)]
    mejor = (float("inf"), 1.0)
    detalle = {}
    for C in (0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 10.0):
        perdidas = []
        for ini, fin in zip(cortes[:-1], cortes[1:]):
            tr, va = dias < ini, (dias >= ini) & (dias < fin)
            if tr.sum() < 2000 or va.sum() < 200:
                continue
            m = LogisticRegression(C=C, max_iter=2000).fit(X[tr], y[tr])
            P = m.predict_proba(X[va])
            perdidas.append(float(-np.log(np.maximum(P[np.arange(va.sum()), y[va]], 1e-12)).mean()))
        ll = float(np.mean(perdidas)) if perdidas else float("inf")
        detalle[str(C)] = round(ll, 5)
        if ll < mejor[0]:
            mejor = (ll, C)
    modelo = LogisticRegression(C=mejor[1], max_iter=2000).fit(X, y)
    return {"modelo": modelo, "C": mejor[1], "cv_log_loss": detalle, "modulos": modulos, "escenario": escenario}


def predecir_lr(lr: dict, regs: list[dict]) -> np.ndarray:
    return lr["modelo"].predict_proba(_features_lr(regs, lr["escenario"], lr["modulos"]))


# ------------------------------------------------------------------ análisis por bloque
def _pares(regs, consensos):
    return [{"probs": c["probs"], "res": r["res"], "score": c["score"], "nivel": c["nivel"],
             "confianza": c["confianza"], "idx": c["idx"]} for r, c in zip(regs, consensos)]


def tabla_umbrales(filas: list[dict]) -> list[dict]:
    salida = []
    for u in UMBRALES_PROB:
        sub = [f for f in filas if max(f["probs"]) >= u]
        if not sub:
            continue
        t = ec.tabla_por_grupos(sub, lambda f: "todos")[0]
        t.pop("grupo")
        salida.append({"prob_pick_min": u, "cobertura": round(len(sub) / len(filas), 4), **t})
    return salida


def bandas_score(f: dict) -> str:
    s = f["score"]
    return "a) <45" if s < 45 else "b) 45-59" if s < 60 else "c) 60-69" if s < 70 else "d) >=70"


def publicacion(regs: list[dict], escenario: str, pesos: dict | None) -> dict:
    pares = _pares(*zip(*_con_consenso(regs, escenario, pesos))) if regs else []
    return {
        "n": len(pares),
        "por_umbral_prob_ponderada": tabla_umbrales(pares),
        "por_confianza_final": ec.tabla_por_grupos(pares, lambda f: f["confianza"]),
        "por_banda_score": ec.tabla_por_grupos(pares, bandas_score),
        "por_nivel": ec.tabla_por_grupos(pares, lambda f: f["nivel"]),
        "distribucion_picks": ec.distribucion_picks(pares),
        "calibracion_pick": calibracion_pick(pares),
    }


def calibracion_pick(filas: list[dict]) -> list[dict]:
    """Probabilidad del pick por tramos de 0.05 → frecuencia real de acierto."""
    def tramo(f):
        p = max(f["probs"])
        return f"{math.floor(p * 20) / 20:.2f}"
    return ec.tabla_por_grupos(filas, tramo)


def nombre_pesos(p: dict) -> dict:
    return {k: round(v, 3) for k, v in p.items() if v}


def evaluar_candidatos(dev: list[dict], test: list[dict], candidatos: dict[str, dict | None]) -> dict:
    """Consenso real con cada juego de pesos: log-loss en desarrollo (para elegir) y prueba (para reportar)."""
    salida = {}
    for nombre, pesos in candidatos.items():
        fila = {"pesos": nombre_pesos(pesos) if pesos else "vigentes"}
        con_c = [r for r in test if r["A"] is not None]
        sin_c = [r for r in test if r["A"] is None]
        for etiqueta, regs in (("dev", dev), ("prueba", test), ("prueba_con_cuotas", con_c), ("prueba_sin_cuotas_apertura", sin_c)):
            pares = [(r, c) for r, c in _con_consenso(regs, "real", pesos)]
            if not pares:
                continue
            P = _arr([c["probs"] for _, c in pares])
            fila[etiqueta] = resumen_np(metricas_np(P, _y([r for r, _ in pares])))
        salida[nombre] = fila
    return salida


def ablacion(test: list[dict], escenario: str) -> dict:
    """Quita un módulo cada vez del consenso vigente y mide el cambio en log-loss/RPS sobre los mismos partidos."""
    sub = [r for r in test if (escenario != "A" or r["A"] is not None)]
    base_pares = _con_consenso(sub, escenario, None)
    regs = [r for r, _ in base_pares]
    y = _y(regs)
    m0 = metricas_np(_arr([c["probs"] for _, c in base_pares]), y)
    salida = {"consenso_vigente": resumen_np(m0)}
    for modulo in MODULOS_CONSENSO:
        pesos = {m: w for m, w in consenso.PESOS_BASE.items() if m != modulo}
        cs = correr_consenso(regs, escenario, pesos)
        idx = [i for i, c in enumerate(cs) if c is not None]
        if not idx:
            continue
        m1 = metricas_np(_arr([cs[i]["probs"] for i in idx]), y[idx])
        base_ll = m0["log_loss"][idx].mean()
        base_rps = m0["rps"][idx].mean()
        salida[f"sin_{modulo}"] = {**resumen_np(m1), "delta_log_loss_vs_vigente": round(float(m1["log_loss"].mean() - base_ll), 5),
                                   "delta_rps_vs_vigente": round(float(m1["rps"].mean() - base_rps), 5)}
    return salida


def por_liga(test_a: list[dict], pesos_aprendidos: dict, top: int = 10) -> dict:
    cuenta = defaultdict(int)
    for r in test_a:
        cuenta[r["liga"]] += 1
    salida = {}
    for liga, n in sorted(cuenta.items(), key=lambda kv: -kv[1])[:top]:
        regs = [r for r in test_a if r["liga"] == liga and r["m_ap_shin"] and r["tb"]]
        if len(regs) < 100:
            continue
        y = _y(regs)
        fila = {"n": len(regs)}
        fila["tasa_base"] = resumen_np(metricas_np(_arr([r["tb"] for r in regs]), y))
        fila["mercado_apertura"] = resumen_np(metricas_np(_arr([r["m_ap_shin"] for r in regs]), y))
        fila["dixon_coles"] = resumen_np(metricas_np(_arr([r["dc"] for r in regs]), y))
        for nombre, pesos in (("consenso_vigente", None), ("consenso_pesos_aprendidos", pesos_aprendidos)):
            cs = correr_consenso(regs, "A", pesos)
            fila[nombre] = resumen_np(metricas_np(_arr([c["probs"] for c in cs]), y))
        salida[liga] = fila
    return salida


def cobertura(test: list[dict], escenario: str) -> dict:
    n = len(test)
    cont = defaultdict(int)
    for r in test:
        for m in (escenario_real(r) if escenario == "real" else r[escenario]):
            cont[m] += 1
    return {m: round(c / n, 4) for m, c in sorted(cont.items())} | {"n_partidos": n}


# ------------------------------------------------------------------ programa
def construir_informe(regs: list[dict], hp: dict, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    dev = [r for r in regs if r["dia"] < CORTE]
    test = [r for r in regs if r["dia"] >= CORTE]
    test_a = [r for r in test if r["A"] is not None]
    informe: dict = {"semilla": seed, "hiperparametros_dc": hp, "n_registros": len(regs), "n_dev": len(dev),
                     "n_prueba": len(test), "n_prueba_con_cuotas_apertura": len(test_a),
                     "pesos_vigentes": dict(consenso.PESOS_BASE)}
    informe["cobertura_modulos_prueba_con_cuotas"] = cobertura(test_a, "A")
    informe["cobertura_modulos_prueba_sin_cuotas_apertura"] = cobertura([r for r in test if r["A"] is None], "B")

    print("aprendiendo pesos (desarrollo)...", flush=True)
    dev_a = [r for r in dev if r["A"] is not None]
    pool_real = aprender_pool(dev, "real", MODULOS_CONSENSO)
    pool_b = aprender_pool(dev, "B", tuple(m for m in MODULOS_CONSENSO if m != "odds"))
    informe["pesos_aprendidos_pool_real"] = pool_real
    informe["pesos_aprendidos_pool_sin_cuotas"] = pool_b
    lr_a = ajustar_lr(dev_a, "A", MODULOS_LR)
    lr_b = ajustar_lr(dev, "B", tuple(m for m in MODULOS_LR if m != "odds"))
    lr_mkt = ajustar_lr(dev_a, "A", ("odds",))
    lr_dcm = ajustar_lr(dev_a, "A", ("dc", "odds"))
    informe["lr"] = {k: {"C": v["C"], "cv_log_loss": v["cv_log_loss"]} for k, v in
                     {"todas_con_cuotas": lr_a, "sin_cuotas": lr_b, "mercado_recalibrado": lr_mkt, "dc_mas_mercado": lr_dcm}.items()}

    # ---- A: con cuotas, mismos partidos
    base_a = [r for r in test_a if r["tb"] and r["m_ci_pin"] and r["m_ap_shin"]]
    pesos_pool = pool_real["pesos"]
    cons_vig = {id(r): consenso_de(r, "A", None) for r in base_a}
    cons_apr = {id(r): consenso_de(r, "A", pesos_pool) for r in base_a}
    base_a = [r for r in base_a if cons_vig[id(r)] and cons_apr[id(r)]]
    Plr = {"lr_todas": predecir_lr(lr_a, base_a), "lr_mercado_recalibrado": predecir_lr(lr_mkt, base_a),
           "lr_dc_mas_mercado": predecir_lr(lr_dcm, base_a)}
    claves = {
        "tasa_base": lambda r: r["tb"], "mercado_apertura_shin": lambda r: r["m_ap_shin"],
        "mercado_apertura_proporcional": lambda r: r["m_ap_prop"], "mercado_cierre_pinnacle": lambda r: r["m_ci_pin"],
        "dixon_coles": lambda r: r["dc"], "dc_mas_mercado_apilador_vigente": lambda r: r["dcm"] or r["dc"],
        "consenso_vigente": lambda r: cons_vig[id(r)]["probs"], "consenso_pesos_aprendidos": lambda r: cons_apr[id(r)]["probs"],
    }
    resumen_a, mm = tabla_modelos(base_a, claves)
    y = _y(base_a)
    for nombre, P in Plr.items():
        m = metricas_np(P, y)
        resumen_a[nombre] = resumen_np(m)
        mm[nombre] = m
    informe["A_con_cuotas_mismos_partidos"] = {"n": len(base_a), "modelos": resumen_a}
    ref = mm["mercado_apertura_shin"]
    informe["A_diferencia_vs_mercado_apertura"] = {
        nombre: {"log_loss": diferencia_bootstrap(m["log_loss"], ref["log_loss"], rng),
                 "rps": diferencia_bootstrap(m["rps"], ref["rps"], rng)}
        for nombre, m in mm.items() if nombre != "mercado_apertura_shin"}

    # ---- módulos sueltos (cobertura propia, comparados con mercado y tasa base en SUS partidos)
    sueltos = {}
    mods_a = {"poisson": lambda r: r["A"].get("poisson"), "forma": lambda r: r["A"].get("forma"),
              "h2h": lambda r: r["A"].get("h2h"), "tabla": lambda r: r["A"].get("tabla"),
              "odds_modulo": lambda r: r["A"].get("odds"), "historico_apilado": lambda r: r["A"].get("historico"),
              "h2h_orientado_al_local_actual": lambda r: r["h2h_c"], "poisson_h2h_orientado": lambda r: r["poisson_c"]}
    for nombre, f in mods_a.items():
        res, _ = tabla_modelos(base_a, {"tasa_base": lambda r: r["tb"], "mercado_apertura_shin": lambda r: r["m_ap_shin"],
                                        "dixon_coles": lambda r: r["dc"], nombre: f})
        sueltos[nombre] = {"n": res["tasa_base"]["n"], **res}
    informe["A_modulos_sueltos_en_su_cobertura"] = sueltos
    informe["A_ablacion_consenso_vigente"] = ablacion(test_a, "A")
    informe["A_publicacion_consenso_vigente"] = publicacion(base_a, "A", None)
    informe["A_publicacion_mercado_apertura"] = {
        "por_umbral_prob": tabla_umbrales([{"probs": r["m_ap_shin"], "res": r["res"]} for r in base_a]),
        "calibracion_pick": calibracion_pick([{"probs": r["m_ap_shin"], "res": r["res"]} for r in base_a])}
    informe["A_publicacion_consenso_pesos_aprendidos"] = publicacion(base_a, "A", pesos_pool)
    informe["A_distribucion_picks_otros"] = {
        "mercado": ec.distribucion_picks([{"probs": r["m_ap_shin"], "res": r["res"]} for r in base_a]),
        "dixon_coles": ec.distribucion_picks([{"probs": r["dc"], "res": r["res"]} for r in base_a]),
        "poisson_actual": ec.distribucion_picks([{"probs": r["A"]["poisson"][:3], "res": r["res"]} for r in base_a if "poisson" in r["A"]])}
    informe["A_regla_de_pick"] = regla_pick(base_a, cons_vig, cons_apr, Plr)
    informe["A_por_liga"] = por_liga(test_a, pesos_pool)

    # ---- B: mismos partidos SIN cuotas (simulado) y C: ligas sin cuotas de apertura (real)
    informe["B_sin_cuotas_simulado_mismos_partidos"] = bloque_sin_cuotas(
        base_a, "B", pesos_pool_b=pool_b["pesos"], lr_b=lr_b, referencia={"mercado_apertura_shin": lambda r: r["m_ap_shin"]}, rng=rng)
    test_c = [r for r in test if r["A"] is None and r["tb"] and r["m_ci_prom"]]
    informe["C_ligas_sin_apertura_sin_cuotas_real"] = bloque_sin_cuotas(
        test_c, "B", pesos_pool_b=pool_b["pesos"], lr_b=lr_b, referencia={"mercado_cierre_promedio_referencia": lambda r: r["m_ci_prom"]}, rng=rng)

    # ---- candidatos de pesos: se elige en desarrollo, se reporta en prueba
    cands = candidatos(pool_real["pesos"])
    informe["candidatos_pesos_escenario_real"] = evaluar_candidatos(dev, test, cands)
    # Solo compiten candidatos que cubren TODOS los partidos (un consenso solo-odds no opina sin cuotas).
    cand = informe["candidatos_pesos_escenario_real"]
    completos = [k for k in cands if cand[k].get("prueba", {}).get("n") == len(test) and cand[k].get("dev", {}).get("n") == len(dev)]
    elegido = min(completos, key=lambda k: cand[k]["dev"]["log_loss"])
    pesos_elegido = cands[elegido]
    informe["publicacion_elegido_con_cuotas"] = publicacion(base_a, "A", pesos_elegido)
    informe["publicacion_elegido_sin_cuotas_simulado"] = publicacion(base_a, "B", pesos_elegido)
    informe["publicacion_elegido_ligas_sin_apertura"] = publicacion(test_c, "B", pesos_elegido)
    informe["candidato_elegido_en_desarrollo"] = elegido
    return informe


def candidatos(pool: dict) -> dict[str, dict | None]:
    redondeado = {m: round(w * 20) / 20 for m, w in pool.items()}
    return {
        "vigentes": None,
        "pool_aprendido": dict(pool),
        "pool_aprendido_redondeado_0.05": {m: w for m, w in redondeado.items() if w > 0},
        "solo_odds_historico_70_30": {"odds": 0.7, "historico": 0.3},
        "odds_historico_poisson_55_30_15": {"odds": 0.55, "historico": 0.30, "poisson": 0.15},
        "sin_forma_h2h_tabla": {k: v for k, v in consenso.PESOS_BASE.items() if k in ("poisson", "historico", "odds")},
        "solo_odds": {"odds": 1.0},
        "solo_historico": {"historico": 1.0},
        "rec_odds70_hist25_forma2_tabla3": {"odds": 0.70, "historico": 0.25, "forma": 0.02, "tabla": 0.03},
        "rec_odds60_hist30_forma4_tabla6": {"odds": 0.60, "historico": 0.30, "forma": 0.04, "tabla": 0.06},
        "rec_odds50_hist40_forma4_tabla6": {"odds": 0.50, "historico": 0.40, "forma": 0.04, "tabla": 0.06},
        "rec_hist90_forma4_tabla6": {"historico": 0.90, "forma": 0.04, "tabla": 0.06},
    }


def regla_pick(base_a: list[dict], cons_vig: dict, cons_apr: dict, Plr: dict) -> dict:
    y = _y(base_a)
    reglas = {
        "argmax_prob_ponderada_vigente": np.array([cons_vig[id(r)]["idx"] for r in base_a]),
        "argmax_prob_ponderada_pesos_aprendidos": np.array([cons_apr[id(r)]["idx"] for r in base_a]),
        "argmax_mercado_apertura": np.array([int(np.argmax(r["m_ap_shin"])) for r in base_a]),
        "argmax_lr_todas": Plr["lr_todas"].argmax(1),
        "siempre_local": np.zeros(len(base_a), dtype=int),
    }
    salida = {}
    for nombre, pick in reglas.items():
        acc = float((pick == y).mean())
        salida[nombre] = {"accuracy": round(acc, 4), "ic95": list(ec.wilson(int((pick == y).sum()), len(y))),
                          "reparto_picks": {e: round(float((pick == i).mean()), 4) for i, e in enumerate("HDA")}}
    coinciden = np.array([cons_vig[id(r)]["idx"] == int(np.argmax(r["m_ap_shin"])) for r in base_a])
    salida["consenso_vigente_coincide_con_mercado"] = round(float(coinciden.mean()), 4)
    salida["accuracy_si_coinciden"] = round(float((reglas["argmax_mercado_apertura"] == y)[coinciden].mean()), 4)
    salida["accuracy_consenso_si_discrepan"] = round(float((reglas["argmax_prob_ponderada_vigente"] == y)[~coinciden].mean()), 4)
    salida["accuracy_mercado_si_discrepan"] = round(float((reglas["argmax_mercado_apertura"] == y)[~coinciden].mean()), 4)
    return salida


def bloque_sin_cuotas(regs: list[dict], escenario: str, pesos_pool_b: dict, lr_b: dict, referencia: dict, rng) -> dict:
    cs_v = {id(r): consenso_de(r, escenario, None) for r in regs}
    cs_a = {id(r): consenso_de(r, escenario, pesos_pool_b) for r in regs}
    regs = [r for r in regs if cs_v[id(r)] and cs_a[id(r)]]
    claves = {"tasa_base": lambda r: r["tb"], "dixon_coles": lambda r: r["dc"],
              "consenso_vigente_sin_odds": lambda r: cs_v[id(r)]["probs"],
              "consenso_pesos_aprendidos_sin_odds": lambda r: cs_a[id(r)]["probs"], **referencia}
    resumen, mm = tabla_modelos(regs, claves)
    y = _y(regs)
    m_lr = metricas_np(predecir_lr(lr_b, regs), y)
    resumen["lr_sin_cuotas"] = resumen_np(m_lr)
    mm["lr_sin_cuotas"] = m_lr
    dif = {n: {"log_loss": diferencia_bootstrap(m["log_loss"], mm["dixon_coles"]["log_loss"], rng),
               "rps": diferencia_bootstrap(m["rps"], mm["dixon_coles"]["rps"], rng)}
           for n, m in mm.items() if n not in ("dixon_coles",)}
    pares = _pares(regs, [cs_v[id(r)] for r in regs])
    return {"n": len(regs), "modelos": resumen, "diferencia_vs_dixon_coles": dif,
            "publicacion_consenso_vigente_sin_odds": {
                "por_umbral_prob_ponderada": tabla_umbrales(pares), "por_confianza_final": ec.tabla_por_grupos(pares, lambda f: f["confianza"]),
                "por_banda_score": ec.tabla_por_grupos(pares, bandas_score), "distribucion_picks": ec.distribucion_picks(pares)},
            "ablacion": ablacion(regs, escenario)}


def activar_formula_poisson_vieja() -> None:
    """Reemplaza `pronostico.calcular_lambdas` por la versión previa a la corrección del agente B
    (2026-10-07): dividía los goles POR EQUIPO entre `liga_avg`, que es el promedio de goles TOTALES.
    Se deriva del código actual cambiando solo esa línea, para no mantener una copia que se desvíe."""
    import inspect
    fuente = inspect.getsource(pronostico.calcular_lambdas)
    vieja = fuente.replace("media_equipo = liga_avg_safe / 2.0", "media_equipo = liga_avg_safe")
    if vieja == fuente:
        raise RuntimeError("calcular_lambdas ya no contiene `media_equipo = liga_avg_safe / 2.0`: revisar este parche")
    exec(vieja, pronostico.__dict__)  # noqa: S102 - código propio del repo, solo para esta medición


def medir_formula_poisson(por_liga: dict[str, list[dict]]) -> dict:
    """Poisson de temporada (réplica `ProduccionPoisson`) con la fórmula corregida y la vieja, contra tasa base,
    en el periodo de prueba y sobre los mismos partidos. Usa el código actual de `pronostico`."""
    corregida = pronostico.calcular_lambdas
    activar_formula_poisson_vieja()
    vieja = pronostico.calcular_lambdas
    pronostico.calcular_lambdas = corregida
    try:
        todos = sorted((p for ps in por_liga.values() for p in ps), key=lambda p: (p["dia"], p["liga"]))
        prods = {"corregida": (emh.ProduccionPoisson(), corregida), "vieja": (emh.ProduccionPoisson(), vieja)}
        base: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        filas = []
        for p in todos:
            if p["dia"] >= CORTE:
                tasa, tot = base[p["liga"]], sum(base[p["liga"]])
                fila = {"res": p["resultado"], "tb": tuple(x / tot for x in tasa) if tot >= 100 else None}
                for nombre, (prod, fn) in prods.items():
                    pronostico.calcular_lambdas = fn
                    fila[nombre] = prod.predecir(p)
                pronostico.calcular_lambdas = corregida
                filas.append(fila)
            for prod, _ in prods.values():
                prod.actualizar(p)
            base[p["liga"]][metricas.INDICE[p["resultado"]]] += 1
    finally:
        pronostico.calcular_lambdas = corregida
    comunes = [f for f in filas if f["tb"] and f["corregida"] and f["vieja"]]
    y = _y(comunes)
    salida = {"n": len(comunes)}
    for nombre in ("tb", "corregida", "vieja"):
        salida["tasa_base" if nombre == "tb" else f"poisson_{nombre}"] = resumen_np(metricas_np(_arr([f[nombre] for f in comunes]), y))
    salida["reparto_picks_corregida"] = ec.distribucion_picks([{"probs": f["corregida"], "res": f["res"]} for f in comunes])
    salida["reparto_picks_vieja"] = ec.distribucion_picks([{"probs": f["vieja"], "res": f["res"]} for f in comunes])
    return salida


def hiperparametros() -> dict:
    ruta = emh.ARTEFACTOS / "dixon_coles_ligas.json"
    try:
        hp = json.loads(ruta.read_text(encoding="utf-8"))["hiperparametros"]
        return {k: hp[k] for k in ("xi", "ridge", "rho")}
    except (OSError, KeyError, ValueError):
        return {"xi": dixon_coles.XI_POR_DEFECTO, "ridge": dixon_coles.RIDGE_POR_DEFECTO, "rho": dixon_coles.RHO_POR_DEFECTO}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ligas", nargs="*", help="códigos de liga (por defecto todas)")
    ap.add_argument("--rapido", action="store_true", help="subconjunto de 10 ligas y evaluación desde 2020-07")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--poisson-formula-vieja", action="store_true",
                    help="evalúa con la fórmula de λ previa a la corrección de unidades (solo para comparar)")
    ap.add_argument("--solo-formula-poisson", action="store_true", help="solo mide Poisson vieja vs corregida y sale")
    ap.add_argument("--cache", type=Path, help="pickle intermedio (acelera iteraciones; se crea si no existe)")
    ap.add_argument("--salida", type=Path, default=SALIDA)
    args = ap.parse_args()
    inicio = time.time()
    np.random.seed(args.seed)
    if args.poisson_formula_vieja:
        activar_formula_poisson_vieja()
    if args.solo_formula_poisson:
        por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
        if args.ligas:
            por_liga = {k: v for k, v in por_liga.items() if k in args.ligas}
        informe = medir_formula_poisson(por_liga)
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(informe, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(informe, indent=1))
        return

    if args.cache and args.cache.exists():
        # El pickle lo genera este mismo script en .qa/ (local, no confiable solo si alguien lo reemplaza).
        regs, hp = pickle.loads(args.cache.read_bytes())
        print(f"cache: {len(regs)} registros", flush=True)
    else:
        por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
        filtro = args.ligas or (LIGAS_RAPIDO if args.rapido else None)
        if filtro:
            por_liga = {k: v for k, v in por_liga.items() if k in filtro}
        print(f"{sum(map(len, por_liga.values()))} partidos, {len(por_liga)} ligas", flush=True)
        hp = hiperparametros()
        desde = date(2020, 7, 1).toordinal() if args.rapido else emh.INICIO_EVALUACION
        regs = recorrer(por_liga, hp, desde)
        print(f"walk-forward listo: {len(regs)} registros ({time.time() - inicio:.0f}s)", flush=True)
        if args.cache:
            args.cache.parent.mkdir(parents=True, exist_ok=True)
            args.cache.write_bytes(pickle.dumps((regs, hp)))

    informe = construir_informe(regs, hp, args.seed)
    informe["rapido"] = bool(args.rapido)
    informe["formula_poisson"] = "vieja (λ a la mitad)" if args.poisson_formula_vieja else "corregida (media por equipo)"
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(informe, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"informe: {args.salida} ({time.time() - inicio:.0f}s)")


if __name__ == "__main__":
    main()
