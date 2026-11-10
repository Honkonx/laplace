"""Laboratorio de pronósticos prepartido.

Esta capa conserva comparadores (motor propio, IA y fuentes externas) sin darles acceso al
consenso publicado. Toda observación se congela con un corte de datos previo al kickoff y se
evalúa cuando `services.resultados` recibe el marcador oficial.
"""
from __future__ import annotations

import logging
import hashlib
import json
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.api.ml import dixon_coles
from backend.api.models.partidos import ResultadoPartido
from backend.api.models.predicciones import ExperimentoPronostico, PronosticoExperimental
from backend.api.services import modelo_historico as modelo_historico_svc

log = logging.getLogger("laplace.laboratorio_pronosticos")

MUESTRA_MINIMA_EXPLORATORIA = 50
MUESTRA_MINIMA_PROMOCION = 200

EXPERIMENTOS_BASE = (
    ("python_baseline", "Motor estadístico Python", "propio", "poisson-dixon-coles-v1"),
    ("python_plus_ia", "Motor estadístico con contraste IA", "ia", "consenso-ia-v1"),
    ("ia_simple", "Hipótesis conversacional solo IA", "ia", "ai-scout-v1"),
    ("api_football_prediction", "Referencia API Football", "api", "api-football-v1"),
    ("bsd_catboost", "Referencia BSD CatBoost", "api", "bsd-catboost-v1"),
    ("human_reference", "Referencia humana supervisada", "web_referencia", "human-v1"),
    ("dixon_coles_historico", "Dixon-Coles entrenado con histórico (puro, sin cuotas)", "propio", "dc-decay-v1"),
    ("dc_mas_mercado_historico", "Dixon-Coles apilado con cuotas del mercado", "propio", "dc-mercado-v1"),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _json(value: object) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def asegurar_experimentos_base(db: Session) -> None:
    ahora = _now()
    for codigo, nombre, tipo, version in EXPERIMENTOS_BASE:
        if db.query(ExperimentoPronostico.id).filter(ExperimentoPronostico.codigo == codigo).first():
            continue
        db.add(ExperimentoPronostico(
            codigo=codigo, nombre=nombre, tipo=tipo, estado="sombra", version=version,
            permite_consenso=0,
            descripcion="Comparador interno; no participa en el consenso público.",
            creado_en=ahora, actualizado_en=ahora,
        ))
    db.flush()


def registrar_pronostico(db: Session, *, experimento_codigo: str, partido_id: str, fecha_partido: str,
                         local: str, visitante: str, fuente: str, variante: str,
                         corte_datos_en: str, hora_kickoff: str | None = None, liga: str | None = None,
                         modelo_version: str | None = None, prompt_version: str | None = None,
                         datos: dict | None = None, respuesta_cruda: str | None = None,
                         pick: str | None = None, prob_local: float | None = None,
                         prob_empate: float | None = None, prob_visitante: float | None = None,
                         marcador_probable: str | None = None, goles_local_esperados: float | None = None,
                         goles_visitante_esperados: float | None = None, rango_goles_total: str | None = None,
                         prob_empate_90: float | None = None) -> PronosticoExperimental:
    """Registra una observación de sombra sin permitir retrospectiva.

    Solo acepta probabilidades 1X2 completas y normalizadas. Si se conoce kickoff, el corte
    debe ser anterior; una fuente llegada tarde se rechaza en vez de contaminar el backtest.
    """
    if not partido_id or not experimento_codigo or not variante:
        raise ValueError("partido_id, experimento_codigo y variante son obligatorios")
    kickoff = _parse_datetime(hora_kickoff)
    corte = _parse_datetime(corte_datos_en)
    if kickoff and corte and corte >= kickoff:
        raise ValueError("el corte de datos debe ser anterior al inicio del partido")
    probabilidades = (prob_local, prob_empate, prob_visitante)
    if any(item is not None for item in probabilidades):
        if any(item is None or not 0 <= float(item) <= 1 for item in probabilidades):
            raise ValueError("las probabilidades 1X2 deben estar completas y entre 0 y 1")
        if abs(sum(float(item) for item in probabilidades) - 1.0) > 0.02:
            raise ValueError("las probabilidades 1X2 deben sumar aproximadamente 1")

    asegurar_experimentos_base(db)
    experimento = db.query(ExperimentoPronostico).filter(
        ExperimentoPronostico.codigo == experimento_codigo
    ).first()
    if experimento is None:
        raise ValueError("experimento no autorizado; debe registrarse y revisarse antes de recibir datos")
    if experimento.permite_consenso:
        raise ValueError("el laboratorio no admite variantes habilitadas para consenso")
    existente = db.query(PronosticoExperimental).filter(
        PronosticoExperimental.partido_id == partido_id,
        PronosticoExperimental.variante == variante,
        PronosticoExperimental.corte_datos_en == corte_datos_en,
    ).first()
    if existente:
        return existente
    snapshot = datos or {}
    fila = PronosticoExperimental(
        experimento_codigo=experimento_codigo, partido_id=partido_id, fecha_partido=fecha_partido,
        hora_kickoff=hora_kickoff, liga=liga, local=local, visitante=visitante, fuente=fuente,
        variante=variante, modelo_version=modelo_version, prompt_version=prompt_version,
        corte_datos_en=corte_datos_en, input_hash=_hash(snapshot), datos_json=_json(snapshot),
        respuesta_cruda=respuesta_cruda, pick=pick, prob_local=prob_local, prob_empate=prob_empate,
        prob_visitante=prob_visitante, marcador_probable=marcador_probable,
        goles_local_esperados=goles_local_esperados, goles_visitante_esperados=goles_visitante_esperados,
        rango_goles_total=rango_goles_total, prob_empate_90=prob_empate_90, creado_en=_now(),
    )
    db.add(fila)
    db.flush()
    return fila


def _pendiente(db: Session, partido_id: str, variante: str) -> bool:
    """True si ya hay una observación sin evaluar de esa variante para el partido (idempotencia)."""
    return db.query(PronosticoExperimental.id).filter(
        PronosticoExperimental.partido_id == partido_id,
        PronosticoExperimental.variante == variante,
        PronosticoExperimental.resultado_real.is_(None),
    ).first() is not None


def registrar_desde_motor(db: Session, *, partido_id: str, fecha_partido: str, local: str, visitante: str,
                          liga: str, hora_kickoff: str | None, datos: dict, poisson: dict,
                          combinado: dict | None) -> None:
    """Crea los comparadores propios a partir de una misma instantánea ya enriquecida."""
    def pendiente(variante: str) -> bool:
        return _pendiente(db, partido_id, variante)

    # No se registra una "variante" vacía cuando Poisson fue excluido por falta de datos de
    # equipos. Registrar ese placeholder produciría un denominador falso en el laboratorio.
    # Algunos adaptadores históricos no incluían `ok`, pero sí entregaban la tripleta completa.
    # La observación es utilizable sólo si hay pick y probabilidades 1X2 completas.
    poisson_valido = bool(poisson.get("pick") and all(
        poisson.get(clave) is not None for clave in ("prob_local", "prob_empate", "prob_visitante")
    ))
    corte = _now()
    base = dict(
        partido_id=partido_id, fecha_partido=fecha_partido, local=local, visitante=visitante,
        liga=liga, hora_kickoff=hora_kickoff, corte_datos_en=corte, datos=datos,
        pick=poisson.get("pick"), prob_local=poisson.get("prob_local"),
        prob_empate=poisson.get("prob_empate"), prob_visitante=poisson.get("prob_visitante"),
        marcador_probable=poisson.get("marcador_probable"),
        goles_local_esperados=poisson.get("lambda_local"), goles_visitante_esperados=poisson.get("lambda_visit"),
        rango_goles_total=poisson.get("rango_goles_total"), prob_empate_90=poisson.get("prob_empate"),
    )
    if poisson_valido and not pendiente("python_baseline"):
        registrar_pronostico(db, experimento_codigo="python_baseline", fuente="laplace", variante="python_baseline",
                             modelo_version=f"{poisson.get('motor', 'math')}+dixon-coles", **base)
    if combinado and poisson_valido and combinado.get("pick_unificado") and not pendiente("python_plus_ia"):
        registrar_pronostico(
            db, experimento_codigo="python_plus_ia", fuente="laplace", variante="python_plus_ia",
            modelo_version="consenso-estadistico-ia-v1", prompt_version="analisis-completo-v1",
            respuesta_cruda=combinado.get("texto_claude"), pick=combinado.get("pick_unificado"),
            prob_local=poisson.get("prob_local"), prob_empate=poisson.get("prob_empate"),
            prob_visitante=poisson.get("prob_visitante"), marcador_probable=poisson.get("marcador_probable"),
            goles_local_esperados=poisson.get("lambda_local"), goles_visitante_esperados=poisson.get("lambda_visit"),
            rango_goles_total=poisson.get("rango_goles_total"), prob_empate_90=poisson.get("prob_empate"),
            partido_id=partido_id, fecha_partido=fecha_partido, local=local, visitante=visitante,
            liga=liga, hora_kickoff=hora_kickoff, corte_datos_en=corte, datos=datos,
        )


def registrar_referencia_bsd(db: Session, *, partido_id: str, fecha_partido: str, local: str, visitante: str,
                             liga: str, hora_kickoff: str | None, datos: dict, bsd_ml: dict) -> None:
    """Duplica BSD como comparador auditable aunque el módulo histórico siga disponible.

    El registro es de sombra; no cambia pesos ni reconfigura consenso.py.
    """
    if not bsd_ml.get("ok") or _pendiente(db, partido_id, "bsd_catboost"):
        return
    registrar_pronostico(
        db, experimento_codigo="bsd_catboost", partido_id=partido_id, fecha_partido=fecha_partido,
        local=local, visitante=visitante, liga=liga, fuente="bsd", variante="bsd_catboost",
        modelo_version="bsd-catboost-proveedor", corte_datos_en=_now(), hora_kickoff=hora_kickoff,
        datos={"bsd_ml": bsd_ml, "contexto": datos}, pick=bsd_ml.get("pick"),
        prob_local=bsd_ml.get("prob_local"), prob_empate=bsd_ml.get("prob_empate"),
        prob_visitante=bsd_ml.get("prob_visitante"), marcador_probable=bsd_ml.get("marcador_probable"),
    )


def _probabilidades_dc_puras(historico: dict, datos: dict) -> tuple[float, float, float] | None:
    """Probabilidades 1X2 del Dixon-Coles SIN cuotas. Si el módulo ya usó solo DC, son las suyas;
    si apiló con el mercado, se reconstruyen desde los λ del propio módulo (que son los del DC) y
    el `rho` real del modelo de la liga (cae al rho por defecto si no se puede resolver)."""
    if historico.get("metodo") != "dc_mas_mercado":
        probs = tuple(historico.get(clave) for clave in ("prob_local", "prob_empate", "prob_visitante"))
        return probs if all(p is not None for p in probs) else None
    lam_h, lam_a = historico.get("lambda_local"), historico.get("lambda_visit")
    if lam_h is None or lam_a is None:
        return None
    rho = dixon_coles.RHO_POR_DEFECTO
    try:
        resuelto = modelo_historico_svc._resolver(datos)  # noqa: SLF001 — mismo paquete; da el rho del modelo
        if resuelto[0]:
            rho = resuelto[1].rho
    except Exception:  # noqa: BLE001 — sin artefactos se usa el rho por defecto
        log.debug("laboratorio: sin rho del modelo histórico, se usa el por defecto", exc_info=True)
    return dixon_coles.probabilidades_desde_lambdas(float(lam_h), float(lam_a), rho)


def registrar_historico(db: Session, *, partido_id: str, fecha_partido: str, local: str, visitante: str,
                        liga: str, hora_kickoff: str | None, datos: dict, historico: dict) -> None:
    """Comparadores de sombra del modelo entrenado con histórico (`services/modelo_historico.py`).

    Dos variantes separadas para poder medir cada una contra el Poisson, la tasa base y el mercado
    (condición para promoverlas, `.claude/rules/evidencia-historica-antes-de-promover.md`):
      - `dixon_coles_historico`: DC puro, se registra SIEMPRE que el módulo participó.
      - `dc_mas_mercado_historico`: DC apilado con cuotas, solo cuando el módulo usó cuotas.
    Antes ambas se mezclaban en una sola variante y no se podía saber qué aportaba el mercado."""
    if not historico.get("ok"):
        return
    corte = _now()
    contexto = {"historico": historico, "contexto": datos}
    puras = _probabilidades_dc_puras(historico, datos)
    if puras is not None and not _pendiente(db, partido_id, "dixon_coles_historico"):
        registrar_pronostico(
            db, experimento_codigo="dixon_coles_historico", partido_id=partido_id, fecha_partido=fecha_partido,
            local=local, visitante=visitante, liga=liga, fuente="laplace", variante="dixon_coles_historico",
            modelo_version="dc-decay-v1:dixon_coles", corte_datos_en=corte, hora_kickoff=hora_kickoff,
            datos=contexto, pick=_pick_de(puras), prob_local=puras[0], prob_empate=puras[1],
            prob_visitante=puras[2], goles_local_esperados=historico.get("lambda_local"),
            goles_visitante_esperados=historico.get("lambda_visit"),
        )
    if historico.get("metodo") == "dc_mas_mercado" and not _pendiente(db, partido_id, "dc_mas_mercado_historico"):
        registrar_pronostico(
            db, experimento_codigo="dc_mas_mercado_historico", partido_id=partido_id, fecha_partido=fecha_partido,
            local=local, visitante=visitante, liga=liga, fuente="laplace", variante="dc_mas_mercado_historico",
            modelo_version="dc-mercado-v1:dc_mas_mercado", corte_datos_en=corte, hora_kickoff=hora_kickoff,
            datos=contexto, pick=historico.get("pick"), prob_local=historico.get("prob_local"),
            prob_empate=historico.get("prob_empate"), prob_visitante=historico.get("prob_visitante"),
            goles_local_esperados=historico.get("lambda_local"), goles_visitante_esperados=historico.get("lambda_visit"),
        )


def _pick_de(probs: tuple[float, float, float]) -> str:
    return ("Local", "Empate", "Visitante")[max(range(3), key=lambda i: probs[i])]


def registrar_comparadores_del_motor(db: Session, *, partido_id: str, fecha_partido: str, local: str,
                                     visitante: str, liga: str, hora_kickoff: str | None, datos: dict,
                                     modulos: dict, combinado: dict | None = None) -> None:
    """Punto único para congelar TODOS los comparadores propios de una instantánea del motor
    (Poisson, IA contrastada, BSD y Dixon-Coles histórico puro/apilado). Lo usan el análisis
    individual, el flujo exploratorio y Top Picks para que ninguno quede sin medir."""
    comun = dict(partido_id=partido_id, fecha_partido=fecha_partido, local=local, visitante=visitante,
                 liga=liga, hora_kickoff=hora_kickoff, datos=datos)
    registrar_desde_motor(db, **comun, poisson=modulos.get("poisson", {}), combinado=combinado)
    registrar_referencia_bsd(db, **comun, bsd_ml=modulos.get("bsd_ml", {}))
    registrar_historico(db, **comun, historico=modulos.get("historico", {}))


def registrar_referencia_api_football(db: Session, *, partido_id: str, fecha_partido: str, local: str,
                                      visitante: str, liga: str, hora_kickoff: str | None,
                                      respuesta: dict) -> None:
    """Guarda API Football como referencia de sombra, sin cambiar el consenso."""
    if db.query(PronosticoExperimental.id).filter(
        PronosticoExperimental.partido_id == partido_id,
        PronosticoExperimental.variante == "api_football_prediction",
        PronosticoExperimental.resultado_real.is_(None),
    ).first():
        return
    pred = respuesta.get("predictions") or respuesta
    winner = (pred.get("winner") or {}).get("name") if isinstance(pred, dict) else None
    percent = pred.get("percent") or {} if isinstance(pred, dict) else {}
    try:
        probs = tuple(float(str(percent.get(key, "")).replace("%", "")) / 100 for key in ("home", "draw", "away"))
        probabilidades = probs if abs(sum(probs) - 1) <= 0.03 else (None, None, None)
    except (TypeError, ValueError):
        probabilidades = (None, None, None)
    # API-Football puede devolver el nombre del club. Se normaliza a las tres categorías que
    # el evaluador entiende, sin perder la respuesta original para auditoría.
    winner_norm = (winner or "").casefold()
    if winner_norm in {local.casefold(), "home", "local"}:
        winner = "local"
    elif winner_norm in {visitante.casefold(), "away", "visitante"}:
        winner = "visitante"
    elif winner_norm in {"draw", "empate", "x"}:
        winner = "empate"
    registrar_pronostico(
        db, experimento_codigo="api_football_prediction", partido_id=partido_id,
        fecha_partido=fecha_partido, local=local, visitante=visitante, liga=liga,
        hora_kickoff=hora_kickoff, fuente="api-football", variante="api_football_prediction",
        modelo_version="api-football-v3", corte_datos_en=_now(), datos={"api_football": respuesta},
        respuesta_cruda=_json(respuesta), pick=winner,
        prob_local=probabilidades[0], prob_empate=probabilidades[1], prob_visitante=probabilidades[2],
    )


def registrar_ia_simple(db: Session, *, partido_id: str, fecha_partido: str, local: str, visitante: str,
                        liga: str, hora_kickoff: str | None, proveedor: str, modelo: str,
                        prompt_version: str, respuesta: dict, respuesta_cruda: str) -> PronosticoExperimental:
    """Guarda una hipótesis IA con sólo identidad del partido, siempre en sombra.

    Esta función no llama al proveedor: recibe una salida ya validada por el adaptador para que
    el laboratorio siga siendo determinista y el consenso publicado no pueda consumirla.
    """
    pick = str(respuesta.get("pick") or "").strip().casefold()
    if pick not in {"local", "empate", "visitante"}:
        raise ValueError("la hipótesis IA debe declarar pick local, empate o visitante")
    probs = (respuesta.get("prob_local"), respuesta.get("prob_empate"), respuesta.get("prob_visitante"))
    return registrar_pronostico(
        db, experimento_codigo="ia_simple", partido_id=partido_id, fecha_partido=fecha_partido,
        local=local, visitante=visitante, liga=liga, hora_kickoff=hora_kickoff,
        fuente=f"ia:{proveedor}", variante="ia_simple", modelo_version=modelo,
        prompt_version=prompt_version, corte_datos_en=_now(),
        datos={"modo": "solo_equipos_y_competicion", "prompt_version": prompt_version},
        respuesta_cruda=respuesta_cruda, pick=pick,
        prob_local=probs[0], prob_empate=probs[1], prob_visitante=probs[2],
        marcador_probable=respuesta.get("marcador_probable"),
    )


def registrar_referencia_humana(db: Session, *, partido_id: str, fecha_partido: str, local: str,
                                visitante: str, liga: str | None, hora_kickoff: str | None,
                                actor_id: str, alias: str, pick: str, razon: str | None,
                                marcador_probable: str | None = None) -> PronosticoExperimental:
    """Registra una referencia humana atribuida, sin darle peso al consenso público."""
    alias_limpio = "".join(c for c in alias.strip().lower() if c.isalnum() or c in "_-")[:48] or "anonimo"
    return registrar_pronostico(
        db, experimento_codigo="human_reference", partido_id=partido_id, fecha_partido=fecha_partido,
        local=local, visitante=visitante, liga=liga, hora_kickoff=hora_kickoff,
        fuente=f"humano:{alias_limpio}", variante=f"human:{alias_limpio}", corte_datos_en=_now(),
        datos={"actor_admin": actor_id, "alias": alias_limpio, "razon": razon or ""},
        respuesta_cruda=razon, pick=pick, marcador_probable=marcador_probable,
    )


def evaluar_partido(db: Session, *, partido_id: str, goles_local: int, goles_visitante: int) -> int:
    """Califica todas las observaciones pendientes del partido usando el mismo resultado oficial."""
    if goles_local > goles_visitante:
        outcome, one_hot = "local", (1.0, 0.0, 0.0)
    elif goles_visitante > goles_local:
        outcome, one_hot = "visitante", (0.0, 0.0, 1.0)
    else:
        outcome, one_hot = "empate", (0.0, 1.0, 0.0)
    actualizados = 0
    for fila in db.query(PronosticoExperimental).filter(
        PronosticoExperimental.partido_id == partido_id,
        PronosticoExperimental.resultado_real.is_(None),
    ).all():
        fila.resultado_real = f"{goles_local}-{goles_visitante}"
        fila.goles_local_real, fila.goles_visitante_real = goles_local, goles_visitante
        pick = (fila.pick or "").strip().casefold()
        fila.pick_correcto = int(pick in ({"local", fila.local.casefold()} if outcome == "local" else
                                          {"visitante", fila.visitante.casefold()} if outcome == "visitante" else
                                          {"empate", "draw", "x"})) if pick else None
        probs = (fila.prob_local, fila.prob_empate, fila.prob_visitante)
        if all(value is not None for value in probs):
            p_local, p_empate, p_visit = (float(value) for value in probs)
            fila.brier_score = (p_local - one_hot[0]) ** 2 + (p_empate - one_hot[1]) ** 2 + (p_visit - one_hot[2]) ** 2
            chosen = p_local if outcome == "local" else p_empate if outcome == "empate" else p_visit
            fila.log_loss = -math.log(max(chosen, 1e-12))
            fila.rps = 0.5 * ((p_local - one_hot[0]) ** 2 + ((p_local + p_empate) - (one_hot[0] + one_hot[1])) ** 2)
        actualizados += 1
    return actualizados


def reconciliar_resultados_experimentales(db: Session, limite: int = 500) -> dict:
    """Repara observaciones pendientes cuando el resultado oficial ya estaba guardado.

    Cubre reinicios entre la persistencia del resultado y la evaluación. Es idempotente porque
    `evaluar_partido` sólo procesa filas cuyo resultado sigue en NULL.
    """
    pendientes = (
        db.query(PronosticoExperimental.partido_id)
        .filter(PronosticoExperimental.resultado_real.is_(None))
        .distinct()
        .limit(limite)
        .all()
    )
    actualizados = 0
    con_resultado = 0
    for (partido_id,) in pendientes:
        resultado = db.query(ResultadoPartido).filter(ResultadoPartido.fixture_id == partido_id).first()
        if resultado is None or resultado.goles_local is None or resultado.goles_visitante is None:
            continue
        con_resultado += 1
        actualizados += evaluar_partido(
            db, partido_id=partido_id, goles_local=int(resultado.goles_local), goles_visitante=int(resultado.goles_visitante)
        )
    return {"pendientes_revisados": len(pendientes), "partidos_con_resultado": con_resultado, "filas_evaluadas": actualizados}


def reporte_laboratorio(db: Session) -> dict:
    """Reporte administrativo reproducible, sin inferir causalidad ni promover variantes."""
    filas = db.query(PronosticoExperimental).all()
    grupos: dict[tuple[str, str, str], list[PronosticoExperimental]] = {}
    for fila in filas:
        grupos.setdefault((fila.experimento_codigo, fila.fuente, fila.liga or "Sin liga"), []).append(fila)
    comparadores = []
    for (experimento, fuente, liga), items in sorted(grupos.items()):
        evaluados = [item for item in items if item.resultado_real is not None]
        con_pick = [item for item in evaluados if item.pick_correcto is not None]
        con_prob = [item for item in evaluados if item.brier_score is not None]
        comparadores.append({
            "experimento": experimento, "fuente": fuente, "liga": liga, "emitidos": len(items),
            "evaluados": len(evaluados), "aciertos": sum(item.pick_correcto or 0 for item in con_pick),
            "winrate_pct": round(100 * sum(item.pick_correcto or 0 for item in con_pick) / len(con_pick), 2) if con_pick else None,
            "brier_score": round(sum(float(item.brier_score) for item in con_prob) / len(con_prob), 4) if con_prob else None,
            "log_loss": round(sum(float(item.log_loss) for item in con_prob) / len(con_prob), 4) if con_prob else None,
            "rps": round(sum(float(item.rps) for item in con_prob) / len(con_prob), 4) if con_prob else None,
            "muestra_suficiente_exploratoria": len(evaluados) >= MUESTRA_MINIMA_EXPLORATORIA,
            "muestra_suficiente_promocion": len(evaluados) >= MUESTRA_MINIMA_PROMOCION,
        })
    total_emitidos = len(filas)
    total_evaluados = sum(1 for fila in filas if fila.resultado_real is not None)
    return {
        "experimentos": [
            {"codigo": item.codigo, "nombre": item.nombre, "tipo": item.tipo, "estado": item.estado,
             "version": item.version, "permite_consenso": bool(item.permite_consenso)}
            for item in db.query(ExperimentoPronostico).order_by(ExperimentoPronostico.codigo).all()
        ],
        "comparadores": comparadores,
        "resumen": {
            "emitidos": total_emitidos,
            "evaluados": total_evaluados,
            "pendientes": total_emitidos - total_evaluados,
            "muestra_minima_exploratoria": MUESTRA_MINIMA_EXPLORATORIA,
            "alertas": [
                "Ninguna variante puede entrar al consenso hasta revisión administrativa y evidencia fuera de muestra."
            ] + [
                f"{codigo}: sin observaciones registradas." for codigo, _, _, _ in EXPERIMENTOS_BASE
                if not any(fila.experimento_codigo == codigo for fila in filas)
            ],
        },
        "politica": "Las variantes de sombra no participan en el consenso público. Promover una requiere revisión administrativa y evidencia fuera de muestra.",
    }
