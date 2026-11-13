"""registro.py — persistencia del modelo propio en las tablas `ml_*`: conjuntos, simulaciones, muestras, entrenamientos, modelos, predicciones y evaluaciones.

Los pesos NO van a la base: se guardan como JSON en `ml/artefactos/laplace/` (fuera del repo público) con su SHA-256; la fila de `ml_modelos` solo apunta.
Promover un modelo a `activo` exige evidencia en sombra y un nombre de quien lo aprueba: nunca es automático.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.ml.laplace import VERSION_GENERADOR, auditoria
from backend.api.models.ml_modelo import MlConjuntoDatos, MlEntrenamiento, MlEvaluacion, MlModelo, MlMuestra, MlPrediccion, MlSimulacion

RUTA_ARTEFACTOS = Path(__file__).resolve().parents[1] / "artefactos" / "laplace"
MIN_CASOS_SOMBRA = 50
MIN_CASOS_PROMOCION = 200
MIN_CASOS_HISTORICOS = 2000   # alternativa a la sombra en vivo: evaluación fuera de muestra con partidos reales
MEJORA_MIN_HISTORICA = 0.02   # ventaja mínima de log loss sobre la tasa base en esa evaluación
PUNTERO = "vigente.json"
_cache_puntero: dict = {}


class ErrorPromocion(ValueError):
    pass


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _fecha(valor) -> str:
    return valor.isoformat() if hasattr(valor, "isoformat") else str(valor)


def guardar_conjunto(db: Session, nombre: str, version: str, partidos: list[dict], procedencia: str, simulacion: dict | None = None) -> int:
    """Guarda un conjunto de partidos con su procedencia. `simulacion` (de `simulacion.simular`) añade la fila reproducible."""
    from backend.api.ml.laplace.simulacion import huella

    if procedencia not in ("real", "sintetico", "mixto"):
        raise ValueError(f"procedencia inválida: {procedencia}")
    fechas = sorted(_fecha(p["fecha"]) for p in partidos)
    conjunto = MlConjuntoDatos(nombre=nombre, version=version, hash_datos=huella(partidos), procedencia=procedencia, desde=fechas[0] if fechas else None,
                               hasta=fechas[-1] if fechas else None, filas=len(partidos), creado_en=_ahora())
    db.add(conjunto)
    db.flush()
    sim_id = None
    if simulacion:
        sim = MlSimulacion(conjunto_id=conjunto.id, grupo=nombre, semilla=simulacion["semilla"], parametros_json=json.dumps(simulacion["parametros"], sort_keys=True),
                           tipo="automatico", version_generador=simulacion.get("version_generador", VERSION_GENERADOR), generada_en=_ahora())
        db.add(sim)
        db.flush()
        sim_id = sim.id
    ahora = _ahora()
    db.add_all([MlMuestra(
        conjunto_id=conjunto.id, simulacion_id=sim_id, partido_id=None, procedencia=p.get("procedencia", procedencia), peso=1.0, fecha_evento=_fecha(p["fecha"]),
        caracteristicas_json=json.dumps({"liga": p["liga"], "local": p["local"], "visitante": p["visitante"]}),
        etiqueta_json=json.dumps({"gl": p["gl"], "gv": p["gv"], "resultado": p["resultado"]}),
        hash_muestra=hashlib.sha256(f"{p['fecha']}|{p['local']}|{p['visitante']}|{p['gl']}|{p['gv']}".encode()).hexdigest(), creada_en=ahora) for p in partidos])
    db.commit()
    return conjunto.id


def registrar_entrenamiento(db: Session, conjunto_id: int, familia: str, semilla: int, parametros: dict, estado: str, error: str | None = None) -> int:
    fila = MlEntrenamiento(conjunto_id=conjunto_id, familia=familia, semilla=semilla, parametros_json=json.dumps(parametros, sort_keys=True), estado=estado, error=error,
                           inicio=_ahora(), fin=_ahora())
    db.add(fila)
    db.commit()
    return fila.id


def registrar_modelo(db: Session, nombre: str, version: str, artefacto: dict, entrenamiento_id: int | None, metricas: dict | None, tarea: str = "1x2+goles", tarjeta: str | None = None) -> int:
    """Escribe el artefacto (JSON) con su hash y crea el modelo en estado `sombra`."""
    RUTA_ARTEFACTOS.mkdir(parents=True, exist_ok=True)
    ruta = RUTA_ARTEFACTOS / f"{nombre}-{version}.json"
    contenido = json.dumps(artefacto, sort_keys=True, ensure_ascii=False)
    ruta.write_text(contenido, encoding="utf-8")
    if tarjeta:  # model card generada, junto al artefacto (no se publica: la carpeta de artefactos queda fuera del repo público)
        ruta.with_suffix(".MODEL_CARD.md").write_text(tarjeta, encoding="utf-8")
    modelo = MlModelo(nombre=nombre, version=version, familia=artefacto.get("familia", "?"), tarea=tarea, artefacto_ruta=str(ruta),
                      artefacto_sha256=hashlib.sha256(contenido.encode()).hexdigest(), estado="sombra", metricas_json=json.dumps(metricas) if metricas else None,
                      entrenamiento_id=entrenamiento_id, creado_en=_ahora())
    db.add(modelo)
    db.commit()
    return modelo.id


def cargar_artefacto(modelo: MlModelo) -> dict | None:
    """Lee el artefacto y verifica su SHA-256; si falta o no coincide devuelve None (el servicio degrada, no explota)."""
    if not modelo.artefacto_ruta or not Path(modelo.artefacto_ruta).is_file():
        return None
    contenido = Path(modelo.artefacto_ruta).read_text(encoding="utf-8")
    if hashlib.sha256(contenido.encode()).hexdigest() != modelo.artefacto_sha256:
        return None
    return json.loads(contenido)


def modelo_vigente(db: Session) -> MlModelo | None:
    """El modelo `activo` más reciente; si no hay, ninguno (la sombra no se sirve como si fuera oficial)."""
    return db.scalars(select(MlModelo).where(MlModelo.estado == "activo").order_by(MlModelo.id.desc())).first()


def modelo_sombra(db: Session) -> MlModelo | None:
    return db.scalars(select(MlModelo).where(MlModelo.estado == "sombra").order_by(MlModelo.id.desc())).first()


def registrar_prediccion(db: Session, modelo_id: int, entrada: dict, salida: dict, canal: str, latencia_ms: float, partido_id: str | None = None, confirmar: bool = True) -> int:
    fila = MlPrediccion(modelo_id=modelo_id, partido_id=partido_id, entrada_json=json.dumps(entrada, sort_keys=True), probabilidades_json=json.dumps(salida["p1x2"]),
                        goles_json=json.dumps(salida.get("goles_esperados")), confianza=salida.get("confianza"), latencia_ms=round(latencia_ms, 2), canal=canal, creada_en=_ahora())
    db.add(fila)
    db.flush()  # da el `id` que entra en el sello
    auditoria.sellar(db, fila)
    if confirmar:  # si no, va dentro de la transacción de otro (el laboratorio) y la confirma quien la abrió
        db.commit()
    return fila.id


def registrar_evaluacion(db: Session, modelo_id: int, informe: dict, origen: str, desde: str | None = None, hasta: str | None = None) -> int:
    p = informe["propio"]
    fila = MlEvaluacion(modelo_id=modelo_id, ventana_desde=desde, ventana_hasta=hasta, n=p["n"], log_loss=p["log_loss"], brier=p["brier"], rps=p["rps"], ece=p["ece"],
                        referencias_json=json.dumps(informe.get("referencias", {})), origen=origen, creada_en=_ahora())
    db.add(fila)
    db.commit()
    return fila.id


def promover(db: Session, modelo_id: int, aprobado_por: str) -> None:
    """Sombra → activo. Exige ≥ `MIN_CASOS_PROMOCION` casos en vivo evaluados en sombra, que no pierda contra la tasa base y un aprobador con nombre."""
    if not aprobado_por.strip():
        raise ErrorPromocion("la promoción exige el nombre de quien la aprueba")
    modelo = db.get(MlModelo, modelo_id)
    if modelo is None or modelo.estado != "sombra":
        raise ErrorPromocion("solo se promueve un modelo en sombra")
    historica = db.scalars(select(MlEvaluacion).where(MlEvaluacion.modelo_id == modelo_id, MlEvaluacion.origen == "historica").order_by(MlEvaluacion.id.desc())).first()
    casos = db.scalar(select(func.coalesce(func.sum(MlEvaluacion.n), 0)).where(MlEvaluacion.modelo_id == modelo_id, MlEvaluacion.origen.in_(("sombra", "vivo")))) or 0
    if casos >= MIN_CASOS_PROMOCION:
        ultima = db.scalars(select(MlEvaluacion).where(MlEvaluacion.modelo_id == modelo_id, MlEvaluacion.origen.in_(("sombra", "vivo"))).order_by(MlEvaluacion.id.desc())).first()
        base = (json.loads(ultima.referencias_json or "{}")).get("tasa_base") if ultima else None
        if base and ultima.log_loss is not None and ultima.log_loss >= base["log_loss"]:
            raise ErrorPromocion("el modelo no mejora a la tasa base en sombra")
    elif historica is not None and historica.n >= MIN_CASOS_HISTORICOS:
        base = (json.loads(historica.referencias_json or "{}")).get("tasa_base")
        if not base or historica.log_loss is None or base["log_loss"] - historica.log_loss < MEJORA_MIN_HISTORICA:
            raise ErrorPromocion("la evaluación histórica real no supera a la tasa base por el margen exigido")
    else:
        raise ErrorPromocion(f"faltan casos: {casos} en sombra de {MIN_CASOS_PROMOCION}, o una evaluación histórica real de {MIN_CASOS_HISTORICOS}")
    for previo in db.scalars(select(MlModelo).where(MlModelo.estado == "activo", MlModelo.nombre == modelo.nombre)):
        previo.estado = "retirado"
    modelo.estado, modelo.promovido_por = "activo", aprobado_por.strip()
    db.commit()
    escribir_puntero(modelo)


def escribir_puntero(modelo: MlModelo) -> None:
    """Deja en disco cuál es el modelo vigente, para que el motor del bot lo lea sin abrir la base."""
    RUTA_ARTEFACTOS.mkdir(parents=True, exist_ok=True)
    info = {"id": modelo.id, "nombre": modelo.nombre, "version": modelo.version, "estado": "activo", "ruta": modelo.artefacto_ruta, "sha256": modelo.artefacto_sha256}
    (RUTA_ARTEFACTOS / PUNTERO).write_text(json.dumps(info), encoding="utf-8")


def cargar_vigente_archivo() -> tuple[dict | None, dict | None]:
    """(info, artefacto) del modelo vigente según el puntero en disco; (None, None) si falta, no coincide la huella o el archivo está roto. Con caché por fecha de archivo."""
    puntero = RUTA_ARTEFACTOS / PUNTERO
    try:
        marca = (puntero.stat().st_mtime_ns, str(puntero))
        if _cache_puntero.get("marca") == marca:
            return _cache_puntero["valor"]
        info = json.loads(puntero.read_text(encoding="utf-8"))
        contenido = Path(info["ruta"]).read_text(encoding="utf-8")
        valor = (info, json.loads(contenido)) if hashlib.sha256(contenido.encode()).hexdigest() == info["sha256"] else (None, None)
    except (OSError, ValueError, KeyError):
        valor, marca = (None, None), None
    if marca:
        _cache_puntero.update(marca=marca, valor=valor)
    return valor


def _mismo_equipo(a: str | None, b: str | None) -> bool:
    a, b = (a or "").strip().casefold(), (b or "").strip().casefold()
    return bool(a) and bool(b) and (a in b or b in a)


def _es_legitima(pred: MlPrediccion, res) -> bool:
    """Una predicción cuenta para evaluar solo si se hizo ANTES del partido y su entrada habla de los mismos equipos que el resultado (defensa contra sesgar la evaluación)."""
    try:
        entrada = json.loads(pred.entrada_json)
    except ValueError:
        return False
    if not (_mismo_equipo(entrada.get("local"), res.local) and _mismo_equipo(entrada.get("visitante"), res.visitante)):
        return False
    fecha = (res.fecha_partido or "")[:10]
    return bool(fecha) and pred.creada_en[:10] <= fecha


def evaluar_sombra(db: Session, modelo_id: int, origen: str = "sombra") -> dict | None:
    """Cruza las predicciones de un modelo con los resultados reales ya guardados y guarda una evaluación acumulada (`origen`: `sombra` para el que aún no responde, `vivo` para el activo). None si aún no hay casos."""
    from backend.api.ml.laplace.entrenamiento import _resumen
    from backend.api.models.partidos import ResultadoPartido

    pares, vistos = [], set()
    filas = db.execute(select(MlPrediccion, ResultadoPartido).join(ResultadoPartido, ResultadoPartido.fixture_id == MlPrediccion.partido_id)
                       .where(MlPrediccion.modelo_id == modelo_id, ResultadoPartido.goles_local.is_not(None), ResultadoPartido.goles_visitante.is_not(None))
                       .order_by(MlPrediccion.id)).all()
    for pred, res in filas:
        if pred.partido_id in vistos or not _es_legitima(pred, res):
            continue
        vistos.add(pred.partido_id)
        p = json.loads(pred.probabilidades_json)
        r = "H" if res.goles_local > res.goles_visitante else "A" if res.goles_visitante > res.goles_local else "D"
        pares.append(((p["local"], p["empate"], p["visitante"]), r))
    if not pares:
        return None
    frec = [sum(1 for _, r in pares if r == c) / len(pares) for c in "HDA"]
    base = _resumen([(tuple(frec), r) for _, r in pares])  # cota optimista de la tasa base (frecuencia de la propia muestra)
    informe = {"propio": _resumen(pares), "referencias": {"tasa_base": base}}
    for previa in db.scalars(select(MlEvaluacion).where(MlEvaluacion.modelo_id == modelo_id, MlEvaluacion.origen == origen)):
        db.delete(previa)
    db.commit()
    registrar_evaluacion(db, modelo_id, informe, origen)
    return informe
