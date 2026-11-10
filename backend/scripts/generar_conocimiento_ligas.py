"""backend/scripts/generar_conocimiento_ligas.py — base de conocimiento por liga, calculada.

Convierte el histórico real (`backend/data/datos/football-data/`) en entradas de
`knowledge/sports/ligas-estadisticas.json`, que `services/agent_runtime.py::
sincronizar_conocimiento_json` ya carga en `agent_knowledge`. Cada entrada es un hecho medido
(no una opinión escrita a mano) con su muestra y su fuente, para que el agente y los prompts de
IA razonen con tasas base reales de cada liga en vez de intuiciones genéricas.

Solo entra la ventana de las últimas 3 temporadas completas de cada liga (las tasas de empate y
de goles cambian con los años) y se declara el tamaño de muestra en el propio texto.

Uso:  python backend/scripts/generar_conocimiento_ligas.py
Idempotente: reescribe el mismo archivo con los datos actuales.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import datos, mercado  # noqa: E402

DESTINO = REPO / "backend" / "knowledge" / "sports" / "ligas-estadisticas.json"
TEMPORADAS_VENTANA = 3
MIN_PARTIDOS = 300
TRAMOS_FAVORITO = ((1.0, 1.5, "favorito muy fuerte (cuota < 1.50)"), (1.5, 2.0, "favorito claro (1.50-2.00)"),
                   (2.0, 2.6, "favorito moderado (2.00-2.60)"))


def _pct(parte: int, total: int) -> float:
    return round(100 * parte / total, 1) if total else 0.0


def _ventana(partidos: list[dict]) -> list[dict]:
    """Partidos de las últimas `TEMPORADAS_VENTANA` temporadas COMPLETAS. La última temporada
    del histórico se descarta si va incompleta (menos del 90% de partidos que la anterior); las
    demás se aceptan tal cual porque las ligas cambian de tamaño (Ligue 1: 380 → 306 partidos)."""
    conteo: dict[str, int] = {}
    for p in partidos:
        conteo[p["temporada"]] = conteo.get(p["temporada"], 0) + 1
    temporadas = sorted(conteo)
    if len(temporadas) >= 2 and conteo[temporadas[-1]] < 0.9 * conteo[temporadas[-2]]:
        temporadas = temporadas[:-1]
    elegidas = set(temporadas[-TEMPORADAS_VENTANA:])
    return [p for p in partidos if p["temporada"] in elegidas]


def _favorito(p: dict) -> tuple[str, float] | None:
    c = p.get("ci_pinnacle") or p.get("ci_prom") or p.get("ap_prom")
    if not c:
        return None
    probs = mercado.quitar_margen_shin(*c)
    lado = "H" if probs[0] >= probs[2] else "A"
    return lado, c[0] if lado == "H" else c[2]


def entrada_liga(codigo: str, partidos: list[dict], hoy: int) -> dict | None:
    muestra = _ventana(partidos)
    n = len(muestra)
    # Se mide la antigüedad con el último partido de la LIGA (no de la ventana: la ventana puede dejar fuera
    # la temporada final por incompleta). Más de 3 años describe otra época y no se publica; entre 1 y 3
    # años se publica con la fecha de los datos explícita (ligas cuyas fuentes gratuitas llegan a 2024).
    ultimo_dia = max(p["dia"] for p in partidos)
    if n < MIN_PARTIDOS or hoy - ultimo_dia > 3 * 366:
        return None
    ultimo = max(p["fecha"] for p in partidos).isoformat()
    aviso_antiguedad = (
        f"Datos hasta {ultimo}: más de un año sin actualizar, tómalo como referencia histórica. "
        if hoy - ultimo_dia > 366 else ""
    )
    goles = sum(p["gl"] + p["gv"] for p in muestra)
    local = sum(p["resultado"] == "H" for p in muestra)
    empate = sum(p["resultado"] == "D" for p in muestra)
    visita = n - local - empate
    over25 = sum(p["gl"] + p["gv"] > 2 for p in muestra)
    btts = sum(p["gl"] > 0 and p["gv"] > 0 for p in muestra)
    ventaja = (sum(p["gl"] for p in muestra) - sum(p["gv"] for p in muestra)) / n
    temporadas = sorted({p["temporada"] for p in muestra})

    partes_favorito = []
    for bajo, alto, etiqueta in TRAMOS_FAVORITO:
        casos = [(p, f) for p in muestra if (f := _favorito(p)) and bajo <= f[1] < alto]
        if len(casos) >= 40:
            gana = sum(p["resultado"] == f[0] for p, f in casos)
            partes_favorito.append(f"{etiqueta}: gana {_pct(gana, len(casos))}% ({len(casos)} partidos)")

    nombre = muestra[-1]["liga_nombre"]
    texto = (
        f"{nombre} ({codigo}), temporadas {temporadas[0]}–{temporadas[-1]}, {n} partidos: "
        f"promedio {goles / n:.2f} goles por partido; gana el local {_pct(local, n)}%, empate "
        f"{_pct(empate, n)}%, gana el visitante {_pct(visita, n)}%; más de 2.5 goles en "
        f"{_pct(over25, n)}% y ambos anotan en {_pct(btts, n)}%; el local anota en promedio "
        f"{ventaja:+.2f} goles más que el visitante. "
        + ("Cuando el mercado marca " + "; ".join(partes_favorito) + ". " if partes_favorito else "")
        + aviso_antiguedad
        + "Tasas base históricas: descripciones de lo ocurrido, no una promesa sobre el próximo partido."
    )
    return {
        "namespace": "futbol", "topic_key": f"liga-{codigo}-estadisticas", "content": texto,
        "source": "football-data.co.uk, calculado por generar_conocimiento_ligas.py",
        "metadata": {
            "liga_codigo": codigo, "partidos": n, "temporadas": temporadas,
            "pct_local": _pct(local, n), "pct_empate": _pct(empate, n), "pct_visitante": _pct(visita, n),
            "goles_por_partido": round(goles / n, 3), "pct_over25": _pct(over25, n), "pct_btts": _pct(btts, n),
            "datos_hasta": ultimo,
        },
    }


def main() -> None:
    partidos = datos.cargar_partidos()
    hoy = max(p["dia"] for p in partidos)
    por_liga = datos.agrupar_por_liga(partidos)
    entradas = [e for codigo, ps in sorted(por_liga.items()) if (e := entrada_liga(codigo, ps, hoy))]
    fecha_corte = max(p["fecha"] for p in partidos).isoformat()
    entradas.append({
        "namespace": "futbol", "topic_key": "estadisticas-ligas-procedencia",
        "content": (
            f"Las entradas liga-*-estadisticas se calculan con datos reales de football-data.co.uk "
            f"(corte de datos: {fecha_corte}; archivo generado: {date.today().isoformat()}), ventana de las "
            f"últimas {TEMPORADAS_VENTANA} temporadas completas de cada liga. Cubren {len(entradas)} ligas "
            "de Europa, Sudamérica, Norteamérica y Asia disponibles en la fuente. No incluyen competiciones "
            "que la fuente no publica, como Chile, Colombia, Arabia Saudita o Corea."),
        "source": "generar_conocimiento_ligas.py",
        "metadata": {
            "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "corte_datos": fecha_corte,
            "ligas_cubiertas": len(entradas),
        },
    })
    DESTINO.write_text(json.dumps(entradas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entradas) - 1} ligas -> {DESTINO.relative_to(REPO)}")


if __name__ == "__main__":
    main()
