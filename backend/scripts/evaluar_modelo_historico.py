"""backend/scripts/evaluar_modelo_historico.py — evaluación walk-forward con datos históricos reales.

Responde con números medidos (no con opinión) a la pregunta central del proyecto: ¿los
pronósticos del bot le ganan al mercado y a un modelo de referencia? Cada partido se predice
usando SOLO información anterior a su fecha:

  tasa_base         frecuencias H/D/A acumuladas de la liga (el "modelo tonto").
  mercado_*         cuotas sin margen (apertura promedio, cierre Pinnacle) — el rival a vencer.
  poisson_actual    réplica del motor en producción (`services/pronostico.py`): promedios de
                    goles de la temporada en curso por equipo + ventaja de local fija.
  dixon_coles       `ml/dixon_coles.py`: fuerzas por liga con decaimiento temporal.
  dc_mas_mercado    regresión logística (apilado) sobre las probabilidades de DC y del mercado.

Hiperparámetros (xi, ridge, rho) se eligen SOLO con el periodo de desarrollo (< 2023-07-01) y el
resultado que se reporta es el del periodo de prueba (>= 2023-07-01), que el tuning nunca vio.

Requiere numpy, scipy y scikit-learn (solo para ajustar/evaluar, no para el bot en ejecución).
Uso:  python backend/scripts/evaluar_modelo_historico.py [--ligas E0 SP1 ...] [--sin-tuning]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import datos, dixon_coles, mercado, metricas  # noqa: E402
from backend.api.services import pronostico  # noqa: E402
from backend.api.services.ligas import get_liga_avg  # noqa: E402

CORTE_DEV_TEST = date(2023, 7, 1).toordinal()
INICIO_EVALUACION = date(2018, 7, 1).toordinal()  # 2 temporadas (1516, 1617) de calentamiento
REFIT_DIAS = 28
LIGAS_TUNING = ("E0", "SP1", "I1", "D1", "F1", "N1")
GRID_XI = (0.0, 0.001, 0.0019, 0.003)
GRID_RIDGE = (0.5, 2.0, 5.0)
GRID_RHO = (-0.20, -0.15, -0.10, -0.05, 0.0)
MIN_PARTIDOS_EQUIPO_PROD = 3
ARTEFACTOS = REPO / "backend" / "api" / "ml" / "artefactos"
RESULTADOS = REPO / "backend" / "data" / "resultados"


def _prob_mercado(p: dict, clave: str, metodo) -> tuple[float, float, float] | None:
    c = p.get(clave)
    return metodo(*c) if c else None


def recorrer_dc(por_liga: dict[str, list[dict]], xi: float, ridge: float, desde: int, hasta: int | None = None) -> list[dict]:
    """Recorre cada liga en orden temporal, reajusta DC cada REFIT_DIAS y devuelve, por partido,
    las lambdas predichas con el modelo vigente (ajustado solo con partidos previos)."""
    salida = []
    for liga, partidos in por_liga.items():
        tuplas = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in partidos]
        modelo = None
        proximo_refit = 0
        for i, p in enumerate(partidos):
            if p["dia"] < desde or (hasta is not None and p["dia"] >= hasta):
                continue
            if modelo is None or p["dia"] >= proximo_refit:
                modelo = dixon_coles.ajustar(tuplas[:i], p["dia"], xi=xi, ridge=ridge)
                proximo_refit = p["dia"] + REFIT_DIAS
            if modelo is None:
                continue
            lam_h, lam_a, conocidos = dixon_coles.lambdas(modelo, p["local"], p["visitante"])
            salida.append({"p": p, "lam_h": lam_h, "lam_a": lam_a, "conocidos": conocidos})
    return salida


def _promedio_log_loss(filas: list[dict], rho: float) -> float:
    pares = [(dixon_coles.probabilidades_desde_lambdas(f["lam_h"], f["lam_a"], rho), f["p"]["resultado"]) for f in filas]
    return metricas.promedio(metricas.log_loss, pares) or float("inf")


def tuning(por_liga: dict[str, list[dict]]) -> dict:
    subconjunto = {k: v for k, v in por_liga.items() if k in LIGAS_TUNING}
    mejor = (float("inf"), None, None)
    for xi in GRID_XI:
        for ridge in GRID_RIDGE:
            filas = recorrer_dc(subconjunto, xi, ridge, INICIO_EVALUACION, CORTE_DEV_TEST)
            ll = _promedio_log_loss(filas, dixon_coles.RHO_POR_DEFECTO)
            print(f"  tuning xi={xi:<6} ridge={ridge:<4} log_loss_dev={ll:.5f} (n={len(filas)})", flush=True)
            if ll < mejor[0]:
                mejor = (ll, xi, ridge)
    _, xi, ridge = mejor
    filas = recorrer_dc(subconjunto, xi, ridge, INICIO_EVALUACION, CORTE_DEV_TEST)
    rho = min(GRID_RHO, key=lambda r: _promedio_log_loss(filas, r))
    return {"xi": xi, "ridge": ridge, "rho": rho, "log_loss_dev": round(mejor[0], 5)}


class ProduccionPoisson:
    """Réplica del insumo del motor en producción: promedio de goles a favor/en contra de la
    TEMPORADA EN CURSO por equipo (como `teams/statistics` de api-football, campo `total`),
    mínimo `MIN_PARTIDOS_EQUIPO_PROD` partidos; con menos, producción salta Poisson.

    Llama a `pronostico.calcular_lambdas` vigente: desde 2026-10-07 usa la media POR EQUIPO (liga_avg/2)
    tras la corrección de unidades; las cifras del informe del 2026-09-29 se midieron con la fórmula
    previa (λ a la mitad) y no son reproducibles con el código actual — ver
    `EVALUACION_CONSENSO_HISTORICO_2026-10-06.md` (`--solo-formula-poisson`)."""

    def __init__(self) -> None:
        self.estado: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0])

    def predecir(self, p: dict) -> tuple[float, float, float] | None:
        clave = (p["liga"], p["temporada"])
        gl = self.estado.get((*clave[:1], clave[1], p["local"]))
        gv = self.estado.get((*clave[:1], clave[1], p["visitante"]))
        if not gl or not gv or gl[2] < MIN_PARTIDOS_EQUIPO_PROD or gv[2] < MIN_PARTIDOS_EQUIPO_PROD:
            return None
        favor_l, contra_l = gl[0] / gl[2], gl[1] / gl[2]
        favor_v, contra_v = gv[0] / gv[2], gv[1] / gv[2]
        d = {"goles_local_avg": favor_l, "goles_visit_avg": favor_v,
             "goles_contra_local_avg": contra_l, "goles_contra_visit_avg": contra_v}
        liga_avg = get_liga_avg(p["liga_nombre"], 2.6)
        lam_h, lam_a = pronostico.calcular_lambdas(d, liga_avg)
        r = pronostico.calcular_poisson_math(lam_h, lam_a)
        return r[0], r[1], r[2]

    def actualizar(self, p: dict) -> None:
        for equipo, favor, contra in ((p["local"], p["gl"], p["gv"]), (p["visitante"], p["gv"], p["gl"])):
            e = self.estado[(p["liga"], p["temporada"], equipo)]
            e[0] += favor
            e[1] += contra
            e[2] += 1


def _caracteristicas(pd_: tuple, pm: tuple) -> list[float]:
    def lg(a: tuple) -> list[float]:
        return [math.log(a[0] / a[1]), math.log(a[2] / a[1])]
    return lg(pd_) + lg(pm)


class Apilador:
    """Regresión logística multinomial sobre (log-odds de DC, log-odds del mercado), reajustada
    cada ~90 días solo con partidos ya resueltos (walk-forward)."""

    def __init__(self) -> None:
        self.X: list[list[float]] = []
        self.y: list[int] = []
        self.modelo = None
        self.proximo = 0

    def _ajustar(self) -> None:
        from sklearn.linear_model import LogisticRegression
        self.modelo = LogisticRegression(C=1.0, max_iter=500).fit(self.X, self.y)

    def predecir(self, x: list[float], dia: int) -> tuple[float, float, float] | None:
        if len(self.y) >= 1500 and (self.modelo is None or dia >= self.proximo):
            self._ajustar()
            self.proximo = dia + 90
        if self.modelo is None:
            return None
        p = self.modelo.predict_proba([x])[0]
        return float(p[0]), float(p[1]), float(p[2])

    def actualizar(self, x: list[float], resultado: str) -> None:
        self.X.append(x)
        self.y.append(metricas.INDICE[resultado])


def evaluar(por_liga: dict[str, list[dict]], hp: dict) -> dict:
    filas = recorrer_dc(por_liga, hp["xi"], hp["ridge"], INICIO_EVALUACION)
    por_id = {id(f["p"]): f for f in filas}
    todos = sorted((p for ps in por_liga.values() for p in ps), key=lambda p: (p["dia"], p["liga"]))
    base = defaultdict(lambda: [0, 0, 0])
    prod = ProduccionPoisson()
    apilador = Apilador()
    registros = []

    for p in todos:
        f = por_id.get(id(p))
        if p["dia"] >= INICIO_EVALUACION and f is not None:
            tasa = base[p["liga"]]
            total = sum(tasa)
            r = {"dia": p["dia"], "liga": p["liga"], "res": p["resultado"], "conocidos": f["conocidos"]}
            r["tasa_base"] = tuple(x / total for x in tasa) if total >= 100 else None
            r["dixon_coles"] = dixon_coles.probabilidades_desde_lambdas(f["lam_h"], f["lam_a"], hp["rho"])
            r["mercado_ap_prop"] = _prob_mercado(p, "ap_prom", mercado.quitar_margen_proporcional)
            r["mercado_ap_shin"] = _prob_mercado(p, "ap_prom", mercado.quitar_margen_shin)
            r["mercado_ci_pinnacle"] = _prob_mercado(p, "ci_pinnacle", mercado.quitar_margen_shin)
            r["poisson_actual"] = prod.predecir(p)
            r["dc_mas_mercado"] = None
            if r["mercado_ap_shin"]:
                x = _caracteristicas(r["dixon_coles"], r["mercado_ap_shin"])
                r["dc_mas_mercado"] = apilador.predecir(x, p["dia"])
                apilador.actualizar(x, p["resultado"])
            registros.append(r)
        prod.actualizar(p)
        base[p["liga"]][metricas.INDICE[p["resultado"]]] += 1
    return {"registros": registros, "apilador": apilador}


MODELOS = ("tasa_base", "poisson_actual", "dixon_coles", "mercado_ap_prop", "mercado_ap_shin",
           "mercado_ci_pinnacle", "dc_mas_mercado")


def resumir(registros: list[dict], modelos: tuple[str, ...], filtro=None) -> dict:
    """Métricas de cada modelo sobre el MISMO conjunto de partidos (los que todos tienen)."""
    filas = [r for r in registros if all(r[m] for m in modelos) and (filtro is None or filtro(r))]
    return {m: metricas.resumen([(r[m], r["res"]) for r in filas]) for m in modelos}


PESOS_ACTUALES = {"poisson_actual": 0.32, "mercado_ap_shin": 0.20}  # PESOS_BASE["poisson"], ["odds"]


def mezclar(pesos: dict[str, float], r: dict) -> tuple[float, float, float] | None:
    """Promedio ponderado de probabilidades, renormalizando entre los modelos disponibles —
    igual que `consenso.calcular_pesos_efectivos` con módulos ausentes."""
    disponibles = {m: w for m, w in pesos.items() if w > 0 and r.get(m)}
    total = sum(disponibles.values())
    if not total:
        return None
    return tuple(sum(w * r[m][i] for m, w in disponibles.items()) / total for i in range(3))  # type: ignore[return-value]


def buscar_pesos(registros: list[dict]) -> dict:
    """Rejilla de pesos (poisson_actual, dixon_coles, mercado) minimizando log-loss en DESARROLLO."""
    dev = [r for r in registros if r["dia"] < CORTE_DEV_TEST and r["poisson_actual"] and r["mercado_ap_shin"]]
    mejor = (float("inf"), None)
    paso = 0.05
    for i in range(0, 21):
        for j in range(0, 21 - i):
            w = {"poisson_actual": i * paso, "dixon_coles": j * paso, "mercado_ap_shin": (20 - i - j) * paso}
            ll = metricas.promedio(metricas.log_loss, [(mezclar(w, r), r["res"]) for r in dev]) or float("inf")
            if ll < mejor[0]:
                mejor = (ll, w)
    return {k: round(v, 2) for k, v in mejor[1].items()}


def calibracion(registros: list[dict], modelo: str, k: int = 10) -> list[dict]:
    """Fiabilidad de P(local): por tramo de probabilidad predicha, frecuencia real de victoria local."""
    tramos = [[0, 0, 0.0] for _ in range(k)]
    for r in registros:
        if r[modelo]:
            i = min(int(r[modelo][0] * k), k - 1)
            tramos[i][0] += 1
            tramos[i][1] += r["res"] == "H"
            tramos[i][2] += r[modelo][0]
    return [{"tramo": f"{i / k:.1f}-{(i + 1) / k:.1f}", "n": n, "predicho": round(s / n, 3), "real": round(h / n, 3)}
            for i, (n, h, s) in enumerate(tramos) if n]


def ajustar_artefactos(por_liga: dict[str, list[dict]], hp: dict, apilador: Apilador) -> dict:
    ultimo = max(p["dia"] for ps in por_liga.values() for p in ps) + 1
    ligas = {}
    for codigo, partidos in por_liga.items():
        tuplas = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in partidos]
        m = dixon_coles.ajustar(tuplas, ultimo, xi=hp["xi"], ridge=hp["ridge"], rho=hp["rho"])
        if m:
            ligas[codigo] = {"nombre": partidos[-1]["liga_nombre"], **m.a_dict()}
    apilador._ajustar()
    sk = apilador.modelo
    return {
        "dixon_coles": {"version": "dc-decay-v1", "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "hiperparametros": hp, "ligas": ligas},
        "apilador": {"version": "dc-mercado-lr-v1", "caracteristicas": ["ln(dc_h/dc_d)", "ln(dc_a/dc_d)", "ln(mkt_h/mkt_d)", "ln(mkt_a/mkt_d)"],
                     "clases": ["H", "D", "A"], "coef": sk.coef_.round(5).tolist(), "intercepto": sk.intercept_.round(5).tolist(),
                     "n_entrenamiento": len(apilador.y)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ligas", nargs="*", help="códigos de liga (por defecto todas las del histórico)")
    ap.add_argument("--sin-tuning", action="store_true", help="usa los hiperparámetros por defecto")
    ap.add_argument("--sin-artefactos", action="store_true", help="no escribe ml/artefactos/")
    args = ap.parse_args()

    inicio = time.time()
    partidos = datos.cargar_partidos()
    por_liga = datos.agrupar_por_liga(partidos)
    if args.ligas:
        por_liga = {k: v for k, v in por_liga.items() if k in args.ligas}
    print(f"{sum(map(len, por_liga.values()))} partidos, {len(por_liga)} ligas", flush=True)

    hp = ({"xi": dixon_coles.XI_POR_DEFECTO, "ridge": dixon_coles.RIDGE_POR_DEFECTO, "rho": dixon_coles.RHO_POR_DEFECTO}
          if args.sin_tuning else tuning(por_liga))
    print("hiperparámetros:", hp, flush=True)

    res = evaluar(por_liga, hp)
    regs = res["registros"]
    pesos_propuestos = buscar_pesos(regs)
    print("pesos propuestos (desarrollo):", pesos_propuestos, flush=True)
    for r in regs:
        r["mezcla_actual"] = mezclar({"poisson_actual": PESOS_ACTUALES["poisson_actual"], "mercado_ap_shin": PESOS_ACTUALES["mercado_ap_shin"]}, r)
        r["mezcla_propuesta"] = mezclar(pesos_propuestos, r)
    test = lambda r: r["dia"] >= CORTE_DEV_TEST  # noqa: E731
    solo_mercado = ("tasa_base", "dixon_coles", "mercado_ap_prop", "mercado_ap_shin", "mercado_ci_pinnacle", "dc_mas_mercado")
    informe = {
        "hiperparametros": hp,
        "partidos_evaluados_total": len(regs),
        "prueba_con_todos_los_modelos": resumir(regs, MODELOS, test),
        "prueba_sin_poisson_actual": resumir(regs, solo_mercado, test),
        "prueba_dc_y_base_todas_las_ligas": resumir(regs, ("tasa_base", "dixon_coles"), test),
        "pesos_mezcla_propuestos": pesos_propuestos,
        "prueba_mezclas": resumir(regs, ("poisson_actual", "dixon_coles", "mercado_ap_shin", "mezcla_actual", "mezcla_propuesta"), test),
        "prueba_dc_y_poisson_actual": resumir(regs, ("tasa_base", "poisson_actual", "dixon_coles"), test),
        "cobertura_poisson_actual_prueba": round(
            sum(1 for r in regs if test(r) and r["poisson_actual"]) / max(1, sum(1 for r in regs if test(r))), 3),
        "calibracion_prueba": {m: calibracion([r for r in regs if test(r)], m) for m in ("dixon_coles", "mercado_ap_shin", "dc_mas_mercado")},
        "por_liga_prueba": {
            liga: resumir(regs, ("dixon_coles", "mercado_ap_shin"), lambda r, codigo=liga: test(r) and r["liga"] == codigo)
            for liga in sorted({r["liga"] for r in regs})},
    }
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    destino = RESULTADOS / "evaluacion_modelo_historico.json"
    destino.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in informe.items() if k not in ("calibracion_prueba", "por_liga_prueba")}, indent=2, ensure_ascii=False))
    print(f"informe completo: {destino.relative_to(REPO)} ({time.time() - inicio:.0f}s)")

    if not args.sin_artefactos and not args.ligas:
        ARTEFACTOS.mkdir(parents=True, exist_ok=True)
        art = ajustar_artefactos(por_liga, hp, res["apilador"])
        (ARTEFACTOS / "dixon_coles_ligas.json").write_text(json.dumps(art["dixon_coles"], ensure_ascii=False), encoding="utf-8")
        (ARTEFACTOS / "apilador_dc_mercado.json").write_text(json.dumps(art["apilador"], indent=2), encoding="utf-8")
        print(f"artefactos escritos en {ARTEFACTOS.relative_to(REPO)}")


if __name__ == "__main__":
    main()
