"""services/consenso_ia.py — Combina el consenso estadístico (services/consenso.py) con el
pick de Claude. Port de la lógica de `Combinar Análisis` (wfb-022) y `Formatear Respuesta Free`
(wfb-026) de WF-B.

Diferencia deliberada vs. el n8n original (documentada, no un bug oculto): wfb-022 votaba entre
Poisson / Forma / Claude como 3 fuentes independientes, IGNORANDO h2h/odds/tabla en esa votación
aunque los calculaba. Acá se usa el consenso multi-módulo COMPLETO que ya arma
`services/consenso.py::calcular_consenso()` (poisson+forma+h2h+odds+tabla con pesos dinámicos)
como "el lado estadístico", y Claude entra como una segunda opinión independiente — el resultado
es un consenso a 2 vías (estadístico consolidado vs. IA) en vez de perder la señal de h2h/odds/
tabla dentro del voto. Si el usuario prefiere replicar el voto a 3 fuentes original tal cual,
es un cambio acotado a esta función.
"""
from __future__ import annotations

import re
import unicodedata

# La IA interpreta y contrasta. No tiene permiso para elevar una confianza calculada por datos
# verificables: puede mantenerla si coincide o reducirla si diverge.
CONSENSO_AJUSTE = {"COINCIDEN": 0, "DIVERGEN": -8}


_RUIDO = frozenset({"fc", "cf", "club", "sc", "cd", "afc", "ssc"})


def _normalizar_nombre(texto: str | None) -> str:
    """Minúsculas, sin acentos, solo alfanumérico y sin sufijos de ruido (fc/cf/club...)."""
    base = unicodedata.normalize("NFKD", texto or "")
    base = "".join(c for c in base if not unicodedata.combining(c)).lower()
    tokens = [t for t in re.sub(r"[^a-z0-9]+", " ", base).split() if t not in _RUIDO]
    return " ".join(tokens)


def _contiene_frase(texto: str, frase: str) -> bool:
    return bool(frase) and f" {frase} " in f" {texto} "


def _normalizar_pick(pick: str | None, local: str, visitante: str) -> str:
    """Categoría del pick: local / visitante / empate / indeterminado. Exige el nombre COMPLETO
    del equipo; un texto compatible con ambos equipos (o con ninguno) es indeterminado, nunca se
    decide por el primer token (Real Madrid vs Real Sociedad, Manchester United vs City...)."""
    p = _normalizar_nombre(pick)
    if not p:
        return "indeterminado"
    if p in ("local", "home"):
        return "local"
    if p in ("visitante", "away"):
        return "visitante"
    if p in ("empate", "draw", "x"):
        return "empate"
    nombre_local, nombre_visit = _normalizar_nombre(local), _normalizar_nombre(visitante)
    completo_local = _contiene_frase(p, nombre_local)
    completo_visit = _contiene_frase(p, nombre_visit)
    if completo_local and completo_visit:
        # Un nombre contenido en el otro (Real Madrid / Real Madrid Castilla): gana el más largo.
        if _contiene_frase(nombre_visit, nombre_local):
            return "visitante"
        if _contiene_frase(nombre_local, nombre_visit):
            return "local"
        return "indeterminado"
    if completo_local:
        return "local"
    if completo_visit:
        return "visitante"
    # El pick es un fragmento del nombre (ej. "Sociedad"): solo vale si identifica a UN equipo.
    if len(p) >= 3:
        en_local = _contiene_frase(nombre_local, p)
        en_visit = _contiene_frase(nombre_visit, p)
        if en_local != en_visit:
            return "local" if en_local else "visitante"
    return "indeterminado"


def _mapear_pick(categoria: str, local: str, visitante: str) -> str:
    return {"local": local, "visitante": visitante, "empate": "Empate"}.get(categoria, "Indeterminado")


def _ultima_mencion(texto: str, nombre: str) -> tuple[int, int] | None:
    """(inicio, fin) de la última aparición del nombre completo como palabras enteras."""
    if not nombre:
        return None
    ultima = None
    for m in re.finditer(rf"(?<![a-z0-9]){re.escape(nombre)}(?![a-z0-9])", texto):
        ultima = (m.start(), m.end())
    return ultima


def _pick_por_ultima_mencion(texto_claude: str, local: str, visitante: str) -> str:
    texto = _normalizar_nombre(texto_claude)
    nombre_local, nombre_visit = _normalizar_nombre(local), _normalizar_nombre(visitante)
    ml, mv = _ultima_mencion(texto, nombre_local), _ultima_mencion(texto, nombre_visit)
    if ml is None and mv is None:
        return "Indeterminado"
    if mv is None:
        return local
    if ml is None:
        return visitante
    # Un nombre anidado en el otro (misma zona del texto): gana el más específico.
    if ml[0] <= mv[0] and mv[1] <= ml[1]:
        return local
    if mv[0] <= ml[0] and ml[1] <= mv[1]:
        return visitante
    return local if ml[1] > mv[1] else visitante


