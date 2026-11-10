"""services/ai_prompt_canal.py — Prompt de Claude para el Top 3 Picks del canal (WF-D).

Distinto del prompt de WF-B (`services/ai_prompts.py`, análisis 1 a 1 para un usuario) — este
analiza 3 partidos a la vez y devuelve 3 bloques PICK/RAZÓN/CONFIANZA separados por `---`.
Texto del prompt copiado literal del nodo `Claude — Análisis Canal` (wfd-008) leído en esta
conversación — no se reformula, solo se parametriza con f-strings donde antes había `{{ }}` de
n8n.
"""
from __future__ import annotations

import re

from backend.api.services.ai_prompts import sanear_texto


def _bloque_partido(numero: int, c: dict | None) -> str:
    if c is None:
        return (
            f"PARTIDO {numero}:\nEquipos: Sin partido\nLiga:  | Hora Chile: \n"
            "Stats local: Sin datos\nStats visitante: Sin datos\nH2H: Sin datos\n"
            "Poisson pick: N/A (score 0)\nForma pick: N/A (score 0)\nOdds: Sin odds\n"
            "Predicción externa: N/A"
        )
    est = c.get("estadistico") or {}
    frm = c.get("estadistico_form") or {}
    local = sanear_texto(c.get("local"))
    visitante = sanear_texto(c.get("visitante"))
    odds_txt = "Sin odds"
    if c.get("odds_local"):
        odds_txt = (
            f"{local} @{sanear_texto(c['odds_local'], 12)} | Emp @{sanear_texto(c.get('odds_empate'), 12)} | "
            f"{visitante} @{sanear_texto(c.get('odds_visit'), 12)}"
        )
    return (
        f"PARTIDO {numero}:\n"
        f"Equipos: {local} vs {visitante}\n"
        f"Liga: {sanear_texto(c.get('liga', ''))} | Hora Chile: {sanear_texto(c.get('hora_chile', ''), 20)}\n"
        f"Stats local: {sanear_texto(c.get('stats_local_str', 'Sin datos'), 300)}\n"
        f"Stats visitante: {sanear_texto(c.get('stats_visit_str', 'Sin datos'), 300)}\n"
        f"H2H: {sanear_texto(c.get('h2h_resumen', 'Sin historial directo.'), 300)}\n"
        f"Poisson pick: {sanear_texto(est.get('pick', 'N/D'))} (score {sanear_texto(est.get('confianza_score', 0), 10)})\n"
        f"Forma pick: {sanear_texto(frm.get('pick', 'N/D'))} (score {sanear_texto(frm.get('confianza_score', 0), 10)})\n"
        f"Odds: {odds_txt}\n"
        f"Predicción externa: {sanear_texto(c.get('pick_externo')) or 'No disponible'}"
    )


def construir_prompt_canal(top3: list[dict]) -> str:
    """`top3` tiene 1 a 3 elementos (los slots faltantes se rellenan como 'Sin partido',
    igual que hacía la expresión `{{ $json.top3[i] ? ... : 'Sin partido' }}` de n8n)."""
    partidos = [top3[i] if i < len(top3) else None for i in range(3)]
    bloques_partidos = "\n\n".join(_bloque_partido(i + 1, c) for i, c in enumerate(partidos))

    return f"""Eres un analista deportivo experto. Se te dan 3 partidos con datos estadísticos de múltiples motores.

CONTEXTO DE DATOS:
- Poisson: modelo probabilístico con goles promedio reales de la temporada
- Forma: modelo basado en victorias recientes (últimos 5 partidos)
- H2H: historial directo disponible cuando se indica
- Externo: predicción de api-football cuando disponible

REGLAS ESTRICTAS:
1. SIN Markdown, asteriscos, hashtags
2. PICK = SOLO nombre exacto del equipo local, visitante, o la palabra Empate
3. RAZÓN = 1 oración, máximo 15 palabras, con dato concreto
4. CONFIANZA = numero entero 0-100 reflejando tu certeza real considerando todos los datos
5. Si los modelos coinciden → mayor confianza. Si divergen → menor confianza
6. SIEMPRE da un pick aunque los datos sean escasos — usa lo disponible
7. Prioriza odds cuando estén disponibles (reflejan el mercado real)
8. NO contradigas las cifras entregadas ni inventes probabilidades, porcentajes ni value bets propios:
   tu rol es explicar y contrastar, las cifras las producen modelos medidos

{bloques_partidos}

FORMATO — exactamente 3 bloques separados por ---:

PICK: [nombre equipo o Empate]
RAZÓN: [1 oración, máximo 15 palabras, dato concreto]
CONFIANZA: [numero 0-100]
---
PICK: [nombre equipo o Empate]
RAZÓN: [1 oración, máximo 15 palabras, dato concreto]
CONFIANZA: [numero 0-100]
---
PICK: [nombre equipo o Empate]
RAZÓN: [1 oración, máximo 15 palabras, dato concreto]
CONFIANZA: [numero 0-100]"""


def parsear_bloque(bloque: str) -> dict:
    """Extrae pick/razón/confianza de un bloque de la respuesta — mismo parseo por regex que
    `parsearBloque` en wfd-009."""
    pick_m = re.search(r"PICK:\s*([^\n]+)", bloque)
    razon_m = re.search(r"RAZ[ÓO]N:\s*([^\n]+)", bloque)
    conf_m = re.search(r"CONFIANZA:\s*(\d+)", bloque)
    return {
        "pick": pick_m.group(1).strip() if pick_m else "Sin datos",
        "razon": razon_m.group(1).strip() if razon_m else "",
        "confianza": int(conf_m.group(1)) if conf_m else None,
    }


def parsear_respuesta_canal(texto_claude: str) -> list[dict]:
    return [parsear_bloque(b.strip()) for b in texto_claude.split("---")]
