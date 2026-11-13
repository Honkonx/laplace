"""services/agent_tools_extra.py — herramientas de lectura nuevas del agente (MA-33): resultados recientes de un equipo y comparación de perfiles.

Ambas son de solo lectura, con esquema cerrado (un nombre de equipo, tope de 10 filas) y sin red ni IA: salen de la base local y del conocimiento histórico. Devuelven `texto` listo para el chat
y `data` estructurada; no inventan nada: si no hay filas lo dicen.
"""
from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.api.models.partidos import ResultadoPartido
from backend.api.services import conocimiento_equipos, conocimiento_texto

MAX_RESULTADOS = 10
_RX_RESULTADOS = re.compile(r"\b(?:ultimos?\s+)?resultados?\s+(?:recientes?\s+)?(?:de|del|de la)\s+(.+?)\s*$")
_RX_COMPARAR = re.compile(r"\bcompar\w*\s+(?:el\s+|la\s+)?(?:perfil|forma|rendimiento|estadisticas)\s+(?:de\s+|del\s+)?(.+?)\s+(?:y|con|vs\.?|contra)\s+(?:el\s+|la\s+)?(.+?)\s*$")


def equipo_de_resultados(texto_normalizado: str) -> str | None:
    """«ultimos resultados del betis» → «betis»; None si no es esa consulta."""
    m = _RX_RESULTADOS.search(texto_normalizado.strip(" ?!."))
    return re.sub(r"^(?:el|la|los|las)\s+", "", m.group(1)).strip() if m else None


def equipos_a_comparar(texto_normalizado: str) -> tuple[str, str] | None:
    m = _RX_COMPARAR.search(texto_normalizado.strip(" ?!."))
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def resultados_recientes(db: Session, equipo: str, limite: int = 5) -> dict:
    """Últimos partidos terminados del equipo según la base local (coincidencia por nombre, sin distinguir mayúsculas)."""
    nombre = equipo.strip()
    if len(nombre) < 3 or len(nombre) > 60:
        return {"ok": False, "tool": "sports.recent_results", "estado": "equipo_invalido", "texto": "Dime el nombre del equipo (3 a 60 letras), por ejemplo «últimos resultados del Betis»."}
    patron = f"%{nombre.replace('%', '').replace('_', '')}%"
    filas = (db.query(ResultadoPartido).filter(ResultadoPartido.goles_local.is_not(None), ResultadoPartido.goles_visitante.is_not(None),
                                              or_(ResultadoPartido.local.ilike(patron), ResultadoPartido.visitante.ilike(patron)))
             .order_by(ResultadoPartido.fecha_partido.desc()).limit(max(1, min(limite, MAX_RESULTADOS))).all())
    if not filas:
        return {"ok": True, "tool": "sports.recent_results", "estado": "sin_datos", "data": [], "texto": f"No tengo resultados guardados de «{nombre}» todavía."}
    data = [{"fecha": f.fecha_partido, "local": f.local, "visitante": f.visitante, "marcador": f"{f.goles_local}-{f.goles_visitante}", "liga": f.liga} for f in filas]
    lineas = [f"• {d['fecha']}: {d['local']} {d['marcador']} {d['visitante']}" for d in data]
    return {"ok": True, "tool": "sports.recent_results", "estado": "ok", "data": data, "texto": f"Últimos resultados de {nombre} (de mi base local):\n" + "\n".join(lineas)}


def comparar_perfiles(a: str, b: str) -> dict:
    """Perfiles de dos equipos lado a lado (forma, goles, local/visitante) del conocimiento histórico; no pronostica quién gana."""
    pa, pb = conocimiento_equipos.perfil_equipo(a, None), conocimiento_equipos.perfil_equipo(b, None)
    texto = f"{conocimiento_texto.texto_equipo(pa)}\n\n{conocimiento_texto.texto_equipo(pb)}\n\nEsto compara perfiles; para el pronóstico del partido pídeme «analiza {a} vs {b}»."
    return {"ok": True, "tool": "knowledge.compare_teams", "estado": "ok" if pa.get("estado") == "ok" and pb.get("estado") == "ok" else "parcial", "data": {"a": pa, "b": pb}, "texto": texto}
