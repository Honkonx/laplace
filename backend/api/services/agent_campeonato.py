"""services/agent_campeonato.py — seguir un campeonato desde el chat: tabla propia, última jornada y, solo para planes pro/max y administradores, la simulación (MS-5 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Todo sale de los resultados propios (`simulador_propio.preparar`) y del modelo (`simulador_propio.simular`); nada lo inventa una IA. La liga es la que menciona el mensaje («tabla de la Premier») o, si no menciona ninguna, las
que la persona sigue («cómo van mis ligas»). Una liga sin datos suficientes dice por qué en vez de dar una tabla falsa. La simulación respeta `usuarios_repo.acceso_simulador` (regla `simulaciones-internas-y-publicas.md`).
"""
from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from backend.api.db import usuarios_repo
from backend.api.services import agent_seguimientos, simulador_propio

log = logging.getLogger("laplace.agent_campeonato")
MAX_LIGAS = 3
FILAS_TABLA = 5
PARTIDOS_JORNADA = 5
N_SIMULACIONES = 1000
AVISO_SIMULACION = "La simulación (campeón, copa y descenso) es de los planes pro y max."


def liga_explicita(texto_normalizado: str) -> str | None:
    """La liga que el mensaje nombra DE VERDAD. «la liga» a secas es ambigua («clasificación de la liga» puede ser cualquiera): solo cuenta si dice LaLiga, liga española o España."""
    slug = simulador_propio.liga_de_texto(texto_normalizado)
    if slug == "laliga" and not re.search(r"\b(?:laliga|liga espanola|espana)\b", texto_normalizado):
        return None
    return slug


def ligas_del_mensaje_o_seguidas(db: Session, user_id: str, texto_normalizado: str) -> list[str]:
    """Los `slug` de las ligas que menciona el mensaje o, si no menciona ninguna, las que sigue la persona (las que el simulador conoce)."""
    mencionada = liga_explicita(texto_normalizado)
    if mencionada:
        return [mencionada]
    slugs: list[str] = []
    for nombre in agent_seguimientos.seguidos(db, user_id)["ligas"]:
        slug = simulador_propio.liga_de_texto(simulador_propio._normalizar(nombre))  # noqa: SLF001
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs[:MAX_LIGAS]


def _ultima_jornada(codigo: str, temporada: str) -> str:
    try:
        todos = [p for p in simulador_propio._partidos() if p["liga"] == codigo and p["temporada"] == temporada]  # noqa: SLF001
        if not todos:
            return ""
        ultimo = max(p["dia"] for p in todos)
        del_dia = sorted((p for p in todos if p["dia"] == ultimo), key=lambda p: p["local"])[:PARTIDOS_JORNADA]
        return f"Último día jugado ({date.fromordinal(ultimo).isoformat()}): " + "; ".join(f"{p['local']} {p['gl']}-{p['gv']} {p['visitante']}" for p in del_dia)
    except Exception:  # noqa: BLE001 — accesorio de la respuesta
        log.warning("no se pudo armar la última jornada de %s", codigo, exc_info=True)
        return ""


def _una(slug: str, con_simulacion: bool) -> str:
    codigo, nombre = simulador_propio.SLUGS[slug]
    base = simulador_propio.preparar(codigo)
    if not base["ok"]:
        return f"{nombre}: {base['razon']}"
    orden = sorted(base["tabla"], key=lambda f: (-f["pts"], -(f["gf"] - f["gc"]), -f["gf"], f["equipo"]))[:FILAS_TABLA]
    filas = [f"{i}. {f['equipo']} {f['pts']} pts (PJ {f['pj']}, DG {f['gf'] - f['gc']:+d})" for i, f in enumerate(orden, 1)]
    lineas = [f"{nombre} {base['temporada']} · datos hasta {base['datos_hasta']} · {base['partidos_jugados']} jugados, {len(base['pendientes'])} por jugar", *filas]
    jornada = _ultima_jornada(codigo, base["temporada"])
    if jornada:
        lineas.append(jornada)
    if con_simulacion:
        lineas.append(simulador_propio.texto_resumen(simulador_propio.simular(slug, n_sim=N_SIMULACIONES)))
    return "\n".join(lineas)


def resumen(db: Session, user_id: str, texto_normalizado: str, es_admin: bool = False) -> str:
    """El resumen de la liga mencionada o de las que sigue la persona. Nunca lanza: ante un fallo lo dice."""
    try:
        slugs = ligas_del_mensaje_o_seguidas(db, user_id, texto_normalizado)
        if not slugs:
            return "No sé de qué liga: dime «tabla de la Premier» o sigue una con «sigue la Premier League» y te cuento cómo va."
        permitido = es_admin or usuarios_repo.acceso_simulador(db, user_id)["permitido"]
        texto = "\n\n".join(_una(slug, permitido) for slug in slugs)
        return texto if permitido else f"{texto}\n{AVISO_SIMULACION}"
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("no se pudo armar el resumen de la liga")
        return "No pude armar el resumen de la liga ahora. Inténtalo de nuevo en un momento."
