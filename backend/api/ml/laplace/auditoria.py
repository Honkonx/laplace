"""auditoria.py — lo que hace al modelo auditable y compartido, sin cambiar ningún pronóstico (plan `11_PLAN_MODELO_PREDICTIVO…`).

- `MP-5` cadena de sellos: cada fila de `ml_predicciones` lleva el SHA-256 de su contenido encadenado con el de la anterior; `verificar_cadena` detecta una fila alterada o una intermedia borrada.
- `MP-1` memoria de errores: `cerrar_bucle` guarda, por partido ya jugado, el pronóstico, el resultado y el error; `informe_errores` dice dónde falla, con n por segmento.
- `MP-2` `puerta_reentreno`: compara el candidato con el vigente (Δ log loss, RPS, ECE) con la regla común de promoción.
- `MP-4` `memoria_equipo`: lo que el modelo sabe de un equipo, para el bot, el agente y la web.
Solo lectura sobre los pronósticos; escribe únicamente `ml_errores` y los sellos de las filas nuevas.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.ml import metricas
from backend.api.models.ml_modelo import MlError, MlEstadoVivo, MlEvaluacion, MlModelo, MlPrediccion

GENESIS = "0" * 64
MEJORA_PUERTA = 0.001      # mejora mínima de log loss frente al vigente (puerta común del plan, `07_PLAN_Y_METAS_MODELO.md` §1)
EMPEORA_ECE_MAX = 0.005    # la calibración no puede empeorar más que esto
MIN_N_SEGMENTO = 30        # por debajo, un segmento se informa pero no se interpreta
N_UMBRAL_INCERTIDUMBRE = 20  # un equipo con menos partidos que esto tiene un rating poco fiable


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------- MP-5: cadena de sellos
def _canonica(p: MlPrediccion) -> str:
    return "|".join(str(x) for x in (p.id, p.modelo_id, p.partido_id or "", p.entrada_json, p.probabilidades_json, p.goles_json or "", p.confianza, p.canal, p.creada_en))


def _sello(previo: str, p: MlPrediccion) -> str:
    return hashlib.sha256(f"{previo}|{_canonica(p)}".encode()).hexdigest()


def sellar(db: Session, fila: MlPrediccion) -> None:
    """Sella una fila recién insertada (ya con `id`): encadena con la última fila sellada. Si la cadena aún no existe, parte de `GENESIS`."""
    ultimo = db.scalars(select(MlPrediccion).where(MlPrediccion.hash_fila.is_not(None), MlPrediccion.id != fila.id).order_by(MlPrediccion.id.desc()).limit(1)).first()
    fila.hash_previo = ultimo.hash_fila if ultimo else GENESIS
    fila.hash_fila = _sello(fila.hash_previo, fila)


def verificar_cadena(db: Session) -> dict:
    """Recorre las filas por `id`. Las anteriores al primer sello (sin sello) no cuentan; una fila sin sello DESPUÉS de la primera sellada, un `hash_previo` que no coincide o un contenido
    que ya no da su hash son una ruptura. Límite honesto: borrar la ÚLTIMA fila no se detecta (no hay una siguiente que la cite)."""
    previo, selladas, sin_sello, rota = None, 0, 0, None
    for p in db.scalars(select(MlPrediccion).order_by(MlPrediccion.id)).yield_per(500):
        if p.hash_fila is None:
            if previo is not None and rota is None:
                rota = {"id": p.id, "motivo": "fila sin sello dentro de la cadena"}
            sin_sello += previo is None
            continue
        esperado_previo = previo if previo is not None else GENESIS
        if rota is None and p.hash_previo != esperado_previo:
            rota = {"id": p.id, "motivo": "el sello anterior no coincide (falta una fila o se alteró otra)"}
        if rota is None and p.hash_fila != _sello(p.hash_previo, p):
            rota = {"id": p.id, "motivo": "el contenido de la fila ya no da su sello"}
        previo, selladas = p.hash_fila, selladas + 1
    return {"ok": rota is None, "filas_selladas": selladas, "filas_anteriores_a_la_cadena": sin_sello, "ruptura": rota}


# ---------------------------------------------------------------- MP-1: memoria de errores
def _resultado(gl: int, gv: int) -> str:
    return "H" if gl > gv else "A" if gv > gl else "D"


def _tramo(p_max: float) -> str:
    base = min(max(math.floor(p_max * 10) / 10, 0.3), 0.9)
    return f"{base:.1f}-{base + 0.1:.1f}"


def cerrar_bucle(db: Session, modelo_id: int) -> int:
    """Guarda en `ml_errores` los pronósticos del modelo cuyo partido ya tiene resultado (solo los hechos ANTES del partido y de los mismos equipos). Idempotente: devuelve cuántos agregó."""
    from backend.api.ml.laplace.registro import _es_legitima  # noqa: PLC0415 — evita el ciclo con registro
    from backend.api.models.partidos import ResultadoPartido  # noqa: PLC0415

    ya = set(db.scalars(select(MlError.partido_id).where(MlError.modelo_id == modelo_id)))
    nuevas = 0
    filas = db.execute(select(MlPrediccion, ResultadoPartido).join(ResultadoPartido, ResultadoPartido.fixture_id == MlPrediccion.partido_id)
                       .where(MlPrediccion.modelo_id == modelo_id, ResultadoPartido.goles_local.is_not(None), ResultadoPartido.goles_visitante.is_not(None))
                       .order_by(MlPrediccion.id)).all()
    for pred, res in filas:
        if pred.partido_id in ya or not _es_legitima(pred, res):
            continue
        ya.add(pred.partido_id)
        p = json.loads(pred.probabilidades_json)
        probs, r = (p["local"], p["empate"], p["visitante"]), _resultado(res.goles_local, res.goles_visitante)
        db.add(MlError(modelo_id=modelo_id, partido_id=pred.partido_id, liga=res.liga or "?", fecha=(res.fecha_partido or "")[:10], p_local=probs[0], p_empate=probs[1], p_visitante=probs[2],
                       resultado=r, rps=round(metricas.rps(probs, r), 6), log_loss=round(metricas.log_loss(probs, r), 6), tramo=_tramo(max(probs)),
                       acierto=int("HDA"[probs.index(max(probs))] == r), creado_en=_ahora()))
        nuevas += 1
    if nuevas:
        db.commit()
    return nuevas


def _agrupar(filas: list[MlError], clave) -> list[dict]:
    grupos: dict[str, list[MlError]] = defaultdict(list)
    for f in filas:
        grupos[clave(f)].append(f)
    salida = []
    for k, g in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        n = len(g)
        salida.append({"clave": k, "n": n, "rps": round(sum(f.rps for f in g) / n, 4), "log_loss": round(sum(f.log_loss for f in g) / n, 4),
                       "acierto": round(sum(f.acierto for f in g) / n, 3), "prob_media_del_favorito": round(sum(max(f.p_local, f.p_empate, f.p_visitante) for f in g) / n, 3),
                       "suficiente": n >= MIN_N_SEGMENTO})
    return salida


def informe_errores(db: Session, modelo_id: int | None = None, peores: int = 10) -> dict:
    """Dónde falla el modelo: por liga, por tramo de probabilidad del favorito (calibración: acierto frente a probabilidad media) y por mes. Un segmento con n < 30 sale con `suficiente: false`
    y no debe interpretarse. `peores` lista los partidos con mayor RPS."""
    consulta = select(MlError).order_by(MlError.id)
    if modelo_id is not None:
        consulta = consulta.where(MlError.modelo_id == modelo_id)
    filas = list(db.scalars(consulta))
    return {"n": len(filas), "min_n_segmento": MIN_N_SEGMENTO, "por_liga": _agrupar(filas, lambda f: f.liga), "por_tramo": sorted(_agrupar(filas, lambda f: f.tramo), key=lambda g: g["clave"]),
            "por_mes": sorted(_agrupar(filas, lambda f: f.fecha[:7] or "?"), key=lambda g: g["clave"]),
            "peores": [{"partido_id": f.partido_id, "liga": f.liga, "fecha": f.fecha, "rps": f.rps, "resultado": f.resultado, "p": [f.p_local, f.p_empate, f.p_visitante]}
                       for f in sorted(filas, key=lambda f: -f.rps)[:peores]]}


# ---------------------------------------------------------------- MP-2: puerta del reentreno
def evaluacion_historica_de(db: Session, modelo_id: int) -> dict | None:
    ev = db.scalars(select(MlEvaluacion).where(MlEvaluacion.modelo_id == modelo_id, MlEvaluacion.origen == "historica").order_by(MlEvaluacion.id.desc()).limit(1)).first()
    if ev is None or ev.log_loss is None:
        return None
    return {"n": ev.n, "log_loss": ev.log_loss, "rps": ev.rps, "ece": ev.ece}


def puerta_reentreno(candidato: dict, vigente: dict | None) -> dict:
    """Candidato frente al vigente con la regla común: mejora ≥ `MEJORA_PUERTA` de log loss y calibración (ECE) que no empeore más de `EMPEORA_ECE_MAX`.
    Límite honesto: NO es una comparación pareada (no hay IC95) y `comparable` es False si los dos se midieron sobre un n distinto (la prueba crece cada semana): entonces es solo indicativa."""
    if vigente is None:
        return {"hay_vigente": False, "pasa": None, "comparable": False, "veredicto": "no hay modelo vigente con evaluación histórica contra el que comparar"}
    d_ll = round(vigente["log_loss"] - candidato["log_loss"], 5)
    d_rps = round((vigente.get("rps") or 0) - (candidato.get("rps") or 0), 5)
    d_ece = round((vigente.get("ece") or 0) - (candidato.get("ece") or 0), 5)   # positivo = el candidato está mejor calibrado
    comparable = vigente.get("n") == candidato.get("n")
    pasa = d_ll >= MEJORA_PUERTA and d_ece >= -EMPEORA_ECE_MAX
    veredicto = ("pasa la puerta" if pasa else "no pasa la puerta") + ("" if comparable else " (indicativo: n distinto, no son los mismos partidos)") + " · sin IC95 (no pareada)"
    return {"hay_vigente": True, "pasa": pasa, "comparable": comparable, "pareada": False, "delta_log_loss": d_ll, "delta_rps": d_rps, "delta_ece": d_ece,
            "n_candidato": candidato.get("n"), "n_vigente": vigente.get("n"), "veredicto": veredicto}


# ---------------------------------------------------------------- MP-4: memoria compartida por equipo
def _buscar(mapa: dict, nombre: str) -> str | None:
    claro = nombre.strip().casefold()
    return next((k for k in mapa if k.casefold() == claro), None)


def memoria_equipo(db: Session, modelo: MlModelo, liga: str, equipo: str, artefacto: dict | None = None) -> dict | None:
    """Lo que el modelo sabe de un equipo de una liga (código del modelo, p. ej. `E0`): rating, goles a favor y en contra, forma, partidos y de dónde sale. None si la liga o el equipo no están.
    Usa la memoria de la base (`ml_estado_vivo`, al día) y, si no hay, el estado del artefacto."""
    from backend.api.ml.laplace.entrenamiento import EstadoLiga  # noqa: PLC0415

    fila = db.scalars(select(MlEstadoVivo).where(MlEstadoVivo.modelo_id == modelo.id, MlEstadoVivo.liga == liga)).first()
    if fila is not None:
        estado, fuente, actualizado = EstadoLiga.de_dict(json.loads(fila.estado_json)), "estado_vivo", fila.actualizado_en
    elif artefacto and liga in (artefacto.get("ligas") or {}):
        estado, fuente, actualizado = EstadoLiga.de_dict(artefacto["ligas"][liga]["estado"]), "artefacto", modelo.creado_en
    else:
        return None
    nombre = _buscar(estado.elo, equipo)
    if nombre is None:
        return None
    n = estado.n.get(nombre, 0)
    return {"liga": liga, "equipo": nombre, "rating_elo": round(estado.elo[nombre], 1), "goles_a_favor": round(estado.gf.get(nombre, 0.0), 3), "goles_en_contra": round(estado.gc.get(nombre, 0.0), 3),
            "forma_puntos_por_partido": round(estado.forma.get(nombre, 0.0), 3), "partidos": n, "fiabilidad": "baja" if n < N_UMBRAL_INCERTIDUMBRE else "normal",
            "media_liga": {"goles_local": round(estado.media_local, 3), "goles_visitante": round(estado.media_visita, 3)}, "fuente": fuente, "actualizado_en": actualizado,
            "modelo": {"id": modelo.id, "nombre": modelo.nombre, "version": modelo.version}}
