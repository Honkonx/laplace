"""backend/scripts/reajustar_modelos.py — reajuste rápido de los Dixon-Coles con resultados en vivo.

Reentrena por liga (solo las que recibieron partidos en vivo nuevos; `--todas` para todas) con
maestro + capa en vivo (`backend/data/datos/vivo/`), usando los hiperparámetros ya elegidos en el
artefacto vigente (xi, ridge, rho) — sin repetir el tuning ni la evaluación completa — y VALIDA antes
de reemplazar: misma o mayor cobertura, ningún equipo desaparece, parámetros finitos y en rango, y una
comparación walk-forward corta de las últimas semanas (el modelo con capa en vivo no puede ser peor en
log-loss que el entrenado solo con el maestro). Sin datos suficientes o con un resultado peor NO
reemplaza y lo explica.

  --dry-run (por defecto)  calcula todo y deja el artefacto candidato en .qa/reajuste/, sin tocar nada.
  --aplicar                si la validación pasa, guarda copia del vigente en .qa/reajuste/respaldo/ y
                           lo reemplaza de forma atómica (`os.replace`).
  --exportar               antes, corre la exportación de resultados vivos desde la BD (solo lectura);
                           en dry-run escribe la capa en .qa/reajuste/vivo_ensayo/, no en backend/data/.
  --rapido                 para tests/humo: bloques de evaluación del doble de largo (la mitad de ajustes) y sin
                           predicciones de ejemplo.

Recarga en caliente: `services/modelo_historico._firma_archivos_modelo` incluye mtime y tamaño de
`dixon_coles_ligas.json`; al reemplazarlo, la siguiente consulta del backend en ejecución ve otra
firma y reconstruye su caché sin reiniciar el proceso (el `os.replace` es atómico: nunca lee un
archivo a medias).

Requiere numpy y scipy (solo para ajustar). Uso:
  python backend/scripts/reajustar_modelos.py [--exportar] [--aplicar] [--todas] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import datos, dixon_coles, reajuste  # noqa: E402

RUTA_ARTEFACTO = REPO / "backend" / "api" / "ml" / "artefactos" / "dixon_coles_ligas.json"
RUTA_BD = REPO / "backend" / "db" / "bot_deportivo.db"
DIR_QA = REPO / ".qa" / "reajuste"
LIGAS_HISPANOHABLANTES = ("CHL1", "COL1", "PER1", "URY1", "ECU1", "PRY1", "BOL1", "VEN1", "SAU1", "KOR1")


def ejemplos_prediccion(viejo: dict, nuevo: dict, vivos: list[dict], ligas: list[str], cuantos: int = 5) -> list[dict]:
    """Predicción de partidos en vivo reales con el artefacto anterior y el nuevo (hispanohablantes primero)."""
    candidatos = [p for p in vivos if p["liga"] in ligas]
    candidatos.sort(key=lambda p: (p["liga"] not in LIGAS_HISPANOHABLANTES, -p["dia"]))
    salida = []
    for p in candidatos[:cuantos]:
        fila = {"liga": p["liga"], "fecha": p["fecha"].isoformat(), "partido": f"{p['local']} - {p['visitante']}",
                "real": f"{p['gl']}-{p['gv']}"}
        for nombre, art in (("antes", viejo), ("despues", nuevo)):
            m = dixon_coles.ModeloLiga.de_dict(art["ligas"][p["liga"]])
            fila[nombre] = [round(x, 3) for x in dixon_coles.probabilidades(m, p["local"], p["visitante"])]
        salida.append(fila)
    return salida


def _preparar_capa(args: argparse.Namespace) -> tuple[Path, dict | None]:
    """Ruta de la capa en vivo a usar y, si se pidió, el resumen de la exportación previa."""
    ruta_vivo = args.vivo or (datos.RUTA_VIVO if args.aplicar else args.qa / "vivo_ensayo" / "resultados_vivos.csv.gz")
    if not args.exportar:
        return ruta_vivo, None
    from backend.scripts import exportar_resultados_vivos as exportador

    resumen = exportador.exportar(args.db, ruta_vivo, aplicar=True, base=datos.RUTA_VIVO if not args.aplicar else None,
                                  reporte=args.qa / "reporte_exportacion.json" if not args.aplicar else None)
    return ruta_vivo, {k: resumen[k] for k in ("crudos_leidos", "filas_totales", "filas_nuevas", "por_liga", "descartes_por_razon")}


def reajustar(args: argparse.Namespace, ajustador=dixon_coles.ajustar) -> dict:
    inicio = time.time()
    viejo = json.loads(args.artefacto.read_text(encoding="utf-8"))
    ruta_vivo, exportacion = _preparar_capa(args)
    partidos, info = datos.cargar_partidos_con_vivo(args.maestro, ruta_vivo)
    resumen: dict = {"aplicado": args.aplicar, "reemplazado": False, "artefacto": str(args.artefacto), "vivo": str(ruta_vivo),
                     "exportacion": exportacion, "vivos_leidos": info["vivos_leidos"], "vivos_duplicados_del_maestro": info["vivos_duplicados"],
                     "vivos_nuevos_por_liga": info["vivos_nuevos"]}
    objetivo = [c for c in (viejo["ligas"] if args.todas else info["vivos_nuevos"]) if c in viejo["ligas"]]
    if not objetivo:
        resumen["motivo"] = "sin partidos en vivo nuevos para ninguna liga con modelo: nada que reajustar"
        return resumen

    por_liga_con = datos.agrupar_por_liga(partidos)
    por_liga_maestro = datos.agrupar_por_liga([p for p in partidos if not p.get("vivo")])
    fecha_ref = max(p["dia"] for p in partidos) + 1
    nuevo = reajuste.reajustar_ligas(viejo, por_liga_con, fecha_ref, objetivo, ajustador=ajustador)
    nuevo["reajuste"] = {"fecha_ref": fecha_ref, "ligas_reajustadas": sorted(objetivo), "vivos_nuevos": sum(info["vivos_nuevos"].values())}
    resumen["ligas_reajustadas"] = sorted(objetivo)
    resumen["cambios"] = reajuste.comparar_parametros(viejo, nuevo, objetivo)

    problemas = reajuste.validar_estructura(viejo, nuevo)
    wf = reajuste.walk_forward_vivo(
        por_liga_maestro, por_liga_con, [p for p in info["vivos_todos"] if p["liga"] in objetivo], viejo["hiperparametros"],
        semanas=args.semanas, bloque_dias=2 * args.bloque_dias if args.rapido else args.bloque_dias, ajustador=ajustador)
    ok, motivo = reajuste.decidir(problemas, wf, args.min_evaluados, args.tolerancia)
    resumen.update({"problemas_estructura": problemas, "walk_forward": wf, "validacion_ok": ok, "motivo": motivo})
    if not args.rapido:
        resumen["ejemplos_prediccion"] = ejemplos_prediccion(viejo, nuevo, info["vivos_todos"], objetivo)

    args.qa.mkdir(parents=True, exist_ok=True)
    candidato = args.qa / "dixon_coles_ligas.nuevo.json"
    candidato.write_text(json.dumps(nuevo, ensure_ascii=False), encoding="utf-8")
    resumen["candidato"] = str(candidato)
    if args.aplicar and ok:
        resumen["respaldo"] = str(reajuste.reemplazar_atomico(nuevo, args.artefacto, args.qa / "respaldo"))
        resumen["reemplazado"] = True
    resumen["segundos"] = round(time.time() - inicio, 1)
    return resumen


def imprimir(r: dict) -> None:
    print(f"capa en vivo: {r['vivos_leidos']} partidos ({r['vivos_duplicados_del_maestro']} ya estaban en el maestro); "
          f"nuevos por liga: {r['vivos_nuevos_por_liga'] or '(ninguno)'}")
    if "ligas_reajustadas" not in r:
        print("RESULTADO:", r["motivo"])
        return
    for c, d in r["cambios"].items():
        print(f"  {c}: n {d['n_antes']}->{d['n_despues']} (vivos {d['vivos']}) d_mu={d['d_mu']:+} d_gamma={d['d_gamma']:+} "
              f"|d_ataque| medio={d['d_ataque_medio']} max={d['d_ataque_max']} |d_defensa| medio={d['d_defensa_medio']} max={d['d_defensa_max']}")
    wf = r["walk_forward"]
    print(f"walk-forward: n={wf['n']} log-loss maestro={wf['log_loss_maestro']} con vivo={wf['log_loss_con_vivo']} "
          f"RPS {wf['rps_maestro']} / {wf['rps_con_vivo']}")
    for e in r.get("ejemplos_prediccion", []):
        print(f"  {e['liga']} {e['fecha']} {e['partido']} (real {e['real']}): antes {e['antes']} -> despues {e['despues']}")
    print("validacion:", "OK" if r["validacion_ok"] else "NO", "-", r["motivo"])
    print("REEMPLAZADO" if r["reemplazado"] else f"no se reemplazó el artefacto ({'--aplicar no pedido' if not r['aplicado'] else 'validación'}); candidato: {r['candidato']}")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="reemplaza el artefacto si la validación pasa (por defecto dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="explícito; es el comportamiento por defecto")
    ap.add_argument("--exportar", action="store_true", help="exporta antes los resultados vivos desde la BD (solo lectura)")
    ap.add_argument("--todas", action="store_true", help="reajusta todas las ligas, no solo las con partidos en vivo nuevos")
    ap.add_argument("--rapido", action="store_true", help="bloques de evaluación del doble de largo y sin ejemplos (tests/humo)")
    ap.add_argument("--semanas", type=int, default=reajuste.SEMANAS_EVALUACION)
    ap.add_argument("--bloque-dias", type=int, default=reajuste.BLOQUE_DIAS)
    ap.add_argument("--min-evaluados", type=int, default=reajuste.MIN_EVALUADOS)
    ap.add_argument("--tolerancia", type=float, default=reajuste.TOLERANCIA_LOG_LOSS)
    ap.add_argument("--artefacto", type=Path, default=RUTA_ARTEFACTO)
    ap.add_argument("--maestro", type=Path, default=None)
    ap.add_argument("--vivo", type=Path, default=None)
    ap.add_argument("--db", type=Path, default=RUTA_BD)
    ap.add_argument("--qa", type=Path, default=DIR_QA)
    ap.add_argument("--json", action="store_true", help="imprime el resumen como una línea JSON final (lo usa el job)")
    return ap


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola Windows cp1252
    args = parser().parse_args(argv)
    if args.dry_run:
        args.aplicar = False
    resumen = reajustar(args)
    if args.json:
        print(json.dumps(resumen, ensure_ascii=False))
    else:
        imprimir(resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
