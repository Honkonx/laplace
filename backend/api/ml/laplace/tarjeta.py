"""tarjeta.py — ficha y model card generadas del artefacto (MM-03): nada se escribe a mano, todo sale de lo que el artefacto trae.

`ficha(artefacto)` es un dict sin rutas, sin secretos y sin datos personales (lo expone `GET /api/v1/ml/modelo`); `markdown(ficha, informe)` es la tarjeta que se guarda junto al artefacto.
Dice qué hace el modelo, con qué datos, cómo se midió, qué cubre, qué NO cubre y con qué huellas se puede reproducir.
"""
from __future__ import annotations

import hashlib
import json

from backend.api.ml.laplace import variables


def huella_artefacto(artefacto: dict) -> str:
    """SHA-256 del JSON canónico del artefacto (claves ordenadas): dos entrenamientos con los mismos datos y el mismo código deben dar la misma huella."""
    return hashlib.sha256(json.dumps(artefacto, sort_keys=True, ensure_ascii=False, default=list).encode("utf-8")).hexdigest()


def ficha(artefacto: dict) -> dict:
    ligas = artefacto.get("ligas") or {}
    hiper = artefacto.get("hiper") or {}
    goles = artefacto.get("goles") or {}
    apilador = artefacto.get("apilador_mercado") or {}
    con_tiros = sorted(c for c, i in ligas.items() if (i.get("estado") or {}).get("n_tiros", 0) > 0)
    return {
        "familia": artefacto.get("familia"), "generacion": artefacto.get("generacion"), "fecha_corte": artefacto.get("fecha_corte"), "n_entrenamiento": artefacto.get("n_entrenamiento"),
        "hiperparametros": {k: hiper.get(k) for k in ("k_elo", "alfa", "extras")},
        "variables": variables.variables_usadas(hiper.get("extras", ())), "version_variables": variables.version_variables(hiper.get("extras", ())),
        "ligas_cubiertas": sorted(ligas), "n_ligas": len(ligas), "ligas_con_tiros": con_tiros,
        "pesos_de_respaldo_en": sorted(c for c, i in ligas.items() if i.get("pesos_de_respaldo")),
        "goles": {"validados": [m for m, v in (goles.get("util") or {}).items() if v], "reserva": goles.get("reserva")} if goles else None,
        "apilador_mercado": {"util": apilador.get("util"), "evaluacion": apilador.get("evaluacion")} if apilador else None,
        "linaje": artefacto.get("linaje"),
    }


def markdown(f: dict, informe: dict | None = None, version: str = "") -> str:
    """Model card en Markdown. `informe` (opcional) es el de `evaluar_jerarquico`: métricas de la prueba y comparaciones con significancia."""
    lineas = [f"# Model card — Laplace {version or f.get('generacion') or ''}".strip(), "",
              "> Generada del artefacto: no se edita a mano. **Pronóstico estadístico; no es una recomendación de apuesta ni una certeza.**", "",
              "## Qué es", f"Modelo propio sin IA (Elo + tasas de gol con memoria exponencial → regresión logística multinomial, jerárquico por liga). Familia `{f['familia']}`, generación `{f['generacion']}`.",
              f"Entrenado con {f['n_entrenamiento']} partidos anteriores al día {f['fecha_corte']} (ordinal) de {f['n_ligas']} ligas. Hiperparámetros: {json.dumps(f['hiperparametros'], ensure_ascii=False)}.", "",
              "## Variables", f"`{f['version_variables']}`: " + ", ".join(f["variables"]) + "."]
    if f["ligas_con_tiros"]:
        lineas += [f"Tiros y tiros a puerta: {len(f['ligas_con_tiros'])} ligas ({', '.join(f['ligas_con_tiros'])}). Las demás usan los pesos de la versión sin tiros ({len(f['pesos_de_respaldo_en'])} ligas)."]
    if informe:
        r = informe.get("resumen", {})
        lineas += ["", "## Métricas (prueba posterior al corte; menos es mejor)"]
        for nombre, m in r.items():
            lineas.append(f"- {nombre}: log loss {m.get('log_loss')} · RPS {m.get('rps')} · n={m.get('n')}")
        for nombre, c in (informe.get("comparaciones") or {}).items():
            lineas.append(f"- {nombre}: diferencia {c['diferencia_media']:+.5f} (z={c['z']:.1f}, IC95 [{c['ic95'][0]:+.5f}, {c['ic95'][1]:+.5f}], n={c['n']})")
    if f.get("goles"):
        lineas += ["", "## Mercados de goles", f"Validados contra la tasa base en el último 15 % de cada liga: {', '.join(f['goles']['validados']) or 'ninguno'}. Lo no validado no se muestra."]
    if f.get("apilador_mercado") and f["apilador_mercado"].get("evaluacion"):
        e = f["apilador_mercado"]["evaluacion"]
        lineas += ["", "## Apilado con cuotas", f"Modelo {e['log_loss_modelo']} · mercado {e['log_loss_mercado']} · apilado {e['log_loss_apilado']} (n={e['n_prueba']}); se ofrece aparte solo si le gana al mercado."]
    lineas += ["", "## Límites", "- No pronostica equipos con menos de 5 partidos de historia ni ligas fuera de la cobertura: responde con el respaldo Dixon-Coles o sin pronóstico, y lo dice.",
               "- No ve lesiones, alineaciones ni contexto; solo goles, resultados y, donde existen, tiros.", "- Las probabilidades son estimaciones; la «confianza» mide dispersión, no certeza."]
    if f.get("linaje"):
        lineas += ["", "## Reproducibilidad", *(f"- {k}: `{v}`" for k, v in f["linaje"].items())]
    return "\n".join(lineas) + "\n"
