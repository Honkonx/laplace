"""services/ai_prompts.py — Prompt de análisis IA para Telegram/App (WF-B `Claude — Análisis IA`).

Antes este prompt vivía SOLO en el nodo n8n `wfb-016` (`@n8n/n8n-nodes-langchain.anthropic`) —
no existía en ningún `.py`. Se porta acá tal cual (mismas 10 reglas de formato, mismo orden de
secciones) para que `services/ai_client.py` lo use en la cascada de proveedores de IA en vez de la integración
langchain de n8n.

El prompt del canal Top Picks (WF-D) es distinto — vive en `services/ai_prompt_canal.py`.
"""
from __future__ import annotations

import re
import unicodedata

LONGITUD_MAXIMA_NOMBRE = 80
LONGITUD_MAXIMA_BLOQUE = 600

# Marcadores del formato que `services/consenso_ia.py` y `ai_prompt_canal.py` parsean: un nombre de
# equipo o texto externo que los traiga no puede fabricar una línea de pick.
_MARCADORES = re.compile(r"\b(balance\s+y\s+pick|pick|raz[óo]n|confianza)\s*:", re.IGNORECASE)
_EMOJIS_FORMATO = re.compile("[\u2696\U0001F3AF\U0001F48E\uFE0F]")


def _limpiar_linea(texto: str) -> str:
    sin_control = "".join(
        " " if c.isspace() else c for c in texto if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf")
    )
    sin_marcadores = _MARCADORES.sub(lambda m: m.group(1) + " -", _EMOJIS_FORMATO.sub("", sin_control))
    return re.sub(r"-{3,}", "-", re.sub(r"\s+", " ", sin_marcadores)).strip()


def sanear_texto(valor: object, max_len: int = LONGITUD_MAXIMA_NOMBRE, multilinea: bool = False) -> str:
    """Texto seguro para interpolar en un prompt: sin caracteres de control ni saltos de línea
    (salvo `multilinea`, que conserva líneas pero limpia cada una), longitud acotada y marcadores
    del formato parseado (`PICK:`, `⚖️ Balance y PICK`, `RAZÓN:`, `---`) neutralizados."""
    if valor is None:
        return ""
    bruto = str(valor)
    if multilinea:
        lineas = [_limpiar_linea(linea) for linea in bruto.splitlines()]
        return "\n".join(linea for linea in lineas if linea)[:max_len].rstrip()
    return _limpiar_linea(bruto)[:max_len].rstrip()


def _bloque_tasas_base(d: dict) -> str:
    """Tasas históricas reales de la liga (2026-09-29): sin ellas un LLM tiende a elegir empates
    o favoritos por intuición. Vacío si la liga no tiene histórico medido — nunca se inventa."""
    from backend.api.services.modelo_historico import tasas_base_liga

    t = tasas_base_liga(d)
    if not t:
        return ""
    return (
        f"\nTASAS BASE HISTÓRICAS DE LA LIGA ({t['partidos']} partidos reales): gana el local "
        f"{t['pct_local']}%, empate {t['pct_empate']}%, gana el visitante {t['pct_visitante']}%, "
        f"{t['goles_por_partido']} goles por partido. Elige Empate solo si los datos de este partido lo "
        "justifican con claridad; un favorito por cuota o forma no debe ignorarse por intuición.\n"
    )


