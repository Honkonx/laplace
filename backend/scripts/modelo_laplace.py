"""modelo_laplace.py — línea de comandos del modelo propio: simular, importar, entrenar y evaluar (el modelo PRONOSTICA; no decide publicar).

  python backend/scripts/modelo_laplace.py simular --semilla 7 --equipos 16 --temporadas 4 --csv salida.csv
  python backend/scripts/modelo_laplace.py entrenar --semilla 7 --equipos 16 --temporadas 4 --nombre laplace-sim --guardar
  python backend/scripts/modelo_laplace.py entrenar --importar partidos.csv --procedencia real --nombre laplace-real --guardar
  python backend/scripts/modelo_laplace.py entrenar-real --guardar          (todas las ligas reales, jerárquico)
  python backend/scripts/modelo_laplace.py generar-clave [--rotar]           (crea ML_API_KEY en .env sin mostrarla; activa /api/v1/ml/predict/interno)
  python backend/scripts/modelo_laplace.py estado                            (modelos, evaluaciones y evidencia en vivo; solo lectura)
  python backend/scripts/modelo_laplace.py predecir --entrada partidos.csv --salida pronosticos.csv   (lote sin Telegram ni servidor; solo lectura)
  python backend/scripts/modelo_laplace.py evaluar-sombra
  python backend/scripts/modelo_laplace.py promover --modelo 3 --aprobado-por <nombre>

Sin `--guardar` solo imprime el informe walk-forward y NO escribe en la base. Con `--guardar` registra conjunto, entrenamiento, modelo (en `sombra`) y su evaluación
en las tablas `ml_*`. La base real se respalda a mano antes (`database-safety.md`); promover exige los casos en sombra que fija `registro.MIN_CASOS_PROMOCION`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import apilado, entrenamiento, registro, simulacion, tarjeta  # noqa: E402


def _partidos(args) -> tuple[list[dict], dict | None, str]:
    if getattr(args, "importar", None):
        return simulacion.importar(Path(args.importar), args.procedencia), None, args.procedencia
    sim = simulacion.simular(args.semilla, n_equipos=args.equipos, temporadas=args.temporadas)
    for p in sim["partidos"]:
        p["ap_prom"] = tuple(p["ap_prom"])
    return sim["partidos"], sim, "sintetico"


def _corte(partidos: list[dict], fraccion: float) -> int:
    ordenados = sorted(p["dia"] for p in partidos)
    return ordenados[int(len(ordenados) * fraccion)]


def cmd_simular(args) -> int:
    partidos, sim, _ = _partidos(args)
    if args.csv:
        simulacion.exportar_csv(partidos, Path(args.csv))
    if args.json and sim:
        simulacion.exportar_json(sim, Path(args.json))
    print(json.dumps({"partidos": len(partidos), "huella": simulacion.huella(partidos), "semilla": args.semilla}))
    return 0


def cmd_entrenar(args) -> int:
    partidos, sim, procedencia = _partidos(args)
    corte = _corte(partidos, args.fraccion_entrenamiento)
    res = entrenamiento.evaluar_comparando(partidos, corte)
    print(json.dumps(res["informe"], indent=1, ensure_ascii=False))
    if not args.guardar:
        print("(sin --guardar: no se escribió nada en la base)")
        return 0
    from backend.api.db.session import SessionLocal

    version = f"{date.today():%Y%m%d}-s{args.semilla}"
    with SessionLocal() as db:
        cid = registro.guardar_conjunto(db, args.nombre, version, partidos, procedencia, sim)
        eid = registro.registrar_entrenamiento(db, cid, res["artefacto"]["familia"], args.semilla, {"corte": corte, "fraccion": args.fraccion_entrenamiento}, "ok")
        mid = registro.registrar_modelo(db, args.nombre, version, res["artefacto"], eid, res["informe"]["propio"])
        registro.registrar_evaluacion(db, mid, res["informe"], "historica", desde=None, hasta=None)
    print(f"guardado: conjunto {cid}, entrenamiento {eid}, modelo {mid} (estado sombra)")
    return 0


def cmd_entrenar_real(args) -> int:
    """Modelo jerárquico con TODAS las ligas reales: mide con corte 2023-07-01 y entrena el definitivo con todo lo disponible (incluida la capa en vivo)."""
    partidos, info = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    corte_eval = date(2023, 7, 1).toordinal()
    medido = entrenamiento.evaluar_jerarquico(por_liga, corte_eval, con_dixon_coles=False)["informe"]
    resumen = medido["resumen"]
    print(json.dumps({"n_prueba": medido["n_prueba"], "ligas": medido["ligas"], "universal": resumen["universal"], "tasa_base": resumen["tasa_base"],
                      "mercado": resumen.get("mercado"), "vivos_nuevos": sum(info["vivos_nuevos"].values())}, indent=1))
    final = entrenamiento.entrenar_jerarquico(por_liga, max(p["dia"] for p in partidos) + 1)
    final["apilador_mercado"] = apilado.ajustar(por_liga, corte_eval)  # 1X2 + cuotas; solo `util` si le gana al mercado solo
    print(f"modelo definitivo: {len(final['ligas'])} ligas, {final['n_entrenamiento']} filas de entrenamiento")
    if not args.guardar:
        print("(sin --guardar: no se escribió nada en la base)")
        return 0
    from backend.api.db.session import SessionLocal

    version = f"{date.today():%Y%m%d}-real-{entrenamiento.GENERACION_MODELO}"
    informe = {"propio": resumen["universal"], "referencias": {"tasa_base": resumen["tasa_base"], **({"mercado": resumen["mercado"]} if "mercado" in resumen else {})}}
    with SessionLocal() as db:
        cid = registro.guardar_conjunto(db, args.nombre, version, partidos, "real")
        eid = registro.registrar_entrenamiento(db, cid, final["familia"], 0, {"corte_evaluacion": corte_eval, "ligas": len(final["ligas"])}, "ok")
        mid = registro.registrar_modelo(db, args.nombre, version, final, eid, resumen["universal"])
        registro.registrar_evaluacion(db, mid, informe, "historica", desde="2023-07-01")
    print(f"guardado: conjunto {cid}, modelo {mid} (estado sombra)")
    return 0


def _commit() -> str | None:
    """Commit del código con el que se entrena (para la reproducibilidad); None si no hay git."""
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10, cwd=str(RAIZ)).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def reentrenar(auto: bool, forzar: bool = False, variante: str = "g3") -> dict:
    """Reentrena con TODO lo disponible (maestro + capa en vivo), mide con el corte fijo 2023-07-01, lo registra y, si `auto`, lo promueve solo si pasa las guardas.

    Guardas (todas): ventaja >= 0,02 de log loss sobre la tasa base; no peor que el modelo activo por más de 0,002 en la misma evaluación; >= 40 ligas;
    filas de entrenamiento >= 90 % de las del activo. Si alguna falla, queda en sombra y el activo se conserva (no es un fallo del trabajo)."""
    import json as _json

    from backend.api.db.session import SessionLocal
    from backend.api.ml.laplace import auditoria
    from backend.api.models.ml_modelo import MlEvaluacion, MlModelo

    partidos, info = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    corte_eval = date(2023, 7, 1).toordinal()
    hiper = entrenamiento.HIPERS[variante]
    informe_eval = entrenamiento.evaluar_jerarquico(por_liga, corte_eval, con_dixon_coles=False, hiper=hiper)["informe"]
    resumen = informe_eval["resumen"]
    final = entrenamiento.entrenar_jerarquico(por_liga, max(p["dia"] for p in partidos) + 1, hiper=hiper)
    final["apilador_mercado"] = apilado.ajustar(por_liga, corte_eval, hiper=hiper)
    final["linaje"]["hash_codigo"] = _commit()  # 1X2 + cuotas; solo `util` si le gana al mercado solo
    sufijo = entrenamiento.GENERACION_MODELO if variante == "g3" else variante.replace(".", "")
    version = f"{date.today():%Y%m%d}-real-{sufijo}"
    informe = {"propio": resumen["universal"], "referencias": {"tasa_base": resumen["tasa_base"], **({"mercado": resumen["mercado"]} if "mercado" in resumen else {})}}
    salida = {"ok": True, "version": version, "ligas": len(final["ligas"]), "filas": final["n_entrenamiento"], "log_loss": resumen["universal"]["log_loss"],
              "tasa_base": resumen["tasa_base"]["log_loss"], "vivos_nuevos": sum(info["vivos_nuevos"].values()), "promovido": False,
              "mercados_goles_validados": (final.get("goles") or {}).get("util"),
              "apilador_mercado": (final.get("apilador_mercado") or {}).get("evaluacion")}
    with SessionLocal() as db:
        previo = registro.modelo_vigente(db)
        existentes = {m.version for m in db.query(MlModelo).filter(MlModelo.nombre == "laplace-real")}
        if version in existentes and not forzar:
            return {**salida, "detalle": "ya existe el modelo de hoy"}
        revision = 2
        while version in existentes:  # con --forzar el mismo día se registra una revisión nueva (nunca se pisa nada)
            version, revision = f"{date.today():%Y%m%d}-real-{sufijo}-r{revision}", revision + 1
        salida["version"] = version
        cid = registro.guardar_conjunto(db, "laplace-real", version, partidos, "real")
        eid = registro.registrar_entrenamiento(db, cid, final["familia"], 0, {"corte_evaluacion": corte_eval, "auto": auto}, "ok")
        mid = registro.registrar_modelo(db, "laplace-real", version, final, eid, resumen["universal"], tarjeta=tarjeta.markdown(tarjeta.ficha(final), informe_eval, version))
        puerta = auditoria.puerta_reentreno(resumen["universal"], auditoria.evaluacion_historica_de(db, previo.id) if previo is not None else None)  # MP-2
        informe["referencias"]["vs_vigente"] = puerta
        registro.registrar_evaluacion(db, mid, informe, "historica", desde="2023-07-01")
        salida["modelo_id"], salida["puerta"] = mid, puerta
        if not auto:
            return salida
        motivos = []
        if variante != "g3":
            motivos.append(f"la variante {variante} queda en sombra: se promueve con la regla 50/200 en vivo y con aprobador (en v1.1 además falta captura de tiros en vivo)")
        if resumen["tasa_base"]["log_loss"] - resumen["universal"]["log_loss"] < registro.MEJORA_MIN_HISTORICA:
            motivos.append("no supera a la tasa base por el margen exigido")
        if len(final["ligas"]) < 40:
            motivos.append(f"solo {len(final['ligas'])} ligas")
        if previo is not None:
            ev = db.query(MlEvaluacion).filter(MlEvaluacion.modelo_id == previo.id, MlEvaluacion.origen == "historica").order_by(MlEvaluacion.id.desc()).first()
            if ev is not None and resumen["universal"]["log_loss"] > ev.log_loss + 0.002:
                motivos.append("peor que el modelo activo")
            n_previo = (_json.loads(previo.metricas_json or "{}") or {}).get("n", 0)
            if n_previo and final["n_entrenamiento"] < 0.9 * (registro.cargar_artefacto(previo) or {}).get("n_entrenamiento", 0):
                motivos.append("menos datos de entrenamiento que el activo")
        if motivos:
            return {**salida, "detalle": "queda en sombra: " + "; ".join(motivos)}
        registro.promover(db, mid, "reentreno-automatico")
        return {**salida, "promovido": True, "detalle": "promovido por las guardas del reentreno"}


def cmd_reentrenar(args) -> int:
    resultado = reentrenar(args.auto, args.forzar, args.variante)
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado["ok"] else 1


def estado() -> dict:
    """Foto de solo lectura: modelos, evaluaciones y cuánta evidencia EN VIVO lleva el modelo en el laboratorio (50 exploratoria, 200 para promover)."""
    from sqlalchemy import func, select

    from backend.api.db.session import SessionLocal
    from backend.api.models.ml_modelo import MlEvaluacion, MlModelo, MlPrediccion
    from backend.api.models.predicciones import PronosticoExperimental as Obs
    from backend.api.services.laboratorio_pronosticos import comparar_en_vivo

    with SessionLocal() as db:
        modelos = [{"id": m.id, "version": m.version, "estado": m.estado, "promovido_por": m.promovido_por} for m in db.scalars(select(MlModelo).order_by(MlModelo.id))]
        evaluaciones = [{"modelo_id": e.modelo_id, "origen": e.origen, "n": e.n, "log_loss": e.log_loss, "creada_en": e.creada_en}
                        for e in db.scalars(select(MlEvaluacion).order_by(MlEvaluacion.id.desc()).limit(6))]
        lab = db.query(func.count(Obs.id), func.count(Obs.resultado_real), func.avg(Obs.log_loss)).filter(Obs.variante == "laplace_modelo").one()
        otros = {v: n for v, n in db.query(Obs.variante, func.count(Obs.resultado_real)).filter(Obs.resultado_real.is_not(None)).group_by(Obs.variante).all()}
        predicciones = db.scalar(select(func.count(MlPrediccion.id))) or 0
    con_resultado = int(lab[1])
    return {"modelos": modelos, "evaluaciones_recientes": evaluaciones, "predicciones_guardadas": predicciones,
            "laboratorio_laplace_modelo": {"observaciones": int(lab[0]), "con_resultado": con_resultado, "log_loss_medio": round(lab[2], 4) if lab[2] is not None else None,
                                           "falta_para_exploratoria": max(0, 50 - con_resultado), "falta_para_promocion": max(0, 200 - con_resultado)},
            "variantes_con_resultado": otros, "comparacion_en_vivo": comparar_en_vivo(db)}


def cmd_predecir(args) -> int:
    """Pronostica un lote de partidos SIN Telegram ni servidor (CSV o JSON de entrada → CSV o JSON de salida); solo lectura, no escribe en la base."""
    from backend.api.ml.laplace import lote

    ruta = args.entrada
    texto = sys.stdin.read() if ruta == "-" else Path(ruta).read_text(encoding="utf-8-sig")
    formato = args.formato or ("json" if ruta == "-" or ruta.lower().endswith(".json") else "csv")
    try:
        filas = lote.pronosticar_lote(lote.entradas_de_texto(texto, formato))
    except (ValueError, OSError) as exc:
        print(f"no se pudo leer la entrada: {exc}")
        return 2
    salida_json = (args.salida or "").lower().endswith(".json") if args.salida else formato == "json"
    cuerpo = lote.a_json(filas) if salida_json else lote.a_csv(filas)
    if args.salida:
        Path(args.salida).write_text(cuerpo, encoding="utf-8")
        print(f"{len(filas)} pronósticos escritos en {args.salida} ({sum(1 for f in filas if f['ok'])} con resultado)")
    else:
        print(cuerpo)
    return 0


def cmd_estado(args) -> int:
    print(json.dumps(estado(), ensure_ascii=False, indent=1))
    return 0


def cmd_generar_clave(args) -> int:
    """Genera ML_API_KEY en el `.env` local (el endpoint interno del modelo) sin mostrarla; actúa sobre tu configuración, por eso solo corre cuando tú lo pides."""
    from backend.api.ml.laplace import clave

    r = clave.generar(RAIZ, rotar=args.rotar)
    print(r["motivo"])
    return 0 if r["creada"] else 1


def cmd_evaluar_sombra(args) -> int:
    from backend.api.db.session import SessionLocal

    with SessionLocal() as db:
        sombra = registro.modelo_sombra(db)
        informe = registro.evaluar_sombra(db, sombra.id) if sombra else None
    print(json.dumps(informe["propio"]) if informe else "sin modelo en sombra o sin casos todavía")
    return 0


def cmd_promover(args) -> int:
    from backend.api.db.session import SessionLocal

    with SessionLocal() as db:
        try:
            registro.promover(db, args.modelo, args.aprobado_por)
        except registro.ErrorPromocion as e:
            print(f"no se promovió: {e}")
            return 1
    print("modelo promovido a activo")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre, fn in (("simular", cmd_simular), ("entrenar", cmd_entrenar)):
        s = sub.add_parser(nombre)
        s.add_argument("--semilla", type=int, default=7)
        s.add_argument("--equipos", type=int, default=16)
        s.add_argument("--temporadas", type=int, default=4)
        s.add_argument("--importar", help="CSV o JSON con partidos reales/sintéticos")
        s.add_argument("--procedencia", default="real", choices=simulacion.PROCEDENCIAS_VALIDAS)
        if nombre == "simular":
            s.add_argument("--csv")
            s.add_argument("--json")
        else:
            s.add_argument("--nombre", default="laplace")
            s.add_argument("--fraccion-entrenamiento", type=float, default=0.6)
            s.add_argument("--guardar", action="store_true")
        s.set_defaults(fn=fn)
    r = sub.add_parser("entrenar-real")
    r.add_argument("--nombre", default="laplace-real")
    r.add_argument("--guardar", action="store_true")
    r.set_defaults(fn=cmd_entrenar_real)
    rt = sub.add_parser("reentrenar")
    rt.add_argument("--auto", action="store_true", help="promueve solo si pasa las guardas")
    rt.add_argument("--forzar", action="store_true", help="registra una revisión nueva aunque ya haya un modelo de hoy")
    rt.add_argument("--variante", default="g3", choices=sorted(entrenamiento.HIPERS), help="versión del modelo: g3 (vigente) o v1.1 (tiros; solo queda en sombra)")
    rt.set_defaults(fn=cmd_reentrenar)
    gc = sub.add_parser("generar-clave", help="crea ML_API_KEY en .env (no se muestra)")
    gc.add_argument("--rotar", action="store_true")
    gc.set_defaults(fn=cmd_generar_clave)
    pr = sub.add_parser("predecir", help="pronostica un lote de partidos (CSV o JSON) sin Telegram ni servidor")
    pr.add_argument("--entrada", required=True, help="archivo CSV o JSON con los partidos, o - para leer JSON de la entrada estándar")
    pr.add_argument("--salida", help="archivo CSV o JSON de salida (por defecto se imprime)")
    pr.add_argument("--formato", choices=("csv", "json"), help="formato de la entrada (por defecto por la extensión)")
    pr.set_defaults(fn=cmd_predecir)
    sub.add_parser("estado").set_defaults(fn=cmd_estado)
    sub.add_parser("evaluar-sombra").set_defaults(fn=cmd_evaluar_sombra)
    p = sub.add_parser("promover")
    p.add_argument("--modelo", type=int, required=True)
    p.add_argument("--aprobado-por", required=True)
    p.set_defaults(fn=cmd_promover)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