_PATRONES_PICK = (r"⚖️ Balance y PICK:\s*([^\n—–]+)", r"🎯 PICK:\s*([^\n—–]+)", r"PICK:\s*([^\n—–]+)")


def extraer_pick_claude(texto_claude: str, local: str, visitante: str) -> str:
    """Port de `limpiarPickClaude` — la línea `⚖️ Balance y PICK: <equipo>` es el contrato con
    el prompt de `services/ai_prompts.py`. Si el texto trae varias, vale la ÚLTIMA (la del
    cierre del formato, no un eco en el cuerpo)."""
    for patron in _PATRONES_PICK:
        coincidencias = re.findall(patron, texto_claude)
        if coincidencias:
            return coincidencias[-1].strip()
    return _pick_por_ultima_mencion(texto_claude, local, visitante)


_PORCENTAJE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_TOLERANCIA_PORCENTAJE = 0.6  # "45%" respalda un 45,2 % del prompt (la IA redondea)


def _porcentajes(texto: str) -> list[float]:
    return [float(m.replace(",", ".")) for m in _PORCENTAJE.findall(texto or "")]


def depurar_cifras(texto_ia: str, prompt: str) -> tuple[str, list[str]]:
    """Quita del texto de la IA las líneas con un porcentaje que NO figura en el prompt que recibió.

    El prompt le prohíbe dar probabilidades propias (la IA explica y contrasta, no calcula): un porcentaje ausente del
    prompt es una cifra inventada o derivada por ella. Se descarta solo esa línea (nunca la del PICK) y se devuelve la
    lista de líneas quitadas para registrarlas. Los porcentajes que sí vienen del prompt se conservan."""
    permitidos = _porcentajes(prompt)
    limpias: list[str] = []
    descartadas: list[str] = []
    for linea in (texto_ia or "").split("\n"):
        es_pick = "PICK" in linea.upper()
        sin_respaldo = [v for v in _porcentajes(linea) if not any(abs(v - p) <= _TOLERANCIA_PORCENTAJE for p in permitidos)]
        if sin_respaldo and not es_pick:
            descartadas.append(linea.strip())
        else:
            limpias.append(linea)
    return "\n".join(limpias), descartadas


def combinar_con_claude(resultado_motor: dict, texto_claude: str) -> dict:
    """`resultado_motor` es la salida de `services/motor.py::analizar_partido()`. Devuelve el
    pick unificado, nivel de consenso (estadístico vs IA) y el score consolidado final."""
    local = resultado_motor.get("local", "Local")
    visitante = resultado_motor.get("visitante", "Visitante")
    consenso_est = resultado_motor.get("consenso", {})

    pick_claude_raw = extraer_pick_claude(texto_claude, local, visitante)
    cat_claude = _normalizar_pick(pick_claude_raw, local, visitante)
    pick_claude = _mapear_pick(cat_claude, local, visitante)

    cat_est = _normalizar_pick(consenso_est.get("pick_final"), local, visitante)

    if cat_est != "indeterminado" and cat_claude != "indeterminado" and cat_est == cat_claude:
        nivel_ia = "COINCIDEN"
    elif cat_claude == "indeterminado":
        nivel_ia = "SOLO_ESTADISTICO"
    else:
        nivel_ia = "DIVERGEN"

    pick_unificado = _mapear_pick(cat_est, local, visitante) if cat_est != "indeterminado" else pick_claude

    score_base = consenso_est.get("score_consenso", consenso_est.get("score", 40))
    ajuste = CONSENSO_AJUSTE.get(nivel_ia, 0)
    score_consolidado = max(10, min(95, round(score_base + ajuste)))
    confianza_estadistica = str(consenso_est.get("confianza_final") or (
        "ALTA" if score_base >= 65 else "MEDIA" if score_base >= 40 else "BAJA"
    ))
    # El score numérico no puede comunicar una confianza superior a la del consenso de datos.
    # Esto también protege consumidores antiguos que coloreaban únicamente por score.
    limite_por_confianza = {"ALTA": 95, "MEDIA": 64, "BAJA": 44, "SIN DATOS": 0}
    score_consolidado = min(score_consolidado, limite_por_confianza.get(confianza_estadistica, 44))
    confianza_por_score = "ALTA" if score_consolidado >= 65 else "MEDIA" if score_consolidado >= 40 else "BAJA"
    orden_confianza = {"SIN DATOS": 0, "BAJA": 1, "MEDIA": 2, "ALTA": 3}
    confianza_final = min((confianza_estadistica, confianza_por_score), key=lambda valor: orden_confianza.get(valor, 0))

    return {
        "pick_claude": pick_claude,
        "pick_estadistico": _mapear_pick(cat_est, local, visitante),
        "pick_unificado": pick_unificado,
        "nivel_ia": nivel_ia,
        "score_consolidado": score_consolidado,
        "confianza_final": confianza_final,
        "texto_claude": texto_claude,
    }
