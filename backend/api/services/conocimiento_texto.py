"""Respuestas en texto, deterministas, de las herramientas `knowledge.*` del agente.

Cada función recibe el resultado estructurado de `conocimiento_equipos` / `conocimiento_referencia` y
devuelve el mensaje que ven web, PWA, app y Telegram. Toda cifra sale de ese resultado: no hay IA ni
redondeos propios. Si el dato está desactualizado o la muestra es pequeña, el aviso va en el texto.
"""
from __future__ import annotations

from backend.api.services import conocimiento_equipos

_LETRAS = {"G": "ganó", "E": "empató", "P": "perdió"}


def _pct(valor: object) -> str:
    return f"{valor}%"


def _linea_ventana(etiqueta: str, v: dict) -> str:
    if not v.get("partidos"):
        return f"{etiqueta}: sin partidos."
    return (f"{etiqueta}: {v['partidos']} partidos, {v['g']}G {v['e']}E {v['p']}P; goles {v['gf_pp']:.2f} a favor y {v['gc_pp']:.2f} en contra por partido "
            f"(local {v['local']['gf_pp']:.2f}-{v['local']['gc_pp']:.2f}, visitante {v['visitante']['gf_pp']:.2f}-{v['visitante']['gc_pp']:.2f}); "
            f"más de 2.5 goles en {_pct(v['pct_over25'])} y ambos anotan en {_pct(v['pct_btts'])}.")


def texto_equipo(r: dict) -> str:
    if r["estado"] == "ambiguo":
        opciones = "; ".join(f"{c['equipo']} ({c['liga_nombre']}, {c['pais']})" for c in r["candidatos"])
        return f"Hay varios equipos que coinciden con «{r['consulta']}»: {opciones}. ¿De cuál quieres el perfil? Indica el país o la liga."
    if r["estado"] == "no_encontrado":
        return f"No tengo un perfil de «{r['consulta']}»: no está en las ligas cubiertas o no jugó en el último año de su liga. No invento cifras."
    e, p = r["equipo"], r["perfil"]
    racha = " ".join(x["resultado"] for x in p["racha_5"])
    partes = [f"{e['equipo']} ({e['liga_nombre']}, {e['pais']}).",
              _linea_ventana("Últimos 12 meses", p["ventana_12m"]),
              _linea_ventana(f"Últimas 3 temporadas ({', '.join(p['ventana_3t']['temporadas'])})", p["ventana_3t"]),
              f"Últimos 5 (del más reciente): {racha}. Último partido registrado: {p['ultimo_partido']}."]
    partes += [f"Aviso: {a}" for a in r["avisos"]]
    if r["otras_ligas"]:
        partes.append("También jugó en: " + ", ".join(o["liga_nombre"] for o in r["otras_ligas"]) + ".")
    partes.append(r["nota"])
    return " ".join(partes)


def texto_liga(r: dict) -> str:
    if r["estado"] == "ambiguo":
        opciones = "; ".join(f"{c.get('nombre', c['codigo'])} ({c.get('pais')})" for c in r["candidatos"])
        return f"{r['mensaje']} Opciones: {opciones}."
    if r["estado"] == "no_encontrada":
        ligas = ", ".join(f"{x['nombre']} ({x['pais']})" for x in r["ligas_cubiertas"][:12])
        return f"{r['mensaje']} Algunas ligas que sí cubro: {ligas}, entre otras."
    liga, t = r["liga"], r["tasas_base"]
    if t is None:
        cuerpo = f"{liga['nombre']} ({liga['pais']}): no hay tasas base publicadas."
    else:
        cuerpo = (f"{liga['nombre']} ({liga['pais']}), temporadas {t['temporadas'][0]}–{t['temporadas'][-1]}, {t['partidos']} partidos: "
                  f"gana el local {_pct(t['pct_local'])}, empate {_pct(t['pct_empate'])}, gana el visitante {_pct(t['pct_visitante'])}; "
                  f"promedio {t['goles_por_partido']:.2f} goles por partido; más de 2.5 goles en {_pct(t['pct_over25'])} y ambos anotan en {_pct(t['pct_btts'])}.")
    cob = r["cobertura"]
    partes = [cuerpo, f"Cobertura: {cob['partidos_historicos']} partidos desde {cob['desde']} hasta {cob['hasta']}."]
    partes += [f"Aviso: {a}" for a in r["avisos"]]
    partes.append(r["nota"])
    return " ".join(partes)


def texto_glosario(r: dict) -> str:
    if r["estado"] == "no_encontrado":
        return f"{r['mensaje']} Puedo explicar, por ejemplo: " + ", ".join(r["terminos_disponibles"][:10]) + "."
    texto = r["entrada"]["texto"]
    if r["relacionados"]:
        texto += " Relacionado: " + "; ".join(x["titulo"] for x in r["relacionados"]) + "."
    return texto


def linea_forma(nombre: str, liga: str | None = None) -> str | None:
    """Una línea con la racha y los goles recientes de un equipo para acompañar un pronóstico, o None si
    no hay perfil o el nombre es ambiguo (no se adivina)."""
    # Con liga, solo vale el perfil DE ESA liga: si el equipo no figura en ella (o la liga no se reconoce) no se busca "por
    # nombre a secas", porque puede ser un homónimo de otro país (sandbox del agente, 2026-11-09: un "Club Fenix" inventado
    # recibió la forma del Fénix uruguayo). Sin liga (el usuario solo escribió nombres) se busca por nombre y un nombre
    # ambiguo no se adivina.
    r = conocimiento_equipos.perfil_equipo(nombre, liga or None)
    if r["estado"] != "ok":
        return None
    p, v = r["perfil"], r["perfil"]["ventana_12m"]
    racha = " ".join(x["resultado"] for x in p["racha_5"])
    aviso = f" ({r['frescura']['aviso']})" if r["frescura"]["aviso"] else ""
    return (f"Forma de {r['equipo']['equipo']}: últimos 5 {racha}; {v['gf_pp']:.2f} goles a favor y {v['gc_pp']:.2f} en contra por partido "
            f"en {v['partidos']} partidos de los últimos 12 meses{aviso}.")


def oferta_perfiles(nombres: list[str]) -> str:
    """Si hay perfil de alguno de los equipos nombrados, lo ofrece (no lo vuelca sin que lo pidan)."""
    con_perfil = []
    for nombre in nombres:
        r = conocimiento_equipos.resolver_equipo(nombre)
        if r["estado"] == "ok":
            con_perfil.append(r["club"].nombre)
    if not con_perfil:
        return ""
    pedidos = " o ".join(f"«perfil de {n}»" for n in con_perfil)
    return f" Sí tengo datos históricos de {', '.join(con_perfil)}: pídeme {pedidos}."

