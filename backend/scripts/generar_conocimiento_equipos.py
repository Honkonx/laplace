"""backend/scripts/generar_conocimiento_equipos.py — perfiles de equipo calculados del histórico real.

Lee el maestro `backend/data/datos/football-data/partidos.csv.gz` y escribe un archivo por liga
doméstica, `knowledge/sports/equipos-<codigo>.json`, con una entrada por equipo activo:

- `namespace` = `futbol`, `topic_key` = `equipo-<CODIGO>-<slug>`.
- `content`: texto en español con solo hechos medidos (nada opinado).
- `metadata`: la misma información estructurada (la consume `services/conocimiento_equipos.py`).

Ventanas (todas relativas al ÚLTIMO partido registrado de la liga, no a la fecha de hoy, para que el
archivo sea determinista y una liga con datos viejos no quede vacía): últimos 12 meses y últimas 3
temporadas de esa liga (la actual incluida aunque vaya a medias). Solo cuentan partidos de la liga
doméstica; las copas (Champions, Europa League, Libertadores, Sudamericana) no generan perfiles.
Un equipo entra si jugó al menos un partido en los últimos 12 meses de su liga. Un club que subió o
bajó de división puede tener un perfil en cada categoría cubierta.

Las entradas NO se cargan en la tabla `agent_knowledge` (ver `agent_knowledge._archivos_conocimiento`):
son miles de filas que solo se consultan por equipo; el servicio las lee bajo demanda.

Uso:  python backend/scripts/generar_conocimiento_equipos.py            (regenera todo)
      python backend/scripts/generar_conocimiento_equipos.py --liga CHL1  (una sola liga)
Idempotente: con los mismos datos reescribe exactamente los mismos bytes. Solo escribe en
`knowledge/sports/equipos-*.json` y no toca la base de datos.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUTA_MAESTRO = REPO / "backend" / "data" / "datos" / "football-data" / "partidos.csv.gz"
DESTINO = REPO / "backend" / "knowledge" / "sports"
COPAS = frozenset({"CLI", "CSU", "UCL", "UEL"})
DIAS_VENTANA = 365
TEMPORADAS_VENTANA = 3
MIN_PARTIDOS_EXTRA = 5
FUENTE = "backend/data/partidos.csv.gz, calculado por generar_conocimiento_equipos.py"
_EXTRAS = (("tiros", "tiros_local", "tiros_visit"), ("tiros_arco", "tiros_arco_local", "tiros_arco_visit"),
           ("corners", "corners_local", "corners_visit"), ("amarillas", "amarillas_local", "amarillas_visit"),
           ("rojas", "rojas_local", "rojas_visit"))


def slug(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", plano)).strip("-") or "equipo"


def _num(texto: str) -> float | None:
    try:
        return float(texto) if texto != "" else None
    except ValueError:
        return None


def leer_partidos(ruta: Path = RUTA_MAESTRO) -> list[dict]:
    """Partidos con marcador de ligas domésticas, con las columnas extra (tiros, córners, tarjetas)."""
    partidos = []
    with io.TextIOWrapper(gzip.open(ruta, "rb"), encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            if fila["liga_codigo"] in COPAS:
                continue
            gl, gv = _num(fila["goles_local"]), _num(fila["goles_visitante"])
            try:
                fecha = date.fromisoformat(fila["fecha"])
            except ValueError:
                continue
            if gl is None or gv is None:
                continue
            p = {"liga": fila["liga_codigo"], "liga_nombre": fila["liga_nombre"], "pais": fila["pais"],
                 "temporada": fila["temporada"], "fecha": fecha, "gl": int(gl), "gv": int(gv),
                 "local": fila["local_canon"] or fila["local"], "visitante": fila["visitante_canon"] or fila["visitante"]}
            for nombre, col_l, col_v in _EXTRAS:
                p[nombre] = (_num(fila[col_l]), _num(fila[col_v]))
            partidos.append(p)
    partidos.sort(key=lambda p: (p["fecha"], p["local"], p["visitante"]))
    return partidos


def _vista_equipo(p: dict, equipo: str) -> dict:
    """El partido desde el punto de vista de `equipo`."""
    es_local = p["local"] == equipo
    gf, gc = (p["gl"], p["gv"]) if es_local else (p["gv"], p["gl"])
    vista = {"fecha": p["fecha"], "local": es_local, "rival": p["visitante"] if es_local else p["local"], "gf": gf, "gc": gc,
             "res": "G" if gf > gc else "E" if gf == gc else "P"}
    for nombre, _, _ in _EXTRAS:
        a_favor, en_contra = (p[nombre] if es_local else p[nombre][::-1])
        vista[nombre] = (a_favor, en_contra)
    return vista


def _pp(total: float, n: int) -> float:
    return round(total / n, 2) if n else 0.0


def _pct(parte: int, n: int) -> float:
    return round(100 * parte / n, 1) if n else 0.0


def _bloque_simple(vistas: list[dict]) -> dict:
    n = len(vistas)
    return {"partidos": n, "g": sum(v["res"] == "G" for v in vistas), "e": sum(v["res"] == "E" for v in vistas),
            "p": sum(v["res"] == "P" for v in vistas), "gf_pp": _pp(sum(v["gf"] for v in vistas), n),
            "gc_pp": _pp(sum(v["gc"] for v in vistas), n)}


def _extras(vistas: list[dict]) -> dict:
    salida = {}
    for nombre, _, _ in _EXTRAS:
        pares = [v[nombre] for v in vistas if v[nombre][0] is not None and v[nombre][1] is not None]
        if len(pares) >= MIN_PARTIDOS_EXTRA:
            salida[nombre] = {"favor_pp": _pp(sum(a for a, _ in pares), len(pares)),
                              "contra_pp": _pp(sum(b for _, b in pares), len(pares)), "partidos_con_dato": len(pares)}
    return salida


def bloque_ventana(vistas: list[dict]) -> dict:
    """Totales, local/visitante, over 2.5, ambos anotan y extras de una lista de partidos del equipo."""
    n = len(vistas)
    bloque = _bloque_simple(vistas)
    locales = [v for v in vistas if v["local"]]
    visitas = [v for v in vistas if not v["local"]]
    local, visitante = _bloque_simple(locales), _bloque_simple(visitas)
    bloque.update({
        "local": local, "visitante": visitante,
        "pct_over25": _pct(sum(v["gf"] + v["gc"] > 2 for v in vistas), n),
        "pct_btts": _pct(sum(v["gf"] > 0 and v["gc"] > 0 for v in vistas), n),
        "dif_gf_local_menos_visitante": round(local["gf_pp"] - visitante["gf_pp"], 2) if locales and visitas else None,
        "dif_gc_local_menos_visitante": round(local["gc_pp"] - visitante["gc_pp"], 2) if locales and visitas else None,
    })
    extras = _extras(vistas)
    if extras:
        bloque["extras"] = extras
    return bloque


def _racha(vistas: list[dict]) -> list[dict]:
    return [{"fecha": v["fecha"].isoformat(), "rival": v["rival"], "condicion": "local" if v["local"] else "visitante",
             "marcador": f"{v['gf']}-{v['gc']}", "resultado": v["res"]} for v in reversed(vistas[-5:])]


def _texto_bloque(etiqueta: str, b: dict) -> str:
    if not b["partidos"]:
        return f"{etiqueta}: sin partidos."
    texto = (f"{etiqueta}: {b['partidos']} partidos, {b['g']}G {b['e']}E {b['p']}P, goles {b['gf_pp']:.2f} a favor y "
             f"{b['gc_pp']:.2f} en contra por partido (local {b['local']['gf_pp']:.2f}-{b['local']['gc_pp']:.2f} en "
             f"{b['local']['partidos']} partidos; visitante {b['visitante']['gf_pp']:.2f}-{b['visitante']['gc_pp']:.2f} en "
             f"{b['visitante']['partidos']}); más de 2.5 goles en {b['pct_over25']}% y ambos anotan en {b['pct_btts']}%.")
    extras = b.get("extras", {})
    if extras:
        etiquetas = {"tiros": "tiros", "tiros_arco": "tiros al arco", "corners": "córners", "amarillas": "amarillas", "rojas": "rojas"}
        texto += " Promedios a favor/en contra: " + "; ".join(f"{etiquetas[k]} {v['favor_pp']:.1f}/{v['contra_pp']:.1f}" for k, v in extras.items()) + "."
    return texto


def perfil_equipo(equipo: str, liga: dict, vistas: list[dict], corte: date, temporadas: list[str]) -> dict | None:
    """Perfil de un equipo, o None si no jugó en los últimos 12 meses de su liga."""
    desde = corte - timedelta(days=DIAS_VENTANA)
    v12 = [v for v in vistas if v["fecha"] > desde]
    if not v12:
        return None
    v3 = [v for v in vistas if v["_temporada"] in temporadas]
    b12, b3 = bloque_ventana(v12), bloque_ventana(v3)
    racha = _racha(vistas)
    ultimo = vistas[-1]["fecha"].isoformat()
    metadata = {
        "equipo": equipo, "liga_codigo": liga["codigo"], "liga_nombre": liga["nombre"], "pais": liga["pais"],
        "ultimo_partido": ultimo, "corte_liga": corte.isoformat(), "partidos_historicos": len(vistas),
        "ventana_12m": {"desde": desde.isoformat(), "hasta": corte.isoformat(), **b12},
        "ventana_3t": {"temporadas": temporadas, **b3},
        "racha_5": racha,
    }
    texto_racha = "; ".join(f"{r['resultado']} {r['fecha']} vs {r['rival']} ({r['marcador']}, {r['condicion']})" for r in racha)
    contenido = (
        f"{equipo} ({liga['nombre']}, {liga['pais']}; {liga['codigo']}). Último partido registrado: {ultimo} "
        f"(los datos de la liga llegan hasta {corte.isoformat()}). "
        + _texto_bloque(f"Últimos 12 meses ({desde.isoformat()} a {corte.isoformat()})", b12) + " "
        + _texto_bloque(f"Últimas 3 temporadas ({', '.join(temporadas)})", b3) + " "
        + f"Últimos 5, del más reciente: {texto_racha}. "
        + "Son hechos pasados de la liga doméstica, no una promesa sobre el próximo partido."
    )
    return {"namespace": "futbol", "topic_key": f"equipo-{liga['codigo']}-{slug(equipo)}", "content": contenido,
            "source": FUENTE, "metadata": metadata}


def entradas_liga(codigo: str, partidos: list[dict]) -> list[dict]:
    liga = {"codigo": codigo, "nombre": partidos[-1]["liga_nombre"], "pais": partidos[-1]["pais"]}
    corte = max(p["fecha"] for p in partidos)
    ultima_fecha: dict[str, date] = {}
    for p in partidos:
        ultima_fecha[p["temporada"]] = max(ultima_fecha.get(p["temporada"], p["fecha"]), p["fecha"])
    temporadas = sorted(ultima_fecha, key=lambda t: ultima_fecha[t])[-TEMPORADAS_VENTANA:]
    por_equipo: dict[str, list[dict]] = {}
    for p in partidos:
        for lado in ("local", "visitante"):
            equipo = p[lado]
            vista = _vista_equipo(p, equipo)
            vista["_temporada"] = p["temporada"]
            por_equipo.setdefault(equipo, []).append(vista)
    entradas, usados = [], set()
    for equipo in sorted(por_equipo):
        entrada = perfil_equipo(equipo, liga, por_equipo[equipo], corte, temporadas)
        if entrada is None:
            continue
        clave = entrada["topic_key"]
        if clave in usados:  # dos nombres que normalizan igual: se desambigua sin perder ninguno
            entrada["topic_key"] = f"{clave}-{len(usados)}"
        usados.add(entrada["topic_key"])
        entradas.append(entrada)
    return entradas


def escribir(codigo: str, entradas: list[dict], destino: Path = DESTINO) -> Path:
    ruta = destino / f"equipos-{codigo.lower()}.json"
    cuerpo = ",\n".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in entradas)
    ruta.write_text(f"[\n{cuerpo}\n]\n", encoding="utf-8")
    return ruta


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Genera knowledge/sports/equipos-<liga>.json (idempotente).")
    parser.add_argument("--liga", help="Código de una sola liga (ej. CHL1)")
    args = parser.parse_args(argv)
    por_liga: dict[str, list[dict]] = {}
    for p in leer_partidos():
        por_liga.setdefault(p["liga"], []).append(p)
    total_equipos, total_bytes = 0, 0
    for codigo, partidos in sorted(por_liga.items()):
        if args.liga and codigo != args.liga:
            continue
        entradas = entradas_liga(codigo, partidos)
        ruta = escribir(codigo, entradas)
        total_equipos += len(entradas)
        total_bytes += ruta.stat().st_size
        print(f"{codigo}: {len(entradas)} equipos -> {ruta.relative_to(REPO)}")
    print(f"TOTAL: {total_equipos} equipos, {total_bytes / 1e6:.2f} MB")


if __name__ == "__main__":
    sys.exit(main())
