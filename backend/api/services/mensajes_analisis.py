"""services/mensajes_analisis.py — Formatea el mensaje final de Telegram/App.

Port de `Formatear Respuesta`/`Combinar Análisis` (wfb-017/wfb-022, plan con IA) y
`Formatear Respuesta Free` (wfb-026, plan free/sin IA) de WF-B.
"""
from __future__ import annotations

import html

from backend.api.core.config import settings
from backend.api.services import consenso as consenso_svc

SEPARADOR = "━━━━━━━━━━━━━━━━━━━━━━"
def pie_comunidad(canal: str, grupo_url: str) -> str:
    """Líneas del canal y del grupo de la comunidad. Si no están configurados (p. ej. un fork) no se muestran."""
    lineas = []
    if canal:
        lineas.append(f"📢 Canal: {canal}")
    if grupo_url:
        lineas.append(f'💬 <a href="{grupo_url}">{html.escape(settings.TELEGRAM_GRUPO_NOMBRE)}</a>')
    return "\n".join(lineas)


def _footer(canal: str, grupo_url: str) -> str:
    pie = pie_comunidad(canal, grupo_url)
    return f"\n{pie}" if pie else ""

_CONF_EMOJI = {"ALTA": "🟢", "MEDIA": "🟡", "BAJA": "🔴"}
_BANKROLL = {"ALTA": "3-5%", "MEDIA": "1-2%", "BAJA": "0.5%"}


def _bloque_datos_desde_claude(texto_claude: str) -> str:
    idx = texto_claude.find("⚖️ Balance y PICK:")
    bloque = texto_claude[:idx] if idx > -1 else texto_claude
    # Si una versión anterior del prompt aún hace escribir la línea de "Value" a la IA, no se
    # muestra: el value bet no está validado (se calculaba con el Poisson). Funciona igual si la
    # IA ya no la trae.
    lineas = [linea for linea in bloque.splitlines() if "💎 Value" not in linea]
    return "\n".join(lineas).rstrip()


def _linea_estadistico(consenso: dict | None, poisson: dict) -> str:
    """Probabilidades del consenso (las que deciden el pick) + el Poisson solo como detalle
    secundario rotulado. Nunca se muestra el Poisson como si fuera la estimación del pick: antes
    un usuario podía ver "Poisson 45% Local" junto a un pick Visitante."""
    texto_consenso = consenso_svc.texto_probabilidad_consenso(consenso)
    linea = ""
    if texto_consenso:
        linea += f"📐 Probabilidad del pick (consenso): {texto_consenso}\n"
    if poisson.get("ok"):
        pl = round((poisson.get("prob_local") or 0) * 100, 1)
        pe = round((poisson.get("prob_empate") or 0) * 100, 1)
        pv = round((poisson.get("prob_visitante") or 0) * 100, 1)
        if texto_consenso:
            linea += f"   Detalle Poisson (un módulo más): {pl}% | Empate {pe}% | {pv}%\n"
        else:
            linea += f"📐 Estadístico (solo Poisson): {pl}% | Empate {pe}% | {pv}%\n"
        over25 = poisson.get("over25_prob")
        btts = poisson.get("btts_prob")
        if over25 is not None:
            linea += f"Over 2.5: {round(over25*100,1)}% | BTTS: {round((btts or 0)*100,1)}%\n"
    elif not texto_consenso:
        return "📐 Estadístico: Sin datos\n"
    return linea


def _lineas_contexto_historico(resultado_motor: dict) -> str:
    """Agrega el desglose del módulo histórico Dixon-Coles y la tasa base de la liga cuando
    están disponibles en `resultado_motor`, sin alterar el formato principal."""
    extra = ""
    historico = (resultado_motor.get("modulos") or {}).get("historico") or {}
    if historico.get("ok") and historico.get("prob_local") is not None:
        hl = round((historico.get("prob_local") or 0) * 100, 1)
        he = round((historico.get("prob_empate") or 0) * 100, 1)
        hv = round((historico.get("prob_visitante") or 0) * 100, 1)
        extra += f"📚 Histórico DC: Local {hl}% | Empate {he}% | Visitante {hv}%\n"
    evidencia = resultado_motor.get("nivel_evidencia") or {}
    if evidencia.get("codigo") and evidencia["codigo"] != "N0":
        extra += f"📊 Evidencia {evidencia['codigo']}: {evidencia.get('etiqueta', '')}" + chr(10)
    tasa = resultado_motor.get("tasa_base_liga") or {}
    if tasa.get("pct_local") is not None and tasa.get("pct_empate") is not None and tasa.get("pct_visitante") is not None:
        n_partidos = f" ({tasa['partidos']} PJ)" if tasa.get("partidos") else ""
        extra += (
            f"📏 Tasa base liga{n_partidos}: Local {round(tasa['pct_local'], 1)}% | "
            f"Empate {round(tasa['pct_empate'], 1)}% | Visitante {round(tasa['pct_visitante'], 1)}%\n"
        )
    return extra


