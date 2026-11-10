"""backend/scripts/medir_colector.py — cobertura de la capa en vivo, por liga con modelo (SOLO lectura).

Responde: ¿cuántos partidos terminados por semana llegan a `resultados_partidos`/`partidos_dia` para cada
liga con modelo?, ¿qué tan viejo es el último?, ¿y cuántos faltan para los ~100 partidos evaluables que
exige el reajuste semanal (`ml/reajuste.MIN_EVALUADOS`, contados sobre las últimas 8 semanas y entre todas
las ligas reajustadas)? También lista los equipos que no se resuelven contra el modelo de su liga (la
causa más frecuente de pérdida: hay que añadirlos a `ml/alias/equipos_alias_vivo.json`).

No escribe nada: abre la BD con `mode=ro`, no toca la capa en vivo ni los artefactos. Usa la misma
clasificación que la exportación (`exportar_resultados_vivos.construir_resolver`/`vivo.clasificar`), así
que lo que cuenta aquí es lo que el reajuste vería. No necesita numpy/scipy.

Uso:  python backend/scripts/medir_colector.py [--db ruta] [--json] [--semanas 4]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import datos, reajuste, vivo  # noqa: E402

RUTA_BD = REPO / "backend" / "db" / "bot_deportivo.db"
SEMANAS_VENTANA_REAJUSTE = reajuste.SEMANAS_EVALUACION
UMBRAL_EVALUABLES = reajuste.MIN_EVALUADOS


def _cargar_exportador():
    ruta = REPO / "backend" / "scripts" / "exportar_resultados_vivos.py"
    spec = importlib.util.spec_from_file_location("exportar_resultados_vivos", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _semana_inicio(f: date) -> str:
    return (f - timedelta(days=f.weekday())).isoformat()


def consumo_colector(ruta_bd: Path) -> list[dict]:
    """Peticiones del colector por día, de `stats_cache` (lectura)."""
    con = sqlite3.connect(f"file:{ruta_bd.as_posix()}?mode=ro", uri=True)
    try:
        filas = con.execute("SELECT cache_key, datos_json FROM stats_cache WHERE cache_key LIKE 'consumo:colector:%' ORDER BY cache_key DESC LIMIT 14").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    salida = []
    for clave, datos_json in filas:
        d = json.loads(datos_json)
        salida.append({"fecha": clave.rsplit(":", 1)[-1], "peticiones": d.get("peticiones"), "restante_api": d.get("restante_api")})
    return salida


def medir(ruta_bd: Path, hoy: date | None = None, semanas: int = 4) -> dict:
    hoy = hoy or date.today()
    exportador = _cargar_exportador()
    resolver, art, mh = exportador.construir_resolver()
    metas = exportador.metadatos_ligas(art, mh, datos.cargar_partidos())
    existentes = vivo.leer_csv_gz(datos.RUTA_VIVO)
    filas, descartes = vivo.clasificar(vivo.leer_crudos_bd(ruta_bd), resolver, metas, existentes, hoy)

    por_liga: dict[str, list[date]] = defaultdict(list)
    for f in filas:
        por_liga[f["liga_codigo"]].append(date.fromisoformat(f["fecha"]))
    semanas_claves = [_semana_inicio(hoy - timedelta(weeks=i)) for i in range(semanas - 1, -1, -1)]
    limite_ventana = hoy - timedelta(weeks=SEMANAS_VENTANA_REAJUSTE)

    ligas = {}
    for codigo, fechas in sorted(por_liga.items(), key=lambda kv: -len(kv[1])):
        por_semana = Counter(_semana_inicio(f) for f in fechas)
        ligas[codigo] = {
            "nombre": metas.get(codigo, {}).get("nombre", ""),
            "total_capa": len(fechas),
            "en_ventana_8_semanas": sum(1 for f in fechas if f >= limite_ventana),
            "por_semana": {s: por_semana.get(s, 0) for s in semanas_claves},
            "ultimo": max(fechas).isoformat(),
            "antiguedad_dias": (hoy - max(fechas)).days,
        }
    evaluables = sum(v["en_ventana_8_semanas"] for v in ligas.values())
    faltan_equipos = Counter(d["detalle"] for d in descartes if d["razon"] == "equipo_desconocido")
    return {
        "hoy": hoy.isoformat(), "bd": str(ruta_bd), "filas_capa": len(filas),
        "evaluables_ventana_8_semanas": evaluables, "umbral_reajuste": UMBRAL_EVALUABLES,
        "faltan_para_umbral": max(0, UMBRAL_EVALUABLES - evaluables),
        "nota_evaluables": "aproximación por exceso: el reajuste solo cuenta partidos de ligas que ya tenían algún partido en vivo "
                           "anterior al bloque de 14 días y descarta los que no cambian entre modelos",
        "ligas": ligas,
        "descartes_por_razon": dict(Counter(d["razon"] for d in descartes if d["razon"] != "duplicado")),
        "equipos_sin_resolver_top": faltan_equipos.most_common(20),
        "consumo_colector": consumo_colector(ruta_bd),
    }


def imprimir(r: dict) -> None:
    print(f"hoy {r['hoy']} | filas en la capa: {r['filas_capa']} | evaluables (8 sem): {r['evaluables_ventana_8_semanas']} "
          f"/ {r['umbral_reajuste']} -> faltan {r['faltan_para_umbral']}")
    semanas = next(iter(r["ligas"].values()), {}).get("por_semana", {})
    print(f"{'liga':8} {'total':>6} {'8sem':>5} {'ult(d)':>7}  " + " ".join(f"{s[5:]:>6}" for s in semanas))
    for codigo, v in r["ligas"].items():
        print(f"{codigo:8} {v['total_capa']:6d} {v['en_ventana_8_semanas']:5d} {v['antiguedad_dias']:7d}  "
              + " ".join(f"{n:6d}" for n in v["por_semana"].values()))
    print("descartes por razón:", r["descartes_por_razon"])
    for detalle, n in r["equipos_sin_resolver_top"]:
        print(f"  equipo sin modelo: {detalle} (x{n})")
    if r["consumo_colector"]:
        print("consumo del colector:", ", ".join(f"{c['fecha']}={c['peticiones']} (restante {c['restante_api']})" for c in r["consumo_colector"]))
    else:
        print("consumo del colector: sin registros (todavía no ha corrido)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=RUTA_BD)
    ap.add_argument("--semanas", type=int, default=4, help="semanas recientes a mostrar por liga")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    resultado = medir(args.db, semanas=args.semanas)
    print(json.dumps(resultado, indent=2, ensure_ascii=False)) if args.json else imprimir(resultado)


if __name__ == "__main__":
    main()
