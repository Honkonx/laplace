"""maquina_del_tiempo.py — repite el pasado con reloj simulado para probar que el sistema se verifica solo (SM-1 a SM-4 de `docs/mejoras/modelo/12_PLAN_...`).

  ventana    partidos REALES de un rango pasado: entrena solo con lo anterior, pronostica, encola, verifica con una fuente que entrega el marcador a inicio + 140 min, e informa.
  sintetico  liga inventada con verdad conocida: cuánto se aleja el modelo de la probabilidad verdadera (oráculo).
  calibrar   temporadas completas: tabla umbral de confianza × acierto × cobertura por liga, frente a las etiquetas vigentes (no cambia nada del producto).

  python backend/scripts/maquina_del_tiempo.py ventana --ligas E0 SP1 D1 --desde 2025-09-01 --hasta 2025-09-30
  python backend/scripts/maquina_del_tiempo.py sintetico --semillas 1 2 3 4 5
  python backend/scripts/maquina_del_tiempo.py calibrar --ligas E0 SP1 D1 I1 F1 N1 --desde 2023-07-01 --hasta 2024-06-30

Todo ocurre en una base temporal con las migraciones reales (`.qa/maquina_del_tiempo/`): nunca toca `bot_deportivo.db`. El informe JSON sale en `.qa/` (no se versiona).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import repeticion as rep, simulacion  # noqa: E402

QA = RAIZ / ".qa" / "maquina_del_tiempo"


def _fecha(texto: str) -> date:
    return date.fromisoformat(texto)


def _base() -> object:
    QA.mkdir(parents=True, exist_ok=True)
    carpeta = Path(tempfile.mkdtemp(prefix="mt_", dir=QA))
    return rep.crear_base_temporal(carpeta / "repeticion.db")


def _sin_casos(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "casos"}


def _linea(inf: dict) -> str:
    if inf.get("aviso"):
        return inf["aviso"]
    a = inf["acierto_1x2"]
    return (f"n={inf['n']} acierto={a['valor']:.4f} IC95=[{a['ic95'][0]:.4f},{a['ic95'][1]:.4f}] | RPS={inf['rps']['modelo']:.5f} (base {inf['rps']['tasa_base']:.5f}) | "
            f"log loss={inf['log_loss']['modelo']:.5f} (base {inf['log_loss']['tasa_base']:.5f}; mejora {inf['log_loss']['mejora_sobre_tasa_base']:+.5f}, IC95 "
            f"[{inf['log_loss']['ic95_mejora'][0]:+.5f},{inf['log_loss']['ic95_mejora'][1]:+.5f}], z={inf['log_loss']['z']:.1f}) | Brier={inf['brier']['modelo']:.5f} (base {inf['brier']['tasa_base']:.5f})")


def _lineas_goles(inf: dict) -> list[str]:
    return [f"goles {lado}: error abs {inf[f'goles_{lado}']['error_abs_modelo']:.4f} frente a {inf[f'goles_{lado}']['error_abs_media_de_la_liga']:.4f} de la media de la liga | "
            f"Poisson +{inf[f'goles_{lado}']['poisson_ll_mejora_por_partido']:.5f}/partido IC95 [{inf[f'goles_{lado}']['ic95_poisson'][0]:+.5f},{inf[f'goles_{lado}']['ic95_poisson'][1]:+.5f}]"
            for lado in ("local", "visitante")]


def cmd_ventana(a: argparse.Namespace) -> dict:
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos_con_vivo()[0])
    t = time.time()
    res = rep.repetir(por_liga, a.ligas, a.desde, a.hasta, _base(), paso_min=a.paso_min)
    print(f"ventana {a.desde}..{a.hasta} ligas={a.ligas}: programados={res['programados']} registrados={res['registrados']} verificados={res['verificados']} "
          f"sin_modelo={res['sin_modelo']} consultas_a_la_fuente={res['consultas_a_la_fuente']} cola={res['cola']['por_estado']} ({time.time() - t:.0f} s)")
    print(_linea(res["informe"]))
    if "goles_local" in res["informe"]:
        print(*_lineas_goles(res["informe"]), sep="\n")
    print(f"cero fugas: {res['fugas']['cero_fugas']} (revisados={res['fugas']['revisados']}, entregas={res['fugas']['entregas']}, violaciones={len(res['fugas']['violaciones'])})")
    print(f"diferencia con el calculo independiente de las metricas: {res.get('diferencia_con_calculo_independiente')}")
    print(f"diferencia con el recorrido walk-forward directo (probabilidades y goles esperados): {res['diferencia_con_recorrido_directo']}")
    return _sin_casos(res)


def cmd_sintetico(a: argparse.Namespace) -> dict:
    salida = []
    for semilla in a.semillas:
        sim = simulacion.simular(semilla, n_equipos=a.equipos, temporadas=a.temporadas_entrenamiento + 1)
        ps = sim["partidos"]
        codigo = ps[0]["liga"]
        ultima = max(p["temporada"] for p in ps)
        prueba = [p for p in ps if p["temporada"] == ultima]
        desde, hasta = date.fromordinal(min(p["dia"] for p in prueba)), date.fromordinal(max(p["dia"] for p in prueba))
        res = rep.repetir({codigo: ps}, [codigo], desde, hasta, _base(), paso_min=a.paso_min, oraculo_de=lambda p: tuple(p["verdad"]))
        o = res["informe"]["frente_al_oraculo"]
        print(f"semilla {semilla}: entrenamiento={a.temporadas_entrenamiento} temporada(s) de {a.equipos} equipos, prueba n={res['verificados']} | log loss modelo {o['log_loss_modelo']:.5f} "
              f"oraculo {o['log_loss_oraculo']:.5f} exceso {o['exceso_de_log_loss']:+.5f} IC95 [{o['ic95_exceso'][0]:+.5f},{o['ic95_exceso'][1]:+.5f}] | cero fugas {res['fugas']['cero_fugas']} "
              f"| dif. independiente {res.get('diferencia_con_calculo_independiente')}")
        salida.append({"semilla": semilla, **_sin_casos(res)})
    excesos = [s["informe"]["frente_al_oraculo"]["exceso_de_log_loss"] for s in salida]
    resumen = {"excesos_de_log_loss": excesos, "media": sum(excesos) / len(excesos), "maximo": max(excesos), "minimo": min(excesos)}
    print("exceso de log loss sobre el oraculo:", {k: (round(v, 5) if isinstance(v, float) else [round(x, 5) for x in v]) for k, v in resumen.items()})
    return {"corridas": salida, "resumen": resumen}


def cmd_calibrar(a: argparse.Namespace) -> dict:
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos_con_vivo()[0])
    todas, por_liga_casos, resumenes = [], {}, {}
    art = rep.entrenar_sin_fuga(por_liga, a.desde, a.ligas)     # un solo entrenamiento para todas las ligas: el de antes de la ventana
    for liga in a.ligas:
        res = rep.repetir(por_liga, [liga], a.desde, a.hasta, _base(), paso_min=a.paso_min, artefacto=art)
        por_liga_casos[liga] = rep.tabla_umbrales(res["casos"])
        todas += res["casos"]
        resumenes[liga] = {"verificados": res["verificados"], "cero_fugas": res["fugas"]["cero_fugas"], "dif_independiente": res.get("diferencia_con_calculo_independiente"),
                           "dif_recorrido_directo": res["diferencia_con_recorrido_directo"], "informe": res["informe"]}
        print(f"{liga}: verificados={res['verificados']} | {_linea(res['informe'])}")
    total = rep.tabla_umbrales(todas)
    for nombre, tabla in [("TODAS", total), *por_liga_casos.items()]:
        b = tabla["bandas"]
        print(f"{nombre} n={tabla['n']} | " + " | ".join(f"{k}: n={v['n']} acierto={v['acierto']:.3f} IC95=[{v['ic95'][0]:.3f},{v['ic95'][1]:.3f}] prob={v['prob_media']:.3f} {v['veredicto']}" for k, v in b.items() if v["n"])
              + f" | bandas separadas: {tabla['las_bandas_se_separan_con_ic95']}")
    print("umbral | n | cobertura | acierto | IC95 (todas las ligas)")
    for t, r in total["umbrales"].items():
        if r["n"]:
            print(f"{t} | {r['n']} | {r['cobertura']:.3f} | {r['acierto']:.4f} | [{r['ic95'][0]:.4f},{r['ic95'][1]:.4f}]")
    return {"ventana": [a.desde.isoformat(), a.hasta.isoformat()], "total": total, "por_liga": por_liga_casos, "resumenes": resumenes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="modo", required=True)
    for nombre in ("ventana", "calibrar"):
        s = sub.add_parser(nombre)
        s.add_argument("--ligas", nargs="+", required=True)
        s.add_argument("--desde", type=_fecha, required=True)
        s.add_argument("--hasta", type=_fecha, required=True)
        s.add_argument("--paso-min", type=int, default=60)
    s = sub.add_parser("sintetico")
    s.add_argument("--semillas", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    s.add_argument("--equipos", type=int, default=16)
    s.add_argument("--temporadas-entrenamiento", type=int, default=1)
    s.add_argument("--paso-min", type=int, default=60)
    a = ap.parse_args()
    informe = {"ventana": cmd_ventana, "sintetico": cmd_sintetico, "calibrar": cmd_calibrar}[a.modo](a)
    destino = QA / f"informe_{a.modo}.json"
    destino.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"escrito en {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