def formatear_mensaje_con_ia(resultado_motor: dict, combinado: dict, canal: str, grupo_url: str) -> str:
    texto_claude = combinado["texto_claude"]
    poisson = resultado_motor.get("modulos", {}).get("poisson", {})
    forma = resultado_motor.get("modulos", {}).get("forma", {})

    msg = _bloque_datos_desde_claude(texto_claude) + "\n"
    msg += f"\n{SEPARADOR}\n"
    msg += f"🎯 PICK: <b>{combinado['pick_unificado']}</b>\n"
    conf = combinado["confianza_final"]
    msg += f"{_CONF_EMOJI.get(conf, '🟡')} Confianza: {conf} ({combinado['score_consolidado']}/100) | Bankroll: {_BANKROLL.get(conf, '1-2%')}\n"
    msg += f"{SEPARADOR}\n\n"
    msg += _linea_estadistico(resultado_motor.get("consenso"), poisson)
    msg += _lineas_contexto_historico(resultado_motor)
    if forma.get("ok") and forma.get("prob_local") is not None:
        fl = round(forma["prob_local"] * 100, 1)
        fv = round((forma.get("prob_visitante") or 0) * 100, 1)
        msg += f"📊 Forma: {fl}% | {fv}%\n"

    nivel_ia = combinado["nivel_ia"]
    consenso_txt = "✅ Estadístico e IA coinciden" if nivel_ia == "COINCIDEN" else "⚠️ Estadístico e IA divergen" if nivel_ia == "DIVERGEN" else "🔷 Solo estadístico"
    msg += f"🤖 IA: {combinado['pick_claude']} | {consenso_txt}\n"
    msg += _footer(canal, grupo_url)
    return msg


def formatear_mensaje_sin_pronostico(resultado_motor: dict, motivos: list[str], canal: str, grupo_url: str) -> str:
    """Respuesta corta y honesta cuando el bot no tiene base para un pronóstico propio: dice por qué, da la
    frecuencia histórica como REFERENCIA (no como pick) y qué lo habilitaría. Nunca inventa un pick."""
    # Telegram usa parse_mode HTML: un "&" o "<" en un nombre ("Harland & Wolff") rompería el mensaje entero.
    local = html.escape(str(resultado_motor.get("local", "Local")))
    visitante = html.escape(str(resultado_motor.get("visitante", "Visitante")))
    msg = f"🏆 {local} vs {visitante}\n📍 {html.escape(str(resultado_motor.get('liga', '')))}\n\n"
    msg += "⚪ Sin pronóstico propio para este partido.\n"
    for motivo in motivos[:3]:
        msg += f"• {html.escape(motivo)}\n"
    ref = resultado_motor.get("referencia_tasa_base") or {}
    if ref.get("pct_local") is not None:
        donde = "en esta liga" if ref.get("nivel") == "liga" else "en general (esta liga no tiene histórico)"
        n = f", {ref['partidos']} partidos" if ref.get("partidos") else ""
        msg += (
            f"\n📏 Referencia, no pronóstico — {donde}{n}: Local {round(ref['pct_local'], 1)}% | "
            f"Empate {round(ref['pct_empate'], 1)}% | Visitante {round(ref['pct_visitante'], 1)}%\n"
            "No distingue a estos dos equipos.\n"
        )
    msg += "\nSe habilita con cuotas reales del partido o con ambos equipos en el histórico del bot.\n"
    msg += _footer(canal, grupo_url)
    return msg


def formatear_mensaje_free(resultado_motor: dict, canal: str, grupo_url: str) -> str:
    local = resultado_motor.get("local", "Local")
    visitante = resultado_motor.get("visitante", "Visitante")
    liga = resultado_motor.get("liga", "")
    poisson = resultado_motor.get("modulos", {}).get("poisson", {})
    forma = resultado_motor.get("modulos", {}).get("forma", {})
    h2h = resultado_motor.get("modulos", {}).get("h2h")
    odds = resultado_motor.get("modulos", {}).get("odds")

    msg = f"🏆 {local} vs {visitante}\n📍 {liga}\n\nDATOS\n\n"
    msg += f"📈 {local}: {forma.get('score_para_claude', 'Sin datos')}\n" if forma.get("ok") else f"📈 {local}: Sin datos\n"
    msg += f"📈 {visitante}: ver forma reciente\n"

    msg += f"\n📜 H2H:\n{h2h.get('score_para_claude', 'Sin historial directo disponible.') if h2h else 'Sin historial directo disponible.'}\n"
    msg += f"\n💰 {odds.get('score_para_claude', 'Sin odds disponibles') if odds else 'Sin odds disponibles — análisis estadístico puro.'}\n"

    if poisson.get("ok"):
        over25 = poisson.get("over25_prob")
        if over25 is not None:
            msg += f"🥅 Over 2.5: {round(over25*100,1)}% | BTTS: {round((poisson.get('btts_prob') or 0)*100,1)}%\n"
        msg += f"🎯 Marcador esperado: {poisson.get('marcador_probable', 'N/A')}\n"
        rango_local = poisson.get("rango_goles_local")
        rango_visitante = poisson.get("rango_goles_visitante")
        if rango_local and rango_visitante:
            msg += f"⚽ Rango probable: {local} {rango_local} goles | {visitante} {rango_visitante} goles\n"
        rango_total = poisson.get("rango_goles_total")
        if rango_total:
            msg += f"📈 Total de goles probable: {rango_total}\n"

    msg += f"\n{SEPARADOR}\n"
    consenso = resultado_motor.get("consenso", {})
    pick = consenso.get("pick_final") or poisson.get("pick", "Indeterminado")
    conf = consenso.get("confianza_final") or poisson.get("confianza", "BAJA")
    score = consenso.get("score_consenso") if consenso.get("score_consenso") is not None else poisson.get("confianza_score", 0)
    msg += f"🎯 PICK: <b>{pick}</b>\n"
    msg += f"{_CONF_EMOJI.get(conf, '🔴')} Confianza: {conf} ({score}/100) | Bankroll: {_BANKROLL.get(conf, '0.5%')}\n"
    msg += f"{SEPARADOR}\n\n"
    msg += _linea_estadistico(consenso, poisson)
    msg += _lineas_contexto_historico(resultado_motor)
    msg += "\n🔒 Análisis IA disponible en plan Pro\n"
    msg += _footer(canal, grupo_url)
    return msg

