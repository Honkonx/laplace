"""Perfiles de equipo del agente: consulta por nombre sobre `knowledge/sports/equipos-<liga>.json`.

Los perfiles son hechos medidos del histórico (últimos 12 meses y últimas 3 temporadas de la liga
doméstica, racha de 5, local/visitante, over 2.5, ambos anotan y, si la fuente los trae, tiros,
córners y tarjetas). Son ~925 equipos y ~2,7 MB: se leen bajo demanda de los archivos y se cachean en
memoria por firma de archivo, NO se cargan en la tabla `agent_knowledge` (ver
`agent_knowledge._archivos_conocimiento`), porque cada consulta de chat recorre esa tabla entera.

Cómo regenerar (idempotente, solo escribe `knowledge/sports/equipos-*.json`):

    python backend/scripts/generar_conocimiento_equipos.py            # todas las ligas
    python backend/scripts/generar_conocimiento_equipos.py --liga CHL1

Resolución de nombres (nunca adivina): se prueba por etapas y gana la primera que encuentra algo,
con los alias y la normalización de `modelo_historico` (los mismos que usa el módulo `historico`):
exacta, apodo, alias vivo, nombre compatible, palabras contenidas y, al final, errata de una sola
letra (marcada `aproximada`). Si el resultado son varios clubes distintos, devuelve candidatos y el
llamador debe preguntar. Un mismo club en dos divisiones del mismo país (ascenso/descenso) es un solo
club: gana la división donde jugó más recientemente y la otra se informa en `otras_ligas`.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date

from backend.api.services import conocimiento_referencia as ref
from backend.api.services import modelo_historico as mh

NOTA_PERFIL = "Hechos medidos de la liga doméstica; describen lo ocurrido, no prometen lo que pasará en el próximo partido."
MUESTRA_PEQUENA = 15
_UMBRAL_ERRATA = 0.92
_MAX_CANDIDATOS = 6
_COMUNES = frozenset({"chico", "start", "haka", "jaro", "cerro", "kyoto", "chiba", "mito", "remo", "cusco", "oriente", "santa", "fenix", "pogon", "como", "nice", "lens", "tigre", "libertad", "central", "union", "boston", "gent", "sion", "ried", "aris", "bari"})
_PISTAS = re.compile(r"\b(?:viene|vienen|perfil|forma|racha|equipo|club|rendimiento|estadisticas|ultimos|como le va|como anda|como juega)\b")

# Apodo o abreviatura (normalizados con `ref.normalizar`) -> (nombre canónico en el histórico, liga).
APODOS: dict[str, tuple] = {  # valor: (nombre, liga) o una tupla de ellos si el apodo es ambiguo
    "la u": ("Universidad de Chile", "CHL1"), "u de chile": ("Universidad de Chile", "CHL1"), "u chile": ("Universidad de Chile", "CHL1"),
    "la catolica": ("U. Catolica", "CHL1"), "u catolica": ("U. Catolica", "CHL1"), "uc": ("U. Catolica", "CHL1"),
    "barca": ("Barcelona", "SP1"), "barcelona fc": ("Barcelona", "SP1"), "fc barcelona": ("Barcelona", "SP1"),
    "atleti": ("Atletico Madrid", "SP1"), "psg": ("Paris Saint Germain", "F1"), "paris sg": ("Paris Saint Germain", "F1"),
    "spurs": ("Tottenham", "E0"),
    "gladbach": ("Borussia Monchengladbach", "D1"),
    "bayern": ("Bayern Munich", "D1"), "bayern munchen": ("Bayern Munich", "D1"), "juve": ("Juventus", "I1"), "inter de milan": ("Inter", "I1"),
    "sporting de lisboa": ("Sp Lisbon", "P1"), "sporting lisboa": ("Sp Lisbon", "P1"), "sporting cp": ("Sp Lisbon", "P1"), "sporting lisbon": ("Sp Lisbon", "P1"),
    "chivas": ("Guadalajara Chivas", "MEX"), "pumas": ("UNAM Pumas", "MEX"), "rayados": ("Monterrey", "MEX"), "tigres": ("Tigres UANL", "MEX"),
    "ldu": ("LDU de Quito", "ECU1"), "liga de quito": ("LDU de Quito", "ECU1"), "newells": ("Newells Old Boys", "ARG"),
    "velez": ("Velez Sarsfield", "ARG"), "gimnasia": ("Gimnasia L.P.", "ARG"), "gimnasia la plata": ("Gimnasia L.P.", "ARG"),
    "estudiantes la plata": ("Estudiantes L.P.", "ARG"), "racing de avellaneda": ("Racing Club", "ARG"), "san lorenzo de almagro": ("San Lorenzo", "ARG"),
    "flamengo": ("Flamengo RJ", "BRA"), "botafogo": ("Botafogo RJ", "BRA"), "atletico mineiro": ("Atletico-MG", "BRA"),
    "atletico paranaense": ("Athletico-PR", "BRA"), "athletico paranaense": ("Athletico-PR", "BRA"),
    "penarol": ("Penarol", "URY1"), "nacional de montevideo": ("Club Nacional", "URY1"),
    "atletico nacional medellin": ("Atletico Nacional", "COL1"),
    "universidad catolica": (("U. Catolica", "CHL1"), ("Universidad Catolica", "ECU1")),
}


@dataclass(frozen=True)
class Club:
    """Un club (nombre + país) con uno o más perfiles, uno por división cubierta."""
    nombre: str
    pais: str
    perfiles: tuple[dict, ...]

    @property
    def principal(self) -> dict:
        return max(self.perfiles, key=lambda p: (p["metadata"]["ultimo_partido"], p["metadata"]["partidos_historicos"]))


def _firma_alias() -> tuple:
    return ref._firma([mh.RUTA_ALIAS, mh.RUTA_ALIAS_EQUIPOS_VIVO])


def _indice() -> dict:
    archivos = ref.archivos_equipos()

    def construir() -> dict:
        perfiles = []
        for ruta in archivos:
            crudo = ref._leer_json(ruta)
            for entrada in crudo if isinstance(crudo, list) else []:
                meta = entrada.get("metadata") if isinstance(entrada, dict) else None
                if isinstance(meta, dict) and meta.get("equipo") and meta.get("ultimo_partido"):
                    perfiles.append({**entrada, "_norm": mh._normalizar(meta["equipo"]), "_nombre": mh._analizar_nombre(meta["equipo"])})
        return {"perfiles": perfiles, "por_clave": {p["topic_key"]: p for p in perfiles}}
    return ref._cacheado("equipos", archivos, construir)  # type: ignore[return-value]


def _alias() -> dict[str, dict[str, str]]:
    return ref._cacheado("alias_equipos", [mh.RUTA_ALIAS, mh.RUTA_ALIAS_EQUIPOS_VIVO], mh._alias_por_liga)  # type: ignore[return-value]


def contar_equipos() -> int:
    return len(_indice()["perfiles"])


def equipos_de_liga(codigo: str) -> int:
    return sum(1 for p in _indice()["perfiles"] if p["metadata"]["liga_codigo"] == codigo)


# --- Resolución -----------------------------------------------------------------------------

def _unicos(perfiles: list[dict]) -> list[dict]:
    return list({p["topic_key"]: p for p in perfiles}.values())


def _nombres_conocidos(perfiles: list[dict], norm: str, analizado) -> tuple[str, list[dict]]:
    """Coincidencias por nombre completo: exacto, apodo o alias vivo (se unen: «Universidad Católica» es de Chile y de Ecuador)."""
    exactos = [p for p in perfiles if p["_norm"] == analizado.norm]
    apodos = [p for nombre, liga in _apodos(norm) for p in perfiles if p["metadata"]["equipo"] == nombre and p["metadata"]["liga_codigo"] == liga]
    canonicos = {(liga, canon) for liga, tabla in _alias().items() if (canon := tabla.get(analizado.norm))}
    por_alias = [p for p in perfiles if any(p["metadata"]["equipo"] == canon and liga in ("*", p["metadata"]["liga_codigo"]) for liga, canon in canonicos)]
    etiqueta = "exacta" if exactos else "apodo" if apodos else "alias"
    return etiqueta, _unicos(exactos + apodos + por_alias)


def _apodos(norm: str) -> tuple[tuple[str, str], ...]:
    valor = APODOS.get(norm, ())
    return valor if valor and isinstance(valor[0], tuple) else (valor,) if valor else ()


def _con_prefijo(candidatos: list[dict], fichas: list[str]) -> list[dict]:
    """Si algún nombre empieza por lo escrito («river» -> «River Plate»), solo esos: «Boston River» queda aparte."""
    empiezan = [p for p in candidatos if p["_norm"].split()[:len(fichas)] == fichas]
    return empiezan or candidatos


def _etapas(consulta: str):
    """Genera (etiqueta, candidatos) de la etapa más fiable a la menos fiable."""
    perfiles = _indice()["perfiles"]
    norm = ref.normalizar(consulta)
    analizado = mh._analizar_nombre(consulta)
    if not analizado.norm:
        return
    etiqueta, conocidos = _nombres_conocidos(perfiles, norm, analizado)
    yield etiqueta, conocidos
    fichas = analizado.norm.split()
    if any(len(f) >= 4 for f in fichas):
        yield "contenido", _con_prefijo([p for p in perfiles if set(fichas) <= set(p["_norm"].split())], fichas)
        if len(fichas) >= 2:  # «Tottenham Hotspur» contiene a «Tottenham»
            yield "contiene", [p for p in perfiles if len(p["_norm"]) >= 5 and set(p["_norm"].split()) <= set(fichas)]
    if len(analizado.norm) >= 8:
        cercanos = difflib.get_close_matches(analizado.norm, sorted({p["_norm"] for p in perfiles}), n=2, cutoff=_UMBRAL_ERRATA)
        if len(cercanos) == 1:
            yield "aproximada", [p for p in perfiles if p["_norm"] == cercanos[0]]


def _agrupar_clubes(candidatos: list[dict]) -> list[Club]:
    """Une las divisiones de un mismo club (mismo nombre y país); clubes distintos quedan separados."""
    grupos: dict[tuple[str, str], list[dict]] = {}
    for p in candidatos:
        grupos.setdefault((p["metadata"]["equipo"], p["metadata"]["pais"]), []).append(p)
    clubes = [Club(nombre, pais, tuple(ps)) for (nombre, pais), ps in grupos.items()]
    return sorted(clubes, key=lambda c: (c.principal["metadata"]["ultimo_partido"], c.principal["metadata"]["partidos_historicos"]), reverse=True)


def _filtrar(candidatos: list[dict], codigos: tuple[str, ...]) -> list[dict]:
    return [p for p in candidatos if p["metadata"]["liga_codigo"] in codigos] if codigos else candidatos


def resolver_equipo(consulta: str, liga: str | None = None) -> dict:
    """{estado: ok|ambiguo|no_encontrado, coincidencia, club, candidatos}. Nunca adivina entre clubes distintos."""
    texto = str(consulta or "").strip()[:100]
    if not texto:
        raise ValueError("Indica el equipo")
    codigos = ref.detectar_ligas(liga).codigos if liga else ()
    if liga and not codigos:
        return {"estado": "no_encontrado", "consulta": texto, "candidatos": [], "motivo": "liga_desconocida"}
    resultado = _resolver_en(texto, codigos)
    if resultado["estado"] == "ok" or codigos:
        return resultado
    # "river uruguay", "boca de argentina": la liga o el país viene dentro del texto.
    pistas = ref.detectar_ligas(texto)
    quitar = [w for w in ref._PALABRAS_PAIS if ref._contiene(ref.normalizar(texto), w)]
    if pistas.codigos and quitar:
        resto = ref.normalizar(texto)
        for palabra in sorted(quitar, key=len, reverse=True):
            resto = resto.replace(palabra, " ")
        resto = re.sub(r"\b(de|del|la|el)\b", " ", resto).strip()
        if resto:
            acotado = _resolver_en(resto, tuple(pistas.codigos))
            if acotado["estado"] != "no_encontrado":
                return acotado
    return resultado


def _resolver_en(texto: str, codigos: tuple[str, ...]) -> dict:
    for etiqueta, candidatos in _etapas(texto):
        clubes = _agrupar_clubes(_filtrar(candidatos, codigos))
        if not clubes:
            continue
        if len(clubes) == 1:
            return {"estado": "ok", "consulta": texto, "coincidencia": etiqueta, "club": clubes[0], "candidatos": []}
        return {"estado": "ambiguo", "consulta": texto, "coincidencia": etiqueta, "club": None,
                "candidatos": [_ficha(c.principal) for c in clubes[:_MAX_CANDIDATOS]]}
    return {"estado": "no_encontrado", "consulta": texto, "candidatos": []}


def _ficha(perfil: dict) -> dict:
    m = perfil["metadata"]
    return {"equipo": m["equipo"], "liga_codigo": m["liga_codigo"], "liga_nombre": m["liga_nombre"], "pais": m["pais"], "ultimo_partido": m["ultimo_partido"]}


# --- Consulta ---------------------------------------------------------------------------------

def perfil_equipo(consulta: str, liga: str | None = None, *, referencia: date | None = None) -> dict:
    """Perfil estructurado de un equipo. `estado`: ok | ambiguo | no_encontrado (con candidatos o sugerencia)."""
    r = resolver_equipo(consulta, liga)
    if r["estado"] == "ambiguo":
        return {"estado": "ambiguo", "consulta": r["consulta"], "candidatos": r["candidatos"],
                "mensaje": "Hay varios equipos con ese nombre; indica cuál (por ejemplo agregando el país o la liga)."}
    if r["estado"] == "no_encontrado":
        return {"estado": "no_encontrado", "consulta": r["consulta"], "candidatos": [],
                "mensaje": "No tengo un perfil de ese equipo: no está en las ligas cubiertas o no jugó en el último año de su liga. No invento cifras."}
    club: Club = r["club"]
    principal = club.principal
    meta = principal["metadata"]
    frescura = ref.frescura_desde(meta["ultimo_partido"], referencia)
    avisos = [frescura["aviso"]] if frescura["aviso"] else []
    if meta["ventana_12m"]["partidos"] < MUESTRA_PEQUENA:
        avisos.append(f"Muestra pequeña: solo {meta['ventana_12m']['partidos']} partidos en los últimos 12 meses; las cifras son inestables.")
    if not meta["ventana_12m"].get("extras") and not meta["ventana_3t"].get("extras"):
        avisos.append("La fuente no trae tiros, córners ni tarjetas de esta liga.")
    if r["coincidencia"] == "aproximada":
        avisos.append(f"Entendí «{meta['equipo']}» a partir de «{r['consulta']}»; confirma que es el equipo correcto.")
    otras = [{"liga_codigo": p["metadata"]["liga_codigo"], "liga_nombre": p["metadata"]["liga_nombre"], "ultimo_partido": p["metadata"]["ultimo_partido"]}
             for p in club.perfiles if p is not principal]
    return {
        "estado": "ok", "consulta": r["consulta"], "coincidencia": r["coincidencia"], "equipo": _ficha(principal),
        "perfil": {k: meta[k] for k in ("ultimo_partido", "corte_liga", "partidos_historicos", "ventana_12m", "ventana_3t", "racha_5")},
        "texto": principal["content"], "frescura": frescura, "avisos": avisos, "otras_ligas": otras,
        "fuente": principal.get("source"), "nota": NOTA_PERFIL,
    }


def detectar_equipos_en_texto(texto: str, maximo: int = 2) -> list[dict]:
    """Equipos (hasta `maximo`, uno por club) mencionados en un mensaje libre. Prueba tramos de 4 a 1 palabras.

    Solo cuentan coincidencias por nombre completo, apodo o alias; «Boca» (nombre parcial) solo si el
    mensaje trae una pista como «cómo viene», «perfil» o «forma». Un tramo de una palabra exige ≥4 letras
    y no ser una palabra común que también es un equipo («chico», «como»). Un tramo que corresponde a
    varios clubes no se adivina: se omite."""
    norm = ref.normalizar(texto)
    palabras = norm.split()
    hay_pista = bool(_PISTAS.search(norm))
    usadas: set[int] = set()
    hallazgos: list[dict] = []
    for largo in (4, 3, 2, 1):
        for i in range(len(palabras) - largo + 1):
            posiciones = set(range(i, i + largo))
            tramo = " ".join(palabras[i:i + largo])
            if posiciones & usadas or not _tramo_plausible(tramo, palabras[i:i + largo]):
                continue
            club = _club_unico(tramo, aceptar_contenido=largo == 1 and hay_pista)
            if club is not None and all(h["club"].nombre != club.nombre or h["club"].pais != club.pais for h in hallazgos):
                usadas |= posiciones
                hallazgos.append({"club": club, "tramo": tramo, "orden": i})
    return [{k: h[k] for k in ("club", "tramo")} for h in sorted(hallazgos, key=lambda h: h["orden"])[:maximo]]


def _tramo_plausible(tramo: str, palabras: list[str]) -> bool:
    if len(palabras) == 1:
        return len(tramo) >= 4 and tramo not in _COMUNES and tramo not in ref._PALABRAS_PAIS
    return tramo in APODOS or not all(len(w) <= 2 for w in palabras)


def _club_unico(tramo: str, aceptar_contenido: bool) -> Club | None:
    permitidas = ("exacta", "apodo", "alias") + (("contenido",) if aceptar_contenido else ())
    for etiqueta, candidatos in _etapas(tramo):
        if etiqueta not in permitidas:
            return None
        clubes = _agrupar_clubes(candidatos)
        if len(clubes) == 1:
            return clubes[0]
        if clubes:
            return None
    return None


def fragmento_equipo(club: Club) -> dict:
    """Fragmento compacto para el contexto del agente: texto del perfil más el aviso de frescura si corresponde."""
    principal = club.principal
    frescura = ref.frescura_desde(principal["metadata"]["ultimo_partido"])
    aviso = f" AVISO: {frescura['aviso']}" if frescura["aviso"] else ""
    return {"namespace": "futbol", "topic_key": principal["topic_key"], "content": principal["content"] + aviso}
