"""bot/ligas.py — Filtro y prioridad de ligas para el menú de /juegos.

Port exacto de `LIGAS_EXCLUIR_LOWER`/`LIGAS_PRIORITARIAS_LOWER` de WF-A (`Crear Botones Ligas`,
wfa-022) — mismo criterio que usa `services/gateway.py` para descartar ligas amateur/africanas.
"""
from __future__ import annotations

from backend.api.services import ligas_ident

LIGAS_EXCLUIR_LOWER = {
    "ligue 1 congo", "ligue 1 senegal", "ligue 1 mali", "ligue 1 ivory coast",
    "ligue 1 cameroun", "ligue 1 morocco", "ligue 1 algerie", "ligue 1 tunisie",
    "ligue 1 gabon", "ligue 1 burkina faso", "ligue 1 guinea",
    "ligue professionnelle 1", "botola pro",
    "premier league tanzania", "premier league kenya", "premier league ethiopia",
    "premier league nigeria", "premier league ghana", "premier league zambia",
    "premier league uganda", "premier league zimbabwe", "premier league rwanda",
    "premier league sierra leone", "premier league liberia", "premier league malawi",
    "national super league", "national division", "super league south africa",
    "psl", "premier soccer league", "ligue africaine",
    "copa peru", "liga distrital", "liga regional", "amateur", "reservas", "reserve league",
    "u20 league", "youth league local",
}

LIGAS_PRIORITARIAS_LOWER = [
    "premier league", "laliga", "la liga", "serie a", "bundesliga", "ligue 1",
    "champions league", "europa league", "conference league",
    "eredivisie", "championship", "primeira liga", "super lig", "saudi pro",
    "mls", "liga mx", "brasileirao", "superliga argentina", "libertadores", "sudamericana",
    "j1 league", "ligue 2", "serie b", "segunda division", "2. bundesliga",
    "eliteserien", "allsvenskan", "primera a", "primera division", "copa argentina",
    "copa chile", "copa colombia", "scottish", "la liga2",
]


def slug_liga(nombre: str, pais: str | None = None) -> str:
    """Identificador de la competición (nombre + país): una sola regla para el menú, el guardado y el catálogo (`services/ligas_ident.py`)."""
    from backend.api.services import ligas_ident

    return ligas_ident.slug_competicion(nombre, pais)


def slug_de_stage(stage: dict) -> str:
    return slug_liga(stage.get("Snm") or stage.get("CompN") or "Liga", stage.get("Cnm"))


def es_prioritaria(nombre: str) -> bool:
    bajo = nombre.lower()
    return any(l in bajo for l in LIGAS_PRIORITARIAS_LOWER)


def _evento_cubierto(stage: dict, ev: dict) -> bool:
    """El partido tiene un modelo histórico válido (liga y ambos equipos resueltos): el bot puede darle pronóstico
    propio aunque ninguna API devuelva cuotas. Auditoría 2026-10-09: sin este filtro el menú ofrecía como
    'prioritarias' ligas homónimas de otros países (Ligue 1 de Argelia, Premier League de Ghana) sin cobertura."""
    from backend.api.services import modelo_historico

    try:
        return bool(modelo_historico.validar_historico({
            "liga": stage.get("Snm") or stage.get("CompN") or "", "pais": stage.get("Cnm") or "",
            "local": (ev.get("T1") or [{}])[0].get("Nm", ""), "visitante": (ev.get("T2") or [{}])[0].get("Nm", ""),
        })[0])
    except Exception:  # noqa: BLE001 — un fallo del histórico nunca debe tumbar el menú
        return False


def ligas_con_partidos(stages: list[dict], solo_prioritarias: bool = True, maximo: int = 12) -> list[dict]:
    """Agrupa `stages` (formato LiveScore6/gateway) en ligas con partidos `NS` (no iniciados),
    excluyendo `LIGAS_EXCLUIR_LOWER`. Las ligas con partidos que el bot sabe pronosticar (`cubiertos`) van primero;
    una liga solo es 'prioritaria' si su nombre está en la lista """
    ligas_map: dict[str, dict] = {}
    for stage in stages:
        nombre = (stage.get("Snm") or stage.get("CompN") or "Liga").strip()
        bajo = nombre.lower()
        if bajo in LIGAS_EXCLUIR_LOWER:
            continue
        pendientes = [ev for ev in stage.get("Events", []) if ev.get("Eps") == "NS"]
        if not pendientes:
            continue
        slug = slug_de_stage(stage)
        entrada = ligas_map.setdefault(slug, {
            "nombre": ligas_ident.nombre_visible(nombre, stage.get("Cnm")), "partidos": 0, "slug": slug, "cubiertos": 0, "paises": [],
            "prioritaria": es_prioritaria(nombre),
        })
        entrada["partidos"] += len(pendientes)
        entrada["cubiertos"] += sum(_evento_cubierto(stage, ev) for ev in pendientes)
        pais = (stage.get("Cnm") or "").strip()
        if pais and pais not in entrada["paises"]:
            entrada["paises"].append(pais)
        if entrada["cubiertos"] and es_prioritaria(nombre):
            entrada["prioritaria"] = True

    ligas = sorted(ligas_map.values(), key=lambda l: (l["cubiertos"] > 0, l["prioritaria"], l["cubiertos"], l["partidos"]), reverse=True)
    if solo_prioritarias and any(l["prioritaria"] or l["cubiertos"] for l in ligas):
        ligas = [l for l in ligas if l["prioritaria"] or l["cubiertos"]]
    return ligas[:maximo]
