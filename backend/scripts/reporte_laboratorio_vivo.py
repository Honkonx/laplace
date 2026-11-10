"""backend/scripts/reporte_laboratorio_vivo.py — reporte honesto del laboratorio de pronósticos en vivo.

SOLO LECTURA (`sqlite3 mode=ro`; no escribe en la BD ni en ningún otro lado salvo `--salida`). Para cada
variante de `pronosticos_experimentales` calcula n, RPS, log-loss, Brier y accuracy contra el
resultado real, y lo compara — sobre los MISMOS partidos — con la tasa base de su liga y con el
mercado (cuotas guardadas en `datos_json`, sin margen de Shin) cuando existen.

Reglas de honestidad:
  - Por partido y variante cuenta SOLO la primera predicción emitida (no se premia reintentar).
  - Las predicciones del motor emitidas antes de `CORTE_MOTOR_CON_PUERTA_CALIDAD` se excluyen de las
    métricas (motor anterior a las correcciones: ver `.claude/rules/evidencia-historica-antes-de-promover.md`).
  - El resultado sale de la propia fila o, si falta, de `resultados_partidos` (mismo fixture).
  - La comparación entre variantes se hace sobre el conjunto de partidos que TODAS las comparadas
    tienen evaluados; si es pequeño o vacío, el reporte lo dice como "muestra insuficiente" en vez de
    inventar un ranking. Umbrales: 50 partidos evaluados (exploratoria) y 200 (promoción).

Uso:  python backend/scripts/reporte_laboratorio_vivo.py [--db ruta] [--json] [--salida archivo.json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import mercado, metricas  # noqa: E402

RUTA_BD = REPO / "backend" / "db" / "bot_deportivo.db"
VARIANTES = ("python_baseline", "dixon_coles_historico", "dc_mas_mercado_historico", "bsd_catboost",
             "api_football_prediction", "ia_simple", "python_plus_ia")
VARIANTES_DEL_MOTOR = ("python_baseline", "python_plus_ia")
UMBRAL_EXPLORATORIA = 50
UMBRAL_PROMOCION = 200
CORTE_MOTOR_DEFECTO = "2026-10-07"
TASA_BASE_GLOBAL = (0.44, 0.26, 0.30)  # solo si la liga no se resuelve: orden de magnitud del fútbol de clubes


def _corte_motor() -> str:
    try:
        from backend.api.models.predicciones import CORTE_MOTOR_CON_PUERTA_CALIDAD
        return CORTE_MOTOR_CON_PUERTA_CALIDAD
    except Exception:  # SQLAlchemy ausente en este Python: se usa el valor vigente documentado
        return CORTE_MOTOR_DEFECTO


def _resultado(gl: int, gv: int) -> str:
    return "H" if gl > gv else "A" if gv > gl else "D"


def _estado(n: int) -> str:
    if n >= UMBRAL_PROMOCION:
        return "muestra suficiente para evaluar promocion (requiere revision administrativa)"
    if n >= UMBRAL_EXPLORATORIA:
        return f"exploratoria (faltan {UMBRAL_PROMOCION - n} para promocion)"
    return f"muestra insuficiente ({n} de {UMBRAL_EXPLORATORIA} evaluados; faltan {UMBRAL_EXPLORATORIA - n} para exploratoria y {UMBRAL_PROMOCION - n} para promocion)"


def leer_filas(ruta_bd: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{Path(ruta_bd).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        filas = [dict(r) for r in con.execute(
            "SELECT p.id, p.partido_id, p.variante, p.liga, p.local, p.visitante, p.fecha_partido, p.corte_datos_en,"
            " p.creado_en, p.datos_json, p.prob_local, p.prob_empate, p.prob_visitante,"
            " p.goles_local_real, p.goles_visitante_real, r.goles_local AS res_gl, r.goles_visitante AS res_gv"
            " FROM pronosticos_experimentales p LEFT JOIN resultados_partidos r ON r.fixture_id = p.partido_id"
            " ORDER BY p.corte_datos_en, p.id")]
    finally:
        con.close()
    return filas


def _cuotas(datos_json: str | None) -> tuple[float, float, float] | None:
    try:
        d = json.loads(datos_json or "{}")
        h, e, a = (float(d[k]) for k in ("odds_local", "odds_empate", "odds_visit"))
    except (ValueError, KeyError, TypeError):
        return None
    return (h, e, a) if d.get("odds_disponibles") and mercado.cuotas_validas(h, e, a) else None


def _tasa_base(fila: dict, resolver) -> tuple[tuple[float, float, float], str]:
    t = resolver({"liga": fila["liga"] or "", "local": fila["local"], "visitante": fila["visitante"]}) if resolver else None
    if t:
        return (t["pct_local"] / 100, t["pct_empate"] / 100, t["pct_visitante"] / 100), "liga"
    return TASA_BASE_GLOBAL, "global"


def preparar(filas: list[dict], resolver_tasas=None) -> tuple[dict[str, dict[str, dict]], dict]:
    """{variante: {partido_id: obs}} con la primera predicción por partido, y conteos de exclusión."""
    corte = _corte_motor()
    obs: dict[str, dict[str, dict]] = {v: {} for v in VARIANTES}
    info = {"corte_motor": corte, "excluidas_por_corte_motor": {}, "sin_probabilidades": {}, "emitidos": {}}
    for f in filas:
        v = f["variante"]
        if v not in obs:
            continue
        info["emitidos"][v] = info["emitidos"].get(v, 0) + 1
        if v in VARIANTES_DEL_MOTOR and (f["corte_datos_en"] or f["creado_en"] or "") < corte:
            info["excluidas_por_corte_motor"][v] = info["excluidas_por_corte_motor"].get(v, 0) + 1
            continue
        if f["partido_id"] in obs[v]:
            continue  # solo la primera emitida
        probs = (f["prob_local"], f["prob_empate"], f["prob_visitante"])
        if any(p is None for p in probs):
            info["sin_probabilidades"][v] = info["sin_probabilidades"].get(v, 0) + 1
            continue
        gl = f["goles_local_real"] if f["goles_local_real"] is not None else f["res_gl"]
        gv = f["goles_visitante_real"] if f["goles_visitante_real"] is not None else f["res_gv"]
        tasa, origen_tasa = _tasa_base(f, resolver_tasas)
        mkt = _cuotas(f["datos_json"])
        obs[v][f["partido_id"]] = {
            "probs": tuple(float(p) for p in probs), "res": _resultado(int(gl), int(gv)) if gl is not None and gv is not None else None,
            "tasa_base": tasa, "origen_tasa": origen_tasa,
            "mercado": mercado.quitar_margen_shin(*mkt) if mkt else None,
        }
    return obs, info


def _metricas(pares: list) -> dict:
    return metricas.resumen(pares)


def comparar(partidos: dict[str, dict], variantes: list[str], obs: dict) -> dict:
    """Métricas de cada variante, de la tasa base y del mercado sobre los partidos dados."""
    out = {"n": len(partidos), "variantes": {}}
    for v in variantes:
        out["variantes"][v] = _metricas([(obs[v][p]["probs"], obs[v][p]["res"]) for p in partidos])
    ref = obs[variantes[0]]
    out["tasa_base"] = _metricas([(ref[p]["tasa_base"], ref[p]["res"]) for p in partidos])
    mkt = {p: next((obs[v][p]["mercado"] for v in variantes if obs[v][p]["mercado"]), None) for p in partidos}
    con_mkt = [p for p in partidos if mkt[p]]
    out["mercado"] = None
    if con_mkt:
        out["mercado"] = {
            "n": len(con_mkt), **_metricas([(mkt[p], ref[p]["res"]) for p in con_mkt]),
            "variantes_en_ese_subconjunto": {v: _metricas([(obs[v][p]["probs"], obs[v][p]["res"]) for p in con_mkt]) for v in variantes},
            "tasa_base_en_ese_subconjunto": _metricas([(ref[p]["tasa_base"], ref[p]["res"]) for p in con_mkt]),
        }
    return out


def construir_reporte(filas: list[dict], resolver_tasas=None) -> dict:
    obs, info = preparar(filas, resolver_tasas)
    variantes = {}
    for v in VARIANTES:
        evaluados = {p: o for p, o in obs[v].items() if o["res"] is not None}
        variantes[v] = {
            "emitidos_en_bd": info["emitidos"].get(v, 0), "excluidos_por_corte_motor": info["excluidas_por_corte_motor"].get(v, 0),
            "sin_probabilidades_1x2": info["sin_probabilidades"].get(v, 0), "con_probabilidades": len(obs[v]),
            "evaluados": len(evaluados), "estado": _estado(len(evaluados)),
            "muestra_insuficiente": len(evaluados) < UMBRAL_EXPLORATORIA,
            "faltan_exploratoria": max(0, UMBRAL_EXPLORATORIA - len(evaluados)),
            "faltan_promocion": max(0, UMBRAL_PROMOCION - len(evaluados)),
            "sobre_su_propio_conjunto": None,
        }
        if evaluados:
            variantes[v]["sobre_su_propio_conjunto"] = comparar(evaluados, [v], {v: evaluados})
    con_datos = [v for v in VARIANTES if variantes[v]["evaluados"]]
    comunes = set.intersection(*(({p for p, o in obs[v].items() if o["res"] is not None}) for v in con_datos)) if con_datos else set()
    conjunto = {"variantes_comparadas": con_datos, "n": len(comunes), "partidos": sorted(comunes)}
    if len(con_datos) >= 2 and comunes:
        conjunto["comparacion"] = comparar({p: obs[con_datos[0]][p] for p in comunes}, con_datos, obs)
    conjunto["advertencia"] = (
        "Muestra insuficiente: con menos de 50 partidos comunes ninguna diferencia es interpretable." if len(comunes) < UMBRAL_EXPLORATORIA
        else "Muestra exploratoria: no promover sin 200 partidos y revision administrativa." if len(comunes) < UMBRAL_PROMOCION else "")
    return {"generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "solo_lectura": True,
            "umbrales": {"exploratoria": UMBRAL_EXPLORATORIA, "promocion": UMBRAL_PROMOCION},
            "corte_motor": info["corte_motor"], "variantes": variantes, "conjunto_comun": conjunto,
            "nota": "Un LLM no produce probabilidades: las de ia_simple son su estimacion declarada, medida igual que las demas."}


def _fmt(m: dict | None) -> str:
    if not m or not m.get("n"):
        return "n=0"
    return f"n={m['n']} RPS={m['rps']} logloss={m['log_loss']} Brier={m['brier']} acc={m['accuracy']}"


def imprimir(r: dict) -> None:
    print(f"LABORATORIO EN VIVO (solo lectura) — corte del motor {r['corte_motor']}")
    for v, d in r["variantes"].items():
        print(f"\n[{v}] emitidos={d['emitidos_en_bd']} con prob. 1X2={d['con_probabilidades']} evaluados={d['evaluados']}"
              f"{' (excluidos por motor anterior: %d)' % d['excluidos_por_corte_motor'] if d['excluidos_por_corte_motor'] else ''}")
        print(f"  estado: {d['estado'].upper() if d['muestra_insuficiente'] else d['estado']}")
        c = d["sobre_su_propio_conjunto"]
        if c:
            print(f"  variante : {_fmt(c['variantes'][v])}")
            print(f"  tasa base: {_fmt(c['tasa_base'])}")
            if c["mercado"]:
                print(f"  mercado  : {_fmt(c['mercado'])} | la variante en ese subconjunto: {_fmt(c['mercado']['variantes_en_ese_subconjunto'][v])}")
            else:
                print("  mercado  : sin cuotas guardadas en los partidos evaluados")
    c = r["conjunto_comun"]
    print(f"\nCONJUNTO COMUN entre {', '.join(c['variantes_comparadas']) or '(ninguna variante con datos)'}: {c['n']} partidos")
    if c.get("comparacion"):
        k = c["comparacion"]
        for v, m in k["variantes"].items():
            print(f"  {v:26s} {_fmt(m)}")
        print(f"  {'tasa_base':26s} {_fmt(k['tasa_base'])}")
        print(f"  {'mercado':26s} {_fmt(k['mercado']) if k['mercado'] else 'sin cuotas'}")
    print("  " + c["advertencia"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=RUTA_BD)
    ap.add_argument("--json", action="store_true", help="imprime el reporte como JSON en vez de texto")
    ap.add_argument("--salida", type=Path, help="guarda además el JSON en este archivo")
    args = ap.parse_args()
    resolver = None
    try:
        from backend.api.services import modelo_historico
        resolver = modelo_historico.tasas_base_liga
    except Exception:  # sin artefactos o dependencias: se usa la tasa base global y se marca en cada fila
        pass
    reporte = construir_reporte(leer_filas(args.db), resolver)
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(reporte, indent=2, ensure_ascii=False))
    else:
        imprimir(reporte)


if __name__ == "__main__":
    main()
