"""
services/consenso.py — Árbitro final del motor de análisis multi-modelo.

Port de consenso.py — mismos PESOS_BASE, mismos umbrales de nivel
(FUERTE/MODERADO/DEBIL/SOLO_<modulo>/SOLO_FALLBACK — con un único módulo el nivel es
`SOLO_` + el nombre del módulo en mayúsculas: SOLO_ODDS, SOLO_POISSON, SOLO_HISTORICO...), misma lógica de ajuste dinámico de
pesos por score. Ya no es un script CLI ni loguea a archivo (`utils.setup_log`) — logging
real de FastAPI se agrega en Parte 2 (ver skill logging-observability).
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.api.services._matematica import clamp as _clamp
from backend.api.services._matematica import normalizar_probabilidades
from backend.api.services._matematica import safe_float as _safe_float

# Pesos revisados 2026-10-07 con la evaluación walk-forward del CONSENSO REAL completo
# (`backend/scripts/evaluar_consenso_historico.py`, informe `EVALUACION_CONSENSO_HISTORICO_2026-10-06.md`,
# 154.421 partidos de 49 ligas, prueba desde 2023-07-01: 15.909 partidos con cuotas de apertura):
#   - El consenso con los pesos anteriores (poisson .10, historico .25, forma .10, h2h .10, odds .32,
#     tabla .08, bsd_ml .05) daba log-loss 1,0095 con cuotas: PEOR que las cuotas solas (0,9929) por
#     +0,0166 (IC95 [+0,0144, +0,0188]); sin cuotas 1,0362 contra 1,0131 de Dixon-Coles solo.
#   - Quitar poisson mejora 0,0087, h2h 0,0037 y forma 0,0016 con las heurísticas actuales; tabla es
#     neutra; historico (quitarlo empeora 0,0137; sin cuotas 0,060) y odds (0,0165) son los que aportan.
#   - Un peso 0 equivale a módulo AUSENTE del consenso (ver `calcular_pesos_efectivos`): el módulo
#     sigue corriendo y registrándose en el laboratorio, pero no vota, no cuenta en `total_modulos`
#     ni en el bonus de score. `bsd_ml` queda en 0 porque no se pudo reconstruir históricamente; se
#     mide en el laboratorio (`bsd_catboost`).
#   - Con estos pesos el pick (argmax de la probabilidad ponderada) coincide con el del mercado.
PESOS_BASE: dict[str, float] = {
    "poisson": 0.0,
    "historico": 0.25,
    "forma": 0.02,
    "h2h": 0.0,
    "odds": 0.70,
    "tabla": 0.03,
    "bsd_ml": 0.0,
}

# Confianza calibrada con datos (misma evaluación): por probabilidad ponderada del pick,
# acierto observado ~72% con >= 0,60, ~57% entre 0,50 y 0,60, ~46% entre 0,45 y 0,50 y ~40% bajo 0,45.
# Las etiquetas anteriores (score/coincidencias) no estaban calibradas: MEDIA acertaba 41% y BAJA 38%,
# menos que "siempre Local" (43%).
PROB_CONFIANZA_ALTA = 0.60
PROB_CONFIANZA_MEDIA = 0.50

MODULOS_TODOS = list(PESOS_BASE.keys())
MODULOS_ANCLA = frozenset({"odds", "historico"})  # los dos que la evaluación walk-forward midió con información real

UMBRAL_FUERTE = 0.70
UMBRAL_MODERADO = 0.55

SCORE_UMBRAL_BAJO = 40
SCORE_UMBRAL_MUY_BAJO = 25


def _resultado_de(resultados: dict, modulo: str) -> dict:
    """Resultado de un módulo, o {} si falta o no es un diccionario (un módulo roto no debe tumbar el consenso)."""
    r = resultados.get(modulo) if isinstance(resultados, dict) else None
    return r if isinstance(r, dict) else {}


def _puntaje(valor) -> float:
    """Puntaje de confianza acotado a 0–100; 50 si falta, es None, NaN o no numérico."""
    v = _safe_float(valor, 50.0, finito=True)
    return _clamp(v, 0.0, 100.0)


def calcular_pesos_efectivos(resultados: dict) -> tuple[dict[str, float], list[str]]:
    pesos: dict[str, float] = {}
    modulos_ok: list[str] = []

    for modulo in MODULOS_TODOS:
        res = _resultado_de(resultados, modulo)
        peso_base = PESOS_BASE[modulo]
        # Peso 0 = módulo ausente del consenso (no vota ni cuenta como módulo disponible).
        if not res.get("ok", False) or peso_base <= 0:
            pesos[modulo] = 0.0
            continue

        score = _puntaje(res.get("confianza_score"))

        if score < SCORE_UMBRAL_MUY_BAJO:
            factor = 0.20
        elif score < SCORE_UMBRAL_BAJO:
            factor = 0.50
        else:
            factor = 1.0 + _clamp((score - 40) / 183.3, 0.0, 0.30)

        pesos[modulo] = peso_base * factor
        modulos_ok.append(modulo)

    total_peso = sum(pesos.values())
    if total_peso > 0:
        pesos = {m: round(p / total_peso, 4) for m, p in pesos.items()}
    else:
        pesos = {m: 0.0 for m in MODULOS_TODOS}

    return pesos, modulos_ok


def calcular_votos_ponderados(resultados: dict, pesos_efectivos: dict, modulos_ok: list[str]):
    votos_peso = {"Local": 0.0, "Empate": 0.0, "Visitante": 0.0}
    votos_count = {"Local": 0, "Empate": 0, "Visitante": 0}

    prob_local_acum = prob_empate_acum = prob_visit_acum = peso_prob_acum = 0.0

    for modulo in modulos_ok:
        res = _resultado_de(resultados, modulo)
        pick = res.get("pick", "")
        peso = pesos_efectivos.get(modulo, 0.0)

        if pick in votos_peso:
            votos_peso[pick] += peso
            votos_count[pick] += 1

        prob_local = _safe_float(res.get("prob_local"), 0.0)
        prob_emp = _safe_float(res.get("prob_empate"), 0.0)
        prob_visit = _safe_float(res.get("prob_visitante"), 0.0)

        if prob_local + prob_emp + prob_visit > 0:
            prob_local_acum += prob_local * peso
            prob_empate_acum += prob_emp * peso
            prob_visit_acum += prob_visit * peso
            peso_prob_acum += peso

    if peso_prob_acum > 0:
        prob_local_pond, prob_empate_pond, prob_visit_pond = normalizar_probabilidades(
            prob_local_acum, prob_empate_acum, prob_visit_acum, peso_prob_acum
        )
    else:
        prob_local_pond, prob_empate_pond, prob_visit_pond = 0.3334, 0.3333, 0.3333

    prob_ponderada = {"local": prob_local_pond, "empate": prob_empate_pond, "visitante": prob_visit_pond}

    total_votos = sum(votos_peso.values())
    if total_votos > 0:
        votos_peso = {k: round(v / total_votos, 4) for k, v in votos_peso.items()}

    return votos_peso, votos_count, prob_ponderada


def calcular_score_consenso(resultados, pesos_efectivos, modulos_ok, pick_final, votos_peso, nivel):
    score_base = 0.0
    peso_base_acum = 0.0

    for modulo in modulos_ok:
        res = _resultado_de(resultados, modulo)
        pick = res.get("pick", "")
        if pick == pick_final:
            score_mod = _puntaje(res.get("confianza_score"))
            peso_mod = pesos_efectivos.get(modulo, 0.0)
            score_base += score_mod * peso_mod
            peso_base_acum += peso_mod

    score_base = score_base / peso_base_acum if peso_base_acum > 0 else 40.0

    # Un módulo aislado puede orientar una exploración, pero no prueba acuerdo. Antes el voto
    # único de odds recibía nivel FUERTE por definición (peso normalizado 1.0) y podía alcanzar
    # 80+, como si varios modelos independientes coincidieran. Lo acotamos antes de evaluar
    # rendimiento real de cada módulo en solitario.
    if len(modulos_ok) == 1:
        return _clamp(min(round(score_base), 39), 10, 39)

    # Con un solo módulo la función ya retornó arriba (tope 39), así que `SOLO_<modulo>` no llega
    # aquí con un módulo real; se contempla por prefijo para que cualquier SOLO_* sea neutro y
    # `SOLO_FALLBACK` siga siendo la única variante que penaliza.
    if nivel.startswith("SOLO_") and nivel != "SOLO_FALLBACK":
        ajuste_nivel = 0
    else:
        ajuste_nivel = {"FUERTE": 10, "MODERADO": 3, "DEBIL": -10, "SOLO_FALLBACK": -15}.get(nivel, 0)

    bonus_modulos = {1: 0, 2: 3, 3: 5, 4: 7, 5: 10}.get(len(modulos_ok), 0)

    return _clamp(round(score_base + ajuste_nivel + bonus_modulos), 10, 95)


def determinar_nivel(modulos_ok: list[str], votos_peso: dict, pick_final: str) -> str:
    if not modulos_ok:
        return "SOLO_FALLBACK"
    if len(modulos_ok) == 1:
        return f"SOLO_{modulos_ok[0].upper()}"

    ratio = votos_peso.get(pick_final, 0.0)
    if ratio >= UMBRAL_FUERTE:
        return "FUERTE"
    elif ratio >= UMBRAL_MODERADO:
        return "MODERADO"
    return "DEBIL"


CONTRATO_CONSENSO = "consenso.v1"


def construir_procedencia(resultados: dict, pesos_efectivos: dict, modulos_ok: list[str]) -> dict:
    """Procedencia del pronóstico (contrato `consenso.v1`, MB-40): qué módulos respondieron y cuáles no, con qué peso y método, la versión del modelo propio cuando entró en la mezcla, los
    pesos configurados y el instante del cálculo. Es descriptiva: no cambia ninguna cifra. El agente y la web leen estos mismos campos."""
    modulos = []
    for modulo in modulos_ok:
        r = resultados.get(modulo) or {}
        propio = r.get("laplace_en_mezcla") or {}
        modulos.append({"modulo": modulo, "peso": round(pesos_efectivos.get(modulo, 0.0), 4), "metodo": r.get("metodo"),
                        "version_modelo_propio": propio.get("version"), "peso_modelo_propio": propio.get("peso")})
    return {"contrato": CONTRATO_CONSENSO, "calculado_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "modulos": modulos,
            "modulos_sin_respuesta": [m for m in MODULOS_TODOS if m not in modulos_ok], "pesos_configurados": dict(PESOS_BASE)}


def calcular_consenso(resultados: dict, partido: dict | None = None) -> dict:
    """Orquesta pesos → votación → nivel → score. `resultados` es
    {modulo: resultado_del_modulo} (mismo shape que armaba datos.py)."""
    pesos_efectivos, modulos_ok = calcular_pesos_efectivos(resultados)

    if not modulos_ok:
        return {
            # Un fallback uniforme no es una predicción. Antes se devolvía "Local"
            # con probabilidades 33/33/33, lo que podía filtrarse como recomendación
            # cuando un caller no aplicaba su propia puerta de calidad.
            "contrato": CONTRATO_CONSENSO,
            "pick_final": "Sin pronóstico",
            "nivel": "SIN_MODULOS",
            "coinciden": 0,
            "total_modulos": 0,
            "detalle": "Ningún módulo devolvió resultado válido",
            "score_consenso": 0,
            "confianza_final": "SIN DATOS",
            "votos": {"Local": 0, "Empate": 0, "Visitante": 0},
            "prob_ponderada": {"local": 0.3334, "empate": 0.3333, "visitante": 0.3333},
            "modulos_en_consenso": [],
            "modulos_disidentes": [],
            "peso_efectivo": pesos_efectivos,
            "pick": "Sin pronóstico",
            "confianza": "SIN DATOS",
            "score": 0,
        }

    votos_peso, votos_count, prob_ponderada = calcular_votos_ponderados(resultados, pesos_efectivos, modulos_ok)

    # Cada módulo aporta una distribución 1X2, no solo un voto binario. Elegir el resultado
    # por los votos hacía que un Poisson exploratorio pudiera publicar «Empate» aunque la
    # probabilidad agregada favoreciera claramente al local o visitante. Los votos se conservan
    # para medir acuerdo y confianza; el pick se deriva de la evidencia probabilística completa.
    probabilidades_pick = {
        "Local": prob_ponderada["local"],
        "Empate": prob_ponderada["empate"],
        "Visitante": prob_ponderada["visitante"],
    }
    pick_final = max(probabilidades_pick, key=probabilidades_pick.get)
    nivel = determinar_nivel(modulos_ok, votos_peso, pick_final)
    score_consenso = calcular_score_consenso(resultados, pesos_efectivos, modulos_ok, pick_final, votos_peso, nivel)

    # Una probabilidad agregada por debajo de 48% describe una señal disputada, incluso si el
    # módulo de mercado tiene más peso que los demás. Sin este límite un único voto de odds
    # podía arrastrar el score por encima de 70 aunque 2 de 3 módulos discreparan.
    probabilidad_ganadora = probabilidades_pick[pick_final]
    if probabilidad_ganadora < 0.48:
        nivel = "DEBIL"
        score_consenso = min(score_consenso, 44)

    modulos_en_consenso = [m for m in modulos_ok if resultados.get(m, {}).get("pick") == pick_final]
    modulos_disidentes = [m for m in modulos_ok if resultados.get(m, {}).get("pick") != pick_final]

    # La confianza sale de la probabilidad ponderada (calibrada con datos reales, ver PROB_CONFIANZA_*),
    # no de cuántos módulos coinciden: los módulos están correlacionados y el acuerdo no era evidencia.
    #
    # Qué respalda una etiqueta: solo un módulo ANCLA (mercado o histórico con ambos equipos conocidos). Medido el
    # 2026-10-19 en el periodo de prueba (>= 2023-07-01), la probabilidad máxima de cada ancla SOLO acierta:
    #   cuotas sin margen (n=20.960):  <0,48 → 41,3 %  | 0,50-0,60 → 55,8 %  | >=0,60 → 71,2 %  | >=0,70 → 80,3 %
    #   Dixon-Coles (n=42.605):        <0,48 → 41,0 %  | 0,50-0,60 → 55,0 %  | >=0,60 → 69,3 %  | >=0,70 → 78,5 %
    # Están calibrados, así que un ancla único NO se degrada a BAJA por ser único (tope vigente desde 2026-10-05, que
    # dejaba en BAJA hasta un 80 % de acierto). Lo que sí se degrada:
    #   - sin ancla: tabla y forma pesan 3 % y 2 % y al renormalizar daban ALTA con 9 puntos de error en P(local)
    #     (sandbox, escenario D);
    #   - histórico con un equipo sin historial (el rating del otro es un promedio) o un modelo de más de 2 años:
    #     como máximo MEDIA, sin pasar a ALTA.
    anclas = [m for m in modulos_ok if m in MODULOS_ANCLA and not resultados.get(m, {}).get("equipo_sin_historial")]
    solo_historico_viejo = anclas == ["historico"] and (resultados["historico"].get("edad_modelo_dias") or 0) > 730
    if not anclas or probabilidad_ganadora < PROB_CONFIANZA_MEDIA:
        confianza_final = "BAJA"
        score_consenso = min(score_consenso, 44)
    elif probabilidad_ganadora >= PROB_CONFIANZA_ALTA and not solo_historico_viejo:
        confianza_final = "ALTA"
        score_consenso = max(score_consenso, 65)
    else:
        confianza_final = "MEDIA"
        score_consenso = max(45, min(score_consenso, 64))

    coinciden = votos_count.get(pick_final, 0)
    total_mod = len(modulos_ok)
    detalle = (
        f"Pick por probabilidad ponderada ({probabilidades_pick[pick_final] * 100:.1f}%): "
        f"{coinciden}/{total_mod} modelos votan {pick_final}"
    )

    peso_efectivo_out = {m: round(pesos_efectivos.get(m, 0.0), 3) for m in MODULOS_TODOS}
    bsd_ml_activo = "bsd_ml" in modulos_ok

    return {
        "pick_final": pick_final,
        "nivel": nivel,
        "coinciden": coinciden,
        "total_modulos": total_mod,
        "detalle": detalle,
        "score_consenso": score_consenso,
        "confianza_final": confianza_final,
        "votos": votos_count,
        "votos_peso": {k: round(v, 3) for k, v in votos_peso.items()},
        "prob_ponderada": prob_ponderada,
        "criterio_pick": "probabilidad_ponderada",
        "modulos_en_consenso": modulos_en_consenso,
        "modulos_disidentes": modulos_disidentes,
        "peso_efectivo": peso_efectivo_out,
        "bsd_ml_activo": bsd_ml_activo,
        "contrato": CONTRATO_CONSENSO,
        "procedencia": construir_procedencia(resultados, pesos_efectivos, modulos_ok),
        "pick": pick_final,
        "confianza": confianza_final,
        "score": score_consenso,
    }


def resumen_probabilidad_consenso(consenso: dict | None) -> dict | None:
    """Probabilidad que de verdad decide el pick público, con su procedencia.

    Devuelve None cuando el consenso no tiene módulos (la tripleta neutra 33/33/33 no es una
    estimación). `procedencia` lista los módulos con peso efectivo > 0 ordenados por peso, para
    mostrar al usuario de dónde sale el número en vez de enseñar solo el Poisson."""
    if not consenso or not consenso.get("total_modulos"):
        return None
    prob = consenso.get("prob_ponderada") or {}
    if not prob:
        return None
    pesos = consenso.get("peso_efectivo") or {}
    procedencia = sorted(((m, p) for m, p in pesos.items() if p and p > 0), key=lambda x: x[1], reverse=True)
    return {
        "local": prob.get("local", 0.0),
        "empate": prob.get("empate", 0.0),
        "visitante": prob.get("visitante", 0.0),
        "procedencia": [(m, round(p * 100)) for m, p in procedencia],
    }


def texto_probabilidad_consenso(consenso: dict | None, etiqueta_local: str = "Local",
                                etiqueta_visitante: str = "Visitante") -> str:
    """Una línea legible: «Local 45.2% | Empate 27.1% | Visitante 27.7% (odds 41%, histórico 30%)».
    Cadena vacía si no hay estimación del consenso."""
    resumen = resumen_probabilidad_consenso(consenso)
    if resumen is None:
        return ""
    base = (
        f"{etiqueta_local} {round(resumen['local'] * 100, 1)}% | Empate {round(resumen['empate'] * 100, 1)}% | "
        f"{etiqueta_visitante} {round(resumen['visitante'] * 100, 1)}%"
    )
    if resumen["procedencia"]:
        base += " (" + ", ".join(f"{m} {p}%" for m, p in resumen["procedencia"]) + ")"
    return base
