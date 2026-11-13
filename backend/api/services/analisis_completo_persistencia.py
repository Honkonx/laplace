"""
services/analisis_completo_persistencia.py — Persistencia de un análisis (individual, multimodelo y registro de sombra). Dividido de `analisis_completo.py` sin cambiar
comportamiento; `analisis_completo.py` reexporta estos nombres.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.db import analisis_repo
from backend.api.services import laboratorio_pronosticos


def _modulos_data_para_guardar(modulos: dict) -> list[dict]:
    """Arma la lista `modulos_data` que espera `analisis_repo.guardar_analisis_multimodelo` — una
    entrada por módulo que sí corrió (`ok=True`; mismo criterio de filtro que ya usa
    `consenso.calcular_pesos_efectivos`), con el dict completo del módulo como `datos_json` para
    no perder los campos que no tienen columna dedicada en `AnalisisModulo` (`over25_prob`,
    `btts_prob`, `marcador_probable`, etc.). Mismo patrón que ya usaba
    `routers/deportivo.py::_persistir_analisis` (endpoint `/api/v1/analisis`, Parte 1) — acá se
    aplica al pipeline real de Telegram/app (2026-09-09, ver nota en `_persistir` más abajo)."""
    return [
        {
            "modulo": nombre, "pick": res.get("pick"), "prob_local": res.get("prob_local"),
            "prob_empate": res.get("prob_empate"), "prob_visitante": res.get("prob_visitante"),
            "score": res.get("confianza_score"), "confianza": res.get("confianza"), "datos_json": res,
        }
        for nombre, res in modulos.items() if res.get("ok")
    ]


def _persistir(db: Session, match_id: str, resultado_motor: dict, combinado: dict | None,
                pick_final: str, confianza_final: str, score_final: int, texto_final: str,
                datos_enriquecidos: dict, fecha_partido: str) -> None:
    analisis_repo.guardar_analisis_individual(
        db, match_id, pick_final, confianza_final, score_final, texto_final,
        fuente="claude" if combinado else "python",
    )
    modulos = resultado_motor.get("modulos", {})
    poisson = modulos.get("poisson", {})
    forma = modulos.get("forma", {})
    h2h = modulos.get("h2h", {})
    odds = modulos.get("odds", {})
    tabla = modulos.get("tabla", {})
    consenso_est = resultado_motor.get("consenso", {})
    nivel_consenso = combinado["nivel_ia"] if combinado else consenso_est.get("nivel", "")
    prob_consenso = consenso_est.get("prob_ponderada") or {}
    pick_py = poisson.get("pick") or consenso_est.get("pick_final") or ""
    prob_local_py = poisson.get("prob_local") if poisson.get("prob_local") is not None else prob_consenso.get("local")
    prob_empate_py = poisson.get("prob_empate") if poisson.get("prob_empate") is not None else prob_consenso.get("empate")
    prob_visit_py = poisson.get("prob_visitante") if poisson.get("prob_visitante") is not None else prob_consenso.get("visitante")

    # 2026-09-09 — normalización AnalisisComparativo/AnalisisModulo (auditoría real: 54 columnas
    # en AnalisisComparativo, varias redundantes con AnalisisModulo — tabla ya diseñada para
    # esto, pero en la BD real tenía 0 filas: existía `guardar_analisis_multimodelo` (escribe
    # ambas tablas en una transacción) pero ningún caller real la llamaba, solo tests). Decisión
    # (Opción A, no Opción B): NO migrar las 19 filas reales existentes de analisis_comparativo —
    # se confirmó empíricamente contra la BD real que sus columnas por-módulo (pick_h2h,
    # score_poisson, score_h2h, score_odds, score_tabla, consenso_nivel, bloque_claude_json, etc.)
    # ya estaban 100% NULL en esas 19 filas (nunca las pobló el pipeline real) — no había ningún
    # dato real que mover, así que "migrar" sería mover filas vacías con riesgo real y cero
    # beneficio. Paso 1 de 2: conectar `guardar_analisis_multimodelo` acá (ya existía completo,
    # solo faltaba este call site) para que TODO análisis nuevo escriba también su fila por
    # módulo en `analisis_modulos`, sin dejar de escribir las columnas anchas de
    # `analisis_comparativo` (ningún query existente que las lee — leer_stats_aciertos,
    # leer_top_picks_app, leer_historial_app, etc. — se rompe). Paso 2 (dejar de escribir las
    # columnas anchas, migrar esas lecturas a `AnalisisModulo`) queda para cuando el volumen real
    # lo justifique — no forzarlo ahora solo por completar la lista.
    analisis_repo.guardar_analisis_multimodelo(
        db,
        partido_id=match_id, local=resultado_motor.get("local", ""), visitante=resultado_motor.get("visitante", ""),
        liga=resultado_motor.get("liga", ""),
        pick_python=pick_py, prob_local_py=prob_local_py,
        prob_empate_py=prob_empate_py, prob_visit_py=prob_visit_py,
        score_poisson=poisson.get("confianza_score", 0),
        pick_claude=combinado["pick_claude"] if combinado else "",
        pick_final=pick_final,
        total_modulos=consenso_est.get("total_modulos", 0),
        consenso=nivel_consenso, consenso_nivel=nivel_consenso,
        coinciden_modulos=consenso_est.get("coinciden", 0),
        score_final=score_final, confianza=confianza_final,
        peso_python=0.6 if combinado else 1.0, peso_ia=0.4 if combinado else 0.0,
        pick_form=forma.get("pick"), score_form=forma.get("confianza_score"),
        pick_h2h=h2h.get("pick"), score_h2h=h2h.get("confianza_score"),
        pick_odds=odds.get("pick"), score_odds=odds.get("confianza_score"),
        pick_tabla=tabla.get("pick"), score_tabla=tabla.get("confianza_score"),
        over25_pred=poisson.get("over25_prob"), btts_pred=poisson.get("btts_prob"),
        modulos_data=_modulos_data_para_guardar(modulos),
        # Sin la hora de inicio no se puede saber si el análisis se creó DESPUÉS del partido (fuga);
        # los 95 análisis históricos de la BD real no la guardaron. Ver `calibracion.comparativo_valido`.
        hora_kickoff=datos_enriquecidos.get("hora_kickoff") or datos_enriquecidos.get("kick_off_utc") or "",
    )
    # Registro de sombra: usa exactamente la instantánea que vio el motor. No se lee desde
    # consenso.py y por tanto no puede cambiar el pick público ni aunque falle esta evaluación.
    laboratorio_pronosticos.registrar_comparadores_del_motor(
        db, partido_id=match_id, fecha_partido=fecha_partido, local=resultado_motor.get("local", ""),
        visitante=resultado_motor.get("visitante", ""), liga=resultado_motor.get("liga", ""),
        hora_kickoff=datos_enriquecidos.get("hora_kickoff") or datos_enriquecidos.get("kick_off_utc"),
        datos=datos_enriquecidos, modulos=modulos, combinado=combinado,
    )
    db.commit()
