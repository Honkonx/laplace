"""Mide, fuera de muestra y sin ver el futuro, si el modelo Laplace sabe decir CUÁNTOS GOLES anotará cada equipo (no solo quién gana).

Protocolo del reentreno: se entrena con todo lo anterior a 2023-07-01 (con calibración de goles) y se recorre la prueba partido a partido. Para el equipo local y el visitante por separado se compara el pronóstico con
la media de goles que ya llevaba la liga (la referencia que cualquiera tendría): error absoluto medio de los goles esperados, log-verosimilitud de Poisson (pareada, con IC95 y la puerta común), calibración por
tramos de goles esperados (lo que se dijo frente a lo que pasó) y probabilidad de que el equipo marque al menos un gol. También mide cuántas veces el marcador más probable es el real (no se espera mucho: es raro).
Uso: python backend/scripts/medir_goles_por_equipo.py   (escribe backend/data/resultados/medicion_goles_por_equipo.json)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import comparacion, datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent, goles  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_goles_por_equipo.json"
CORTE = date(2023, 7, 1).toordinal()
N_BOOT = 200
MAX_GOLES = 8


def _ll_poisson(lam: float, k: int) -> float:
    lam = max(lam, 1e-6)
    return -(k * math.log(lam) - lam - math.lgamma(k + 1))


def _pmf(lam: float, k: int) -> float:
    return math.exp(-_ll_poisson(lam, k))


def filas() -> list[dict]:
    partidos, _ = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    art = ent.entrenar_jerarquico(por_liga, CORTE, especializar=False, hiper=ent.HIPERS["g3"], con_goles=True)
    s = (art.get("goles") or {}).get("s")
    salida = []
    for codigo, info in art["ligas"].items():
        estado = ent.EstadoLiga.de_dict(info["estado"])
        for p in sorted((p for p in por_liga[codigo] if p["dia"] >= CORTE), key=lambda q: (q["dia"], q["local"])):
            lh, la = estado.lambdas(p["local"], p["visitante"])
            if s is not None:
                lh, la = goles.encoger(lh, estado.media_local, s), goles.encoger(la, estado.media_visita, s)
            salida.append({"liga": codigo, "dia": p["dia"], "gl": p["gl"], "gv": p["gv"], "lh": lh, "la": la, "bh": estado.media_local, "ba": estado.media_visita})
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], ent.tiros_de(p))
    return salida


def _lado(fs: list[dict], lam: str, base: str, real: str) -> dict:
    n = len(fs)
    mae_m = sum(abs(f[lam] - f[real]) for f in fs) / n
    mae_b = sum(abs(f[base] - f[real]) for f in fs) / n
    ll_m = [_ll_poisson(f[lam], f[real]) for f in fs]
    ll_b = [_ll_poisson(f[base], f[real]) for f in fs]
    r = comparacion.comparar_perdidas(ll_b, ll_m, bloques=[f["dia"] // 7 for f in fs], n_boot=N_BOOT)
    marca = [(1 - _pmf(f[lam], 0), 1 if f[real] > 0 else 0, 1 - _pmf(f[base], 0)) for f in fs]
    ll_marca = sum(-math.log(max(p if y else 1 - p, 1e-9)) for p, y, _ in marca) / n
    ll_marca_b = sum(-math.log(max(b if y else 1 - b, 1e-9)) for _, y, b in marca) / n
    tramos: dict[int, list[dict]] = {}
    for f in fs:
        tramos.setdefault(min(int(f[lam] * 2), 7), []).append(f)
    return {"n": n, "error_abs_modelo": round(mae_m, 4), "error_abs_media_de_la_liga": round(mae_b, 4), "mejora_error_abs": round(mae_b - mae_m, 4),
            "poisson_log_verosimilitud": {"mejora_por_partido": round(r["diferencia_media"], 5), "ic95": [round(r["ic95"][0], 5), round(r["ic95"][1], 5)], "z": round(r["z"], 1)},
            "marca_al_menos_un_gol": {"log_loss_modelo": round(ll_marca, 5), "log_loss_media_de_la_liga": round(ll_marca_b, 5)},
            "calibracion_de_goles_esperados": [{"tramo": f"{k / 2:.1f}-{(k + 1) / 2:.1f}", "n": len(v), "goles_esperados_medios": round(sum(x[lam] for x in v) / len(v), 3), "goles_reales_medios": round(sum(x[real] for x in v) / len(v), 3)}
                                                for k, v in sorted(tramos.items()) if len(v) >= 100]}


def marcador_mas_probable(fs: list[dict]) -> dict:
    aciertos = 0
    for f in fs:
        mejor = max(((i, j) for i in range(MAX_GOLES + 1) for j in range(MAX_GOLES + 1)), key=lambda ij: _pmf(f["lh"], ij[0]) * _pmf(f["la"], ij[1]))
        aciertos += mejor == (f["gl"], f["gv"])
    base = sum(1 for f in fs if (f["gl"], f["gv"]) == (1, 1)) / len(fs)
    mas_comun = sum(1 for f in fs if (f["gl"], f["gv"]) == (1, 0)) / len(fs)
    return {"n": len(fs), "acierto_del_marcador_mas_probable": round(aciertos / len(fs), 4), "frecuencia_del_1_1": round(base, 4), "frecuencia_del_1_0": round(mas_comun, 4)}


def medir() -> dict:
    fs = filas()
    return {"corte": "2023-07-01", "partidos": len(fs), "local": _lado(fs, "lh", "bh", "gl"), "visitante": _lado(fs, "la", "ba", "gv"),
            "total_de_goles": {"error_abs_modelo": round(sum(abs(f["lh"] + f["la"] - f["gl"] - f["gv"]) for f in fs) / len(fs), 4),
                               "error_abs_media_de_la_liga": round(sum(abs(f["bh"] + f["ba"] - f["gl"] - f["gv"]) for f in fs) / len(fs), 4)},
            "marcador": marcador_mas_probable(fs[:12000])}


def main() -> int:
    informe = medir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    for lado in ("local", "visitante"):
        i = informe[lado]
        print(lado, "· error abs modelo", i["error_abs_modelo"], "vs liga", i["error_abs_media_de_la_liga"], "· Poisson", i["poisson_log_verosimilitud"], "· marca ≥1", i["marca_al_menos_un_gol"])
    print("total", informe["total_de_goles"], "· marcador", informe["marcador"])
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