def construir_prompt_analisis(d: dict) -> str:
    """`d` es el mismo dict que ya pasó por `services/motor.py` (trae `resumen_estadistico`,
    `standings_info`, `h2h_resumen`, `odds_info`, etc.) — mismos campos que leía el nodo
    `wfb-016` desde `$json`."""
    local = sanear_texto(d.get("local", "Local")) or "Local"
    visitante = sanear_texto(d.get("visitante", "Visitante")) or "Visitante"
    partido = sanear_texto(d.get("partido")) or f"{local} vs {visitante}"
    liga = sanear_texto(d.get("liga", ""))
    standings = sanear_texto(
        d.get("standings_info", "Datos de tabla no disponibles para esta liga."), LONGITUD_MAXIMA_BLOQUE, True)
    h2h = sanear_texto(
        d.get("h2h_resumen", "Sin historial directo disponible."), LONGITUD_MAXIMA_BLOQUE, True)
    odds = sanear_texto(d.get("odds_info", "Sin odds disponibles — análisis estadístico puro."), 300)
    resumen = sanear_texto(d.get("resumen_estadistico", "Motor estadístico no disponible."), 1500, True)
    total_h2h = sanear_texto(d.get("total_h2h", 0), 10)
    victorias_local = sanear_texto(d.get("forma_local_wins", 2), 10)
    victorias_visit = sanear_texto(d.get("forma_visit_wins", 2), 10)
    goles_local = sanear_texto(d.get("goles_local_avg", ""), 10)
    goles_visit = sanear_texto(d.get("goles_visit_avg", ""), 10)
    return f"""Eres un analista deportivo profesional especializado en fútbol. Tu trabajo es leer
los datos reales de abajo (tabla de posiciones, forma reciente, H2H y odds del mercado) y producir
un pronóstico fundamentado y consistente con esos datos — nunca con intuición ni con información
externa a la que se te entrega. Tu rol es EXPLICAR y CONTRASTAR, no calcular probabilidades: las
cifras las producen modelos medidos. Tu análisis se compara después con un modelo estadístico Poisson
independiente: no intentes adivinar ni replicar ese modelo, razoná de forma autónoma solo a partir
de los datos que ves abajo.

DATOS DISPONIBLES:
Partido: {partido}
Liga: {liga}
Tabla: {standings}
H2H ({total_h2h} partidos):
{h2h}
Odds: {odds}

ESTADÍSTICAS DE EQUIPOS (forma y goles recientes):
{local}: {victorias_local}/5 victorias recientes | Goles/partido: {goles_local}
{visitante}: {victorias_visit}/5 victorias recientes | Goles/partido: {goles_visit}

REFERENCIA ESTADÍSTICA (no la copies, úsala para calibrar tu análisis):
{resumen}
{_bloque_tasas_base(d)}
REGLAS ESTRICTAS — NUNCA VIOLAR:
1. SIN Markdown, asteriscos, guiones ni hashtags
2. SIN frases introductorias ni relleno
3. Cada línea 📈: máximo 1 dato clave por equipo
4. El PICK final va en la última línea, con formato exacto:
   ⚖️ Balance y PICK: [SOLO nombre del equipo o la palabra Empate]
   Sin frases, sin explicaciones en esa línea
5. BTTS y Over 2.5 en una sola línea
6. SIN sección de confianza ni porcentajes de probabilidad — el sistema los calcula
7. Si standings_info contiene "no disponibles" o "Sin datos" → usar ESTADÍSTICAS DE EQUIPOS para la línea 📈
8. Si standings_info contiene "no disponibles" o "Sin datos" → NO escribir "Sin datos de tabla" — usar forma y goles de la sección ESTADÍSTICAS DE EQUIPOS
9. Si odds_info contiene "no disponibles" → escribir:
   💰 Sin odds disponibles
   NO estimes porcentajes implícitos
10. NUNCA inventes estadísticas. Sin dato real en ninguna fuente → escribe "Sin datos"
11. NO contradigas las cifras entregadas (tabla, forma, H2H, odds, tasas base, referencia estadística):
    si tu lectura difiere, dilo con datos de esta sección, no con cifras propias
12. NO menciones probabilidades ni porcentajes propios y NO propongas value bets ni apuestas:
    el sistema no te pide una estimación de valor

Responde ÚNICAMENTE con el bloque de abajo, sin texto antes ni después ni comentarios propios —
el sistema parsea tu respuesta con este formato exacto, cualquier texto extra rompe el parseo.

FORMATO EXACTO — respetar orden y emojis:

🏆 {partido}
📍 {liga}

DATOS

📈 {local}: [1 dato clave real — usar forma/goles si no hay tabla]
📈 {visitante}: [1 dato clave real — usar forma/goles si no hay tabla]

📜 H2H:
{h2h}

💰 Odds: {odds}

🥅 BTTS y Over 2.5: [Sí/No ambos] — [razón en 5 palabras]
🎯 Marcador: [X-X]

⚖️ Balance y PICK: [SOLO nombre del equipo o Empate]"""
