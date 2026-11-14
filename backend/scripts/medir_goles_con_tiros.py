"""Mide (GO-4) si los TIROS mejoran los goles esperados de cada equipo, fuera de muestra y sin ver el futuro.

Para cada partido de las ligas que traen tiros se guardan, con el estado de ANTES del partido, tres λ por equipo: la de goles (la del modelo), la que sale de los tiros y la que sale de los tiros
a puerta (`media × (a favor del atacante / media) × (en contra del defensor / media)`). En desarrollo (< 2023-07-01) se elige por rejilla la mezcla (en logaritmos) y el encogimiento hacia la
media de la liga que maximizan la log-verosimilitud de Poisson; en prueba (≥ 2023-07-01) se compara la mezcla elegida con la λ de solo goles (con SU mejor encogimiento): diferencia pareada
por partido-equipo, IC95 por bloques de semana y puerta común (≥ 0,001, z ≥ 3, IC95 sin cero). Las λ de solo goles y las de tiros salen del MISMO recorrido: la diferencia es solo la mezcla.
Uso: python backend/scripts/medir_goles_con_tiros.py   (escribe backend/data/resultados/medicion_goles_con_tiros.json)
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import comparacion, datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent, goles  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_goles_con_tiros.json"
CORTE = date(2023, 7, 1).toordinal()
PESOS = [round(x * 0.1, 1) for x in range(0, 8)]
EXPONENTES = (0.6, 0.7, 0.8, 0.9, 1.0)


def _filas() -> list[dict]:
    partidos, _ = datos.cargar_partidos_con_vivo()
    salida = []
    for codigo, lista in datos.agrupar_por_liga(partidos).items():
        if sum(1 for p in lista if ent.tiros_de(p)) < 500:
            continue
        h = ent.HIPERS["v1.1"]
        estado = ent.EstadoLiga(k_elo=h.get("k_elo", ent.K_ELO), alfa=h.get("alfa", ent.ALFA_GOLES), extras=tuple(h.get("extras", ())))
        for p in sorted(lista, key=lambda q: (q["dia"], q["local"])):
            t = ent.tiros_de(p)
            if t is not None and estado.n_tiros >= 50 and p["local"] in estado.t_for and p["visitante"] in estado.t_for and estado.media_t > 0 and estado.media_a > 0:
                lh, la = estado.lambdas(p["local"], p["visitante"])
                mt, ma = estado.media_t, estado.media_a
                f = lambda d, k: max(d.get(k, 0.0), 0.5)  # noqa: E731
                th = estado.media_local * (f(estado.t_for, p["local"]) / mt) * (f(estado.t_con, p["visitante"]) / mt)
                ta = estado.media_visita * (f(estado.t_for, p["visitante"]) / mt) * (f(estado.t_con, p["local"]) / mt)
                ah = estado.media_local * (f(estado.a_for, p["local"]) / ma) * (f(estado.a_con, p["visitante"]) / ma)
                aa = estado.media_visita * (f(estado.a_for, p["visitante"]) / ma) * (f(estado.a_con, p["local"]) / ma)
                salida.append({"dia": p["dia"], "g": (p["gl"], p["gv"]), "base": (lh, la), "t": (th, ta), "a": (ah, aa), "media": (estado.media_local, estado.media_visita)})
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], t)
    return salida


def _lam(f: dict, lado: int, wt: float, wa: float, s: float) -> float:
    media = f["media"][lado]
    mezcla = (1 - wt - wa) * math.log(f["base"][lado]) + wt * math.log(max(f["t"][lado], 1e-3)) + wa * math.log(max(f["a"][lado], 1e-3))
    return goles.encoger(math.exp(mezcla), media, s)


def _ll(fs: list[dict], wt: float, wa: float, s: float) -> list[float]:
    return [goles._ll_poisson(_lam(f, lado, wt, wa, s), f["g"][lado]) for f in fs for lado in (0, 1)]  # noqa: SLF001


def medir() -> dict:
    fs = _filas()
    dev = [f for f in fs if f["dia"] < CORTE]
    prueba = [f for f in fs if f["dia"] >= CORTE]
    muestra = dev[::3] or dev
    solo_goles = min(EXPONENTES, key=lambda s: sum(_ll(muestra, 0.0, 0.0, s)))
    mejor = min(itertools.product(PESOS, PESOS, EXPONENTES), key=lambda c: sum(_ll(muestra, c[0], c[1], c[2])) if c[0] + c[1] <= 0.8 else 1e18)
    base = _ll(prueba, 0.0, 0.0, solo_goles)
    prop = _ll(prueba, *mejor)
    bloques = [f["dia"] // 7 for f in prueba for _ in (0, 1)]
    r = comparacion.comparar_perdidas(base, prop, bloques=bloques, n_boot=200)
    return {"corte": "2023-07-01", "partidos_dev": len(dev), "partidos_prueba": len(prueba), "solo_goles": {"exponente": solo_goles},
            "mezcla_elegida": {"peso_tiros": mejor[0], "peso_tiros_a_puerta": mejor[1], "exponente": mejor[2]},
            "poisson_mejora_por_equipo_partido": {"valor": round(r["diferencia_media"], 5), "ic95": [round(r["ic95"][0], 5), round(r["ic95"][1], 5)], "z": round(r["z"], 1)},
            "puerta_comun": bool(r["diferencia_media"] >= 0.001 and r["z"] >= 3 and r["ic95"][0] > 0)}


def main() -> int:
    informe = medir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
