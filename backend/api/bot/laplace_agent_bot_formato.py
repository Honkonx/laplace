"""bot/laplace_agent_bot_formato.py — constantes, menú de comandos y formato de mensajes del bot del agente."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update


log = logging.getLogger("laplace.agent_telegram")


TZ_CHILE = ZoneInfo("America/Santiago")
MAX_MENSAJE = 3800
LIMITE_PARTIDOS = 20


AVISO_ESTIMACION = "Es una estimación estadística, no una certeza."


COMANDOS_PUBLICOS = [
    ("partidos", "Partidos de hoy o mañana (opcional: liga o equipo)"),
    ("predecir", "Predicción de un partido: /predecir River vs Boca"),
    ("top", "Top Picks publicados de hoy"),
    ("ligas", "Ligas cubiertas por el bot"),
    ("ia", "Pregunta al agente con IA"),
    ("simular", "Simular una liga (planes pro y max): /simular premier"),
    ("estado", "Tus tareas y memorias"),
    ("nuevo", "Empezar una conversación nueva"),
    ("sesiones", "Ver tus conversaciones guardadas"),
    ("incognito", "No guardar esta conversación (on/off)"),
    ("olvidar", "Borrar todo lo guardado de ti: /olvidar confirmo"),
    ("retomar", "Retomar donde lo dejaste: /retomar o /retomar <número>"),
    ("ayuda", "Qué puedo hacer"),
]
COMANDOS_ADMIN = [
    ("panel", "Estado del sistema (admin)"),
    ("fuentes", "Salud de las fuentes de datos (admin)"),
    ("resultados", "Verificar resultados pendientes (admin)"),
    ("toppicks", "Generar Top Picks sin publicar (admin)"),
    ("publicar", "Publicar Top Picks: /publicar confirmo (admin)"),
    ("marcador", "Rendimiento del modelo y del bot por liga (admin)"),
    ("aprobaciones", "Aprobaciones pendientes (admin)"),
    ("decidir", "Decidir una aprobación (admin)"),
]


async def _enviar(update: Update, texto: str) -> None:
    """Envía respetando el límite de Telegram, cortando por saltos de línea."""
    texto = (texto or "").strip() or "Sin contenido."
    while texto:
        if len(texto) <= MAX_MENSAJE:
            await update.effective_message.reply_text(texto)
            return
        corte = texto.rfind("\n", 0, MAX_MENSAJE)
        corte = corte if corte > MAX_MENSAJE // 2 else MAX_MENSAJE
        await update.effective_message.reply_text(texto[:corte])
        texto = texto[corte:].lstrip("\n")


def _fecha_desde(texto: str | None) -> str:
    """'hoy' (defecto), 'mañana' o YYYY-MM-DD, en hora de Chile."""
    hoy = datetime.now(TZ_CHILE).date()
    valor = (texto or "hoy").strip().lower()
    if valor in {"mañana", "manana", "tomorrow"}:
        return (hoy + timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return valor
    return hoy.isoformat()


def _es_token_fecha(token: str) -> bool:
    return token.lower() in {"hoy", "mañana", "manana", "today", "tomorrow"} or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", token))


def _hora_corta(valor: object) -> str:
    """HH:MM desde el formato compacto de la cascada (`yyyymmddHHMM[SS]`) o desde un ISO (`...THH:MM...`)."""
    texto = str(valor or "")
    compacto = re.fullmatch(r"\d{8}(\d{2})(\d{2})(?:\d{2})?", texto)
    if compacto:
        return f"{compacto.group(1)}:{compacto.group(2)}"
    iso = re.search(r"[T ](\d{2}):(\d{2})", texto)
    return f"{iso.group(1)}:{iso.group(2)}" if iso else ""


def formatear_partidos(partidos: list[dict], fecha: str) -> str:
    if not partidos:
        return f"No encontré partidos para {fecha}."
    por_liga: dict[str, list[dict]] = {}
    for partido in partidos[:LIMITE_PARTIDOS]:
        por_liga.setdefault(str(partido.get("liga") or "Otras competiciones"), []).append(partido)
    lineas = [f"⚽ Partidos {fecha} ({len(partidos)} encontrados)"]
    for liga, items in por_liga.items():
        lineas.append(f"\n{liga}")
        for p in items:
            hora = _hora_corta(p.get("fecha"))
            lineas.append(f"• {hora + ' ' if hora else ''}{p.get('local', '?')} vs {p.get('visitante', '?')}")
    if len(partidos) > LIMITE_PARTIDOS:
        lineas.append(f"\n…y {len(partidos) - LIMITE_PARTIDOS} más. Filtra con /partidos <liga o equipo>.")
    lineas.append("\nPara una predicción: /predecir Local vs Visitante")
    return "\n".join(lineas)


def formatear_prediccion(partido: dict, resumen: dict) -> str:
    cabecera = f"⚽ {partido.get('local', '?')} vs {partido.get('visitante', '?')}"
    if partido.get("liga"):
        cabecera += f"\n{partido['liga']}"
    if not resumen or not resumen.get("pick"):
        texto = f"{cabecera}\n\nSin pronóstico propio para este partido (es un resultado válido, no un error)."
        for motivo in (resumen or {}).get("motivos_sin_pronostico") or []:
            texto += f"\n• {motivo}"
        ref = (resumen or {}).get("referencia_tasa_base") or {}
        if ref.get("pct_local") is not None:
            donde = "esta liga" if ref.get("nivel") == "liga" else "promedio general"
            texto += (f"\n\nReferencia, no pronóstico ({donde}): local {ref.get('pct_local')}% · empate {ref.get('pct_empate')}% · "
                      f"visitante {ref.get('pct_visitante')}%. No distingue a estos dos equipos.")
        return texto
    prob = resumen.get("prob_ponderada_pct") or {}
    lineas = [cabecera, ""]
    if prob:
        lineas.append(
            f"Probabilidad estimada: {partido.get('local', 'Local')} {prob.get('local', '?')}% · "
            f"Empate {prob.get('empate', '?')}% · {partido.get('visitante', 'Visitante')} {prob.get('visitante', '?')}%"
        )
    lineas.append(f"Resultado más probable: {resumen['pick']} · confianza {resumen.get('confianza', 'n/d')}")
    modelo = resumen.get("modelo_laplace")
    if modelo:
        mp, mg = modelo["p1x2"], modelo.get("goles_esperados")
        lineas.append(f"Modelo Laplace{' (' + modelo['etiqueta'] + ')' if modelo.get('etiqueta') and modelo['etiqueta'] != 'propio' else ''}: {round(mp['local'] * 100)}% · {round(mp['empate'] * 100)}% · {round(mp['visitante'] * 100)}%"
                      + (f" — goles esperados {mg['local']}-{mg['visitante']}, marcador probable {modelo['marcador_mas_probable']}" if mg else ""))
    modulos = ", ".join(resumen.get("modulos_usados") or []) or "n/d"
    lineas.append(f"Modelos usados: {modulos}")
    base = resumen.get("tasa_base_liga")
    if base:
        lineas.append(
            f"Tasa base de la liga ({base.get('partidos')} partidos): local {base.get('pct_local')}% · "
            f"empate {base.get('pct_empate')}% · visitante {base.get('pct_visitante')}%"
        )
    lineas += ["", AVISO_ESTIMACION]
    return "\n".join(lineas)


def _separar_equipos(texto: str) -> tuple[str, str] | None:
    partes = re.split(r"\s+(?:vs\.?|v|contra|-)\s+", texto.strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(partes) != 2 or not partes[0].strip() or not partes[1].strip():
        return None
    return partes[0].strip(), partes[1].strip()


def _coincide(nombre_pedido: str, nombre_partido: str) -> bool:
    pedido, real = nombre_pedido.casefold(), (nombre_partido or "").casefold()
    # Un nombre vacío no coincide con nada: `"" in pedido` es verdadero y un partido sin nombre habría casado con cualquier equipo.
    return bool(pedido) and bool(real) and (pedido in real or real in pedido)
