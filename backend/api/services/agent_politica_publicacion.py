"""agent_politica_publicacion.py — cuándo el agente publica, cuándo pide aprobación y cuándo no publica. El MODELO Y EL BOT SOLO PRONOSTICAN: esta política es del agente.

Tres decisiones, siempre con sus motivos:
- `no_publicar`: no hay picks válidos, o algún pick no llega al umbral de probabilidad, o es de baja confianza. Publicar sería llenar el canal.
- `publicar_con_aprobacion` (la decisión por defecto): hay picks válidos; un administrador confirma (`/publicar confirmo`). Mientras no haya evidencia en vivo, esta es la única salida posible.
- `publicar_solo`: SOLO si el administrador lo habilitó (`AGENTE_PUBLICA_SOLO=1`) Y el laboratorio acumuló evidencia en vivo suficiente (>= `EVIDENCIA_MINIMA_PUBLICAR_SOLO` pronósticos del
  motor ya jugados) Y los picks cumplen los umbrales. Nunca es el valor por defecto: la regla de evidencia (`evidencia-historica-antes-de-promover.md`) exige 200 casos en vivo.
Función pura: no consulta nada ni publica; quien la usa le pasa los picks y la evidencia.
"""
from __future__ import annotations

EVIDENCIA_MINIMA_PUBLICAR_SOLO = 200
PROB_MINIMA_PICK = 0.50


def evaluar(resultado_top_picks: dict, evidencia_en_vivo: int = 0, publica_solo_habilitado: bool = False) -> dict:
    """Decisión para el resultado de `top_picks.generar_top_picks_dia` (`picks`, `sin_picks_validos`, `baja_confianza`)."""
    picks = resultado_top_picks.get("picks") or []
    motivos: list[str] = []
    if resultado_top_picks.get("sin_candidatos") or resultado_top_picks.get("sin_picks_validos") or not picks:
        return {"decision": "no_publicar", "motivos": ["no hay picks válidos hoy"], "evidencia_en_vivo": evidencia_en_vivo}
    if resultado_top_picks.get("baja_confianza"):
        motivos.append("la confianza mínima del lote es baja")
    flojos = [p for p in picks if _prob(p) < PROB_MINIMA_PICK]
    if flojos:
        motivos.append(f"{len(flojos)} pick(s) con probabilidad por debajo de {round(PROB_MINIMA_PICK * 100)}%")
    if motivos:
        return {"decision": "no_publicar", "motivos": motivos, "evidencia_en_vivo": evidencia_en_vivo}
    if not publica_solo_habilitado:
        return {"decision": "publicar_con_aprobacion", "motivos": ["la publicación automática no está habilitada: confirma un administrador"], "evidencia_en_vivo": evidencia_en_vivo}
    if evidencia_en_vivo < EVIDENCIA_MINIMA_PUBLICAR_SOLO:
        return {"decision": "publicar_con_aprobacion", "evidencia_en_vivo": evidencia_en_vivo,
                "motivos": [f"falta evidencia en vivo: {evidencia_en_vivo} de {EVIDENCIA_MINIMA_PUBLICAR_SOLO} pronósticos jugados"]}
    return {"decision": "publicar_solo", "motivos": ["habilitado por el administrador, con evidencia en vivo suficiente y picks sobre el umbral"], "evidencia_en_vivo": evidencia_en_vivo}


def _prob(pick: dict) -> float:
    """Probabilidad del resultado más probable del consenso del pick (0..1); sin dato no se inventa un rechazo: lo deciden las demás reglas."""
    consenso = pick.get("prob_consenso")
    if isinstance(consenso, dict):
        valores = [consenso.get(k) for k in ("local", "empate", "visitante") if isinstance(consenso.get(k), (int, float))]
        if valores:
            m = max(valores)
            return float(m) / 100.0 if m > 1 else float(m)
    return 1.0
