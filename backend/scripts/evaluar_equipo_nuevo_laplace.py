"""Mide si el modelo Laplace, con los valores por defecto de un equipo sin historia (Elo 1500, tasas medias de la liga), le gana a la tasa base de su liga.

Camina en el tiempo por liga sin ver el futuro: antes de cada partido toma el estado, y si algún equipo tiene menos de `N_MIN_EQUIPO` partidos lo cuenta como «equipo nuevo».
Compara RPS y log-loss del modelo, de la tasa base de la liga (frecuencias acumuladas) y, donde hay cuotas, del mercado sin margen. Los pesos son los del modelo vigente
(15 parámetros sobre 135.000 filas: la fuga por usarlos en todo el periodo es despreciable, y se dice en el informe).

Uso: python backend/scripts/evaluar_equipo_nuevo_laplace.py   (escribe backend/data/resultados/evaluacion_equipo_nuevo_laplace.json)
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent  # noqa: E402
from backend.api.ml.laplace import registro  # noqa: E402

CLASES = ("H", "D", "A")
SALIDA = RAIZ / "backend" / "data" / "resultados" / "evaluacion_equipo_nuevo_laplace.json"


def rps(p: tuple[float, float, float], r: str) -> float:
    o = [1.0 if r == c else 0.0 for c in CLASES]
    return sum((sum(p[: i + 1]) - sum(o[: i + 1])) ** 2 for i in range(2)) / 2


def logloss(p: tuple[float, float, float], r: str) -> float:
    return -math.log(max(p[CLASES.index(r)], 1e-9))


def cuotas_sin_margen(p: dict) -> tuple[float, float, float] | None:
    c = next((p[k] for k in ("ci_prom", "ci_pinnacle", "ci_b365", "ap_prom", "ap_pinnacle", "ap_b365") if p.get(k)), None)
    if not c:
        return None
    try:
        return ent.sin_margen(tuple(c)[:3])  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None


def evaluar() -> dict:
    _, art = registro.cargar_vigente_archivo()
    if not art:
        raise SystemExit("no hay modelo vigente")
    h = art.get("hiper") or {}
    pesos = art["universal"]
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    acum: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for codigo, partidos in por_liga.items():
        estado = ent.EstadoLiga(k_elo=h.get("k_elo", ent.K_ELO), alfa=h.get("alfa", ent.ALFA_GOLES), extras=tuple(h.get("extras", ())))
        frec = {c: 0 for c in CLASES}
        for i, p in enumerate(sorted(partidos, key=lambda x: (x["dia"], x["local"]))):
            nuevos = (not estado.conoce(p["local"])) + (not estado.conoce(p["visitante"]))
            if i >= 200 and nuevos and estado.total_partidos >= 200:  # la liga ya tiene memoria propia: el «equipo nuevo» es un ascendido o un recién llegado
                pm = ent.probs_lineal(pesos, estado.features(p["local"], p["visitante"]))
                total = sum(frec.values())
                base = tuple((frec[c] + 1) / (total + 3) for c in CLASES)
                grupo = "un_equipo_nuevo" if nuevos == 1 else "dos_equipos_nuevos"
                mercado = cuotas_sin_margen(p)
                for g in (grupo, "todos"):
                    acum[g]["rps_modelo"].append(rps(pm, p["resultado"]))
                    acum[g]["rps_base"].append(rps(base, p["resultado"]))
                    acum[g]["ll_modelo"].append(logloss(pm, p["resultado"]))
                    acum[g]["ll_base"].append(logloss(base, p["resultado"]))
                    if mercado:
                        acum[g]["rps_modelo_c"].append(rps(pm, p["resultado"]))
                        acum[g]["rps_mercado_c"].append(rps(mercado, p["resultado"]))
            frec[p["resultado"]] += 1
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], ent.tiros_de(p))
    informe: dict = {"nota": "pesos del modelo vigente aplicados a todo el periodo (15 parámetros); estado reconstruido sin ver el futuro"}
    for g, m in acum.items():
        n = len(m["rps_modelo"])
        media = lambda k: round(sum(m[k]) / len(m[k]), 5) if m[k] else None  # noqa: E731
        # error estándar de la diferencia pareada de RPS (modelo - base): negativa = el modelo es mejor
        d = [a - b for a, b in zip(m["rps_modelo"], m["rps_base"])]
        mu = sum(d) / n
        ee = (sum((x - mu) ** 2 for x in d) / max(n - 1, 1)) ** 0.5 / math.sqrt(n)
        informe[g] = {"partidos": n, "rps_modelo": media("rps_modelo"), "rps_tasa_base": media("rps_base"), "logloss_modelo": media("ll_modelo"), "logloss_tasa_base": media("ll_base"),
                      "dif_rps_modelo_menos_base": round(mu, 5), "z": round(mu / ee, 2) if ee else None,
                      "con_cuotas": {"partidos": len(m["rps_modelo_c"]), "rps_modelo": media("rps_modelo_c"), "rps_mercado": media("rps_mercado_c")}}
    return informe


if __name__ == "__main__":
    r = evaluar()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(r, indent=2, ensure_ascii=False))
