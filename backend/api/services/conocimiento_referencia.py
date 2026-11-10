"""Conocimiento de referencia del agente leído de `knowledge/`: ligas, glosario y versión.

Todo es determinista y de solo lectura: nada llama a una IA ni a la red. Las rutas salen de
`settings.repo_root` (los tests las redirigen a una carpeta temporal).

- `detectar_ligas(texto)`: reconoce liga/país/gentilicio en lenguaje natural ("la liga chilena",
  "la Premier", "serie b de Brasil"). Un nombre compartido por varias ligas ("primera división")
  sin país NO se adivina: devuelve `ambiguo=True`.
- `perfil_liga(consulta)`: tasas base (de `ligas-estadisticas.json`), cobertura y frescura.
- `buscar_glosario(termino)`: términos, guías y FAQ (entradas con `metadata.tipo` glosario/guia/faq).
- `version_conocimiento()`: huella de los archivos y fecha de los datos, para `/agent/capabilities`.

Los perfiles de equipo viven en `conocimiento_equipos.py`. Para regenerar las tasas base:
`python backend/scripts/generar_conocimiento_ligas.py`.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from backend.api.core.config import settings

RUTA_LIGAS_ALIAS = Path(__file__).resolve().parents[1] / "ml" / "alias" / "ligas_alias.json"
TIPOS_REFERENCIA = frozenset({"glosario", "guia", "faq"})
COPAS = {"UCL": "UEFA Champions League", "UEL": "UEFA Europa League", "CLI": "Copa Libertadores", "CSU": "Copa Sudamericana"}

# País (nombre en inglés, como en `ligas_alias.json`) -> código de su primera división.
PRIMERA_DIVISION = {
    "argentina": "ARG", "chile": "CHL1", "peru": "PER1", "uruguay": "URY1", "colombia": "COL1", "ecuador": "ECU1",
    "paraguay": "PRY1", "bolivia": "BOL1", "venezuela": "VEN1", "brazil": "BRA", "mexico": "MEX", "spain": "SP1",
    "england": "E0", "italy": "I1", "germany": "D1", "france": "F1", "portugal": "P1", "netherlands": "N1",
    "belgium": "B1", "turkey": "T1", "scotland": "SC0", "greece": "G1", "switzerland": "SWZ", "austria": "AUT",
    "denmark": "DNK", "sweden": "SWE", "norway": "NOR", "finland": "FIN", "poland": "POL", "romania": "ROU",
    "russia": "RUS", "ireland": "IRL", "usa": "USA", "japan": "JPN", "china": "CHN", "south korea": "KOR1",
    "saudi arabia": "SAU1",
}
# Palabra o frase (sin tildes) -> país. Incluye gentilicios en ambos géneros.
_PALABRAS_PAIS = {
    "argentina": "argentina", "argentino": "argentina", "chile": "chile", "chileno": "chile", "chilena": "chile",
    "peru": "peru", "peruano": "peru", "peruana": "peru", "uruguay": "uruguay", "uruguayo": "uruguay", "uruguaya": "uruguay",
    "colombia": "colombia", "colombiano": "colombia", "colombiana": "colombia", "ecuador": "ecuador", "ecuatoriano": "ecuador",
    "ecuatoriana": "ecuador", "paraguay": "paraguay", "paraguayo": "paraguay", "paraguaya": "paraguay", "bolivia": "bolivia",
    "boliviano": "bolivia", "boliviana": "bolivia", "venezuela": "venezuela", "venezolano": "venezuela", "venezolana": "venezuela",
    "brasil": "brazil", "brasileno": "brazil", "brasilena": "brazil", "brasilero": "brazil", "brasilera": "brazil", "brasileira": "brazil",
    "mexico": "mexico", "mexicano": "mexico", "mexicana": "mexico", "espana": "spain", "espanol": "spain", "espanola": "spain",
    "inglaterra": "england", "ingles": "england", "inglesa": "england", "italia": "italy", "italiano": "italy", "italiana": "italy",
    "alemania": "germany", "aleman": "germany", "alemana": "germany", "francia": "france", "frances": "france", "francesa": "france",
    "portugal": "portugal", "portugues": "portugal", "portuguesa": "portugal", "holanda": "netherlands", "holandes": "netherlands",
    "holandesa": "netherlands", "neerlandes": "netherlands", "paises bajos": "netherlands", "belgica": "belgium", "belga": "belgium",
    "turquia": "turkey", "turco": "turkey", "turca": "turkey", "escocia": "scotland", "escoces": "scotland", "escocesa": "scotland",
    "grecia": "greece", "griego": "greece", "griega": "greece", "suiza": "switzerland", "suizo": "switzerland",
    "austria": "austria", "austriaco": "austria", "austriaca": "austria", "dinamarca": "denmark", "danes": "denmark", "danesa": "denmark",
    "suecia": "sweden", "sueco": "sweden", "sueca": "sweden", "noruega": "norway", "noruego": "norway", "finlandia": "finland",
    "finlandes": "finland", "finlandesa": "finland", "polonia": "poland", "polaco": "poland", "polaca": "poland", "rumania": "romania",
    "rumano": "romania", "rumana": "romania", "rusia": "russia", "ruso": "russia", "rusa": "russia", "irlanda": "ireland",
    "irlandes": "ireland", "irlandesa": "ireland", "eeuu": "usa", "usa": "usa", "estados unidos": "usa", "estadounidense": "usa",
    "japon": "japan", "japones": "japan", "japonesa": "japan", "china": "china", "chino": "china", "corea": "south korea",
    "coreano": "south korea", "coreana": "south korea", "arabia saudita": "saudi arabia", "arabia": "saudi arabia", "saudita": "saudi arabia",
}
# Frases que valen para una sola liga aunque el alias oficial las comparta con otra.
_FRASES_FIJAS = {
    "premier league": ("E0",), "premier": ("E0",), "bundesliga": ("D1",), "serie a": ("I1",), "serie b": ("I2",),
    "la liga": ("SP1",), "laliga": ("SP1",), "segunda division": ("SP2",), "brasileirao": ("BRA",), "mls": ("USA",),
    "liga mx": ("MEX",), "champions league": ("UCL",), "champions": ("UCL",), "europa league": ("UEL",),
    "libertadores": ("CLI",), "copa libertadores": ("CLI",), "sudamericana": ("CSU",), "copa sudamericana": ("CSU",),
    "liga profesional": ("ARG",), "ligue 1": ("F1",), "eredivisie": ("N1",),
}
# Frases demasiado genéricas para fiarse de ellas sin país.
_FRASES_IGNORADAS = frozenset({"liga", "primera", "super", "premier division", "division profesional", "liga i"})
_LIGA = re.compile(r"\b([A-Z]{1,3}[0-9]?)\b")


def normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", plano)).strip()


def _leer_json(ruta: Path) -> object:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _firma(rutas: list[Path]) -> tuple:
    firma = []
    for ruta in rutas:
        try:
            info = ruta.stat()
            firma.append((str(ruta), info.st_mtime_ns, info.st_size))
        except OSError:
            firma.append((str(ruta), -1, -1))
    return tuple(firma)


_CACHE: dict[str, tuple[tuple, object]] = {}


def _cacheado(clave: str, rutas: list[Path], construir):
    """Reconstruye un índice solo cuando cambian los archivos de los que depende."""
    firma = _firma(rutas)
    previo = _CACHE.get(clave)
    if previo and previo[0] == firma:
        return previo[1]
    valor = construir()
    _CACHE[clave] = (firma, valor)
    return valor


def dir_conocimiento() -> Path:
    return settings.repo_root / "backend" / "knowledge"


def archivos_referencia() -> list[Path]:
    """JSON de `knowledge/` que no son casos de prueba ni perfiles de equipo."""
    raiz = dir_conocimiento()
    return sorted(p for p in raiz.glob("**/*.json") if "qa" not in p.relative_to(raiz).parts[:-1] and not p.name.startswith("equipos-"))


def archivos_equipos() -> list[Path]:
    return sorted((dir_conocimiento() / "sports").glob("equipos-*.json"))


def hoy() -> date:
    return date.today()


# --- Ligas ---------------------------------------------------------------------------------

def _tabla_alias_ligas() -> dict:
    def construir() -> dict:
        crudo = _leer_json(RUTA_LIGAS_ALIAS)
        frases: dict[str, list[str]] = {}
        paises: dict[str, str] = {}
        for entrada in (crudo or {}).get("ligas", []) if isinstance(crudo, dict) else []:
            codigo = entrada.get("codigo")
            if not codigo:
                continue
            paises[codigo] = normalizar(entrada.get("pais", ""))
            for nombre in entrada.get("nombres", []):
                clave = normalizar(nombre)
                if len(clave) >= 3 and clave not in _FRASES_IGNORADAS and codigo not in frases.setdefault(clave, []):
                    frases[clave].append(codigo)
        return {"frases": frases, "paises": paises}
    return _cacheado("alias_ligas", [RUTA_LIGAS_ALIAS], construir)  # type: ignore[return-value]


@dataclass(frozen=True)
class LigaDetectada:
    codigos: tuple[str, ...]
    ambiguo: bool = False


def _contiene(texto: str, frase: str) -> bool:
    return f" {frase} " in f" {texto} "


def _frase_calificada(norm: str, frase: str) -> bool:
    """«la liga» seguida de «de …» o de un país («la liga de Costa Rica», «la liga chilena») no es LaLiga."""
    if frase != "la liga":
        return False
    siguiente = f" {norm} ".split(" la liga ", 1)[1].split()[:1]
    return bool(siguiente) and (siguiente[0] in ("de", "del") or siguiente[0] in _PALABRAS_PAIS)


def detectar_ligas(texto: str) -> LigaDetectada:
    """Ligas mencionadas en `texto`. Un código explícito (CHL1, E0) se respeta tal cual."""
    norm = normalizar(texto)
    if not norm:
        return LigaDetectada(())
    tabla = _tabla_alias_ligas()
    conocidos = set(tabla["paises"]) | set(COPAS)
    explicitos = tuple(c for c in dict.fromkeys(_LIGA.findall(texto or "")) if c in conocidos)
    if explicitos:
        return LigaDetectada(explicitos)
    paises = {pais for palabra, pais in _PALABRAS_PAIS.items() if _contiene(norm, palabra)}
    frases = tabla["frases"]
    mencionadas: list[str] = []
    for frase in sorted({*frases, *_FRASES_FIJAS}, key=len, reverse=True):
        if _contiene(norm, frase) and not _frase_calificada(norm, frase):
            mencionadas.append(frase)
            norm = norm.replace(frase, " ")  # una frase larga ya explica el texto: no sumar las contenidas en ella
    primeras = tuple(PRIMERA_DIVISION[p] for p in sorted(paises) if p in PRIMERA_DIVISION)
    if paises:
        todas = [c for f in mencionadas for c in (*_FRASES_FIJAS.get(f, ()), *frases.get(f, ()))]
        delpais = tuple(dict.fromkeys(c for c in todas if tabla["paises"].get(c) in paises))
        return LigaDetectada(delpais or primeras)
    candidatas = tuple(dict.fromkeys(c for f in mencionadas for c in (_FRASES_FIJAS.get(f) or frases.get(f, ()))))
    return LigaDetectada(candidatas, ambiguo=len(candidatas) > 1 and not all(c in COPAS for c in candidatas))


def _tasas_base() -> dict[str, dict]:
    ruta = dir_conocimiento() / "sports" / "ligas-estadisticas.json"

    def construir() -> dict:
        entradas = _leer_json(ruta)
        salida = {}
        for e in entradas if isinstance(entradas, list) else []:
            meta = e.get("metadata") if isinstance(e, dict) else None
            if isinstance(meta, dict) and meta.get("liga_codigo"):
                salida[meta["liga_codigo"]] = {**meta, "texto": e.get("content", ""), "topic_key": e.get("topic_key")}
        return salida
    return _cacheado("tasas_base", [ruta], construir)  # type: ignore[return-value]


def tasas_base_liga_conocimiento(codigo: str) -> dict | None:
    return _tasas_base().get(codigo)


def _catalogo() -> dict[str, dict]:
    ruta = settings.repo_root / "backend" / "data" / "datos" / "catalogo_ligas.json"

    def construir() -> dict:
        crudo = _leer_json(ruta)
        return {e["codigo"]: e for e in crudo if isinstance(e, dict) and e.get("codigo")} if isinstance(crudo, list) else {}
    return _cacheado("catalogo", [ruta], construir)  # type: ignore[return-value]


def ligas_cubiertas() -> list[dict]:
    """Ligas con histórico: código, nombre, país, tipo y hasta qué fecha llegan los datos."""
    catalogo = _catalogo()
    codigos = set(catalogo) | set(_tasas_base())
    salida = []
    for codigo in sorted(codigos):
        e = catalogo.get(codigo, {})
        salida.append({"codigo": codigo, "nombre": e.get("nombre") or COPAS.get(codigo, codigo), "pais": e.get("pais"),
                       "tipo": "copa" if codigo in COPAS else "liga", "datos_hasta": e.get("hasta")})
    return salida


def _frescura(hasta: str | None, referencia: date | None = None) -> dict:
    """Nivel de actualidad del último dato. Más de 180 días: probablemente fuera de temporada o sin actualizar."""
    if not hasta:
        return {"datos_hasta": None, "dias": None, "nivel": "desconocido", "aviso": "No se conoce la fecha del último dato."}
    try:
        dias = ((referencia or hoy()) - date.fromisoformat(str(hasta)[:10])).days
    except ValueError:
        return {"datos_hasta": hasta, "dias": None, "nivel": "desconocido", "aviso": "Fecha del último dato ilegible."}
    if dias <= 21:
        nivel, aviso = "al_dia", None
    elif dias <= 60:
        nivel, aviso = "reciente", None
    elif dias <= 180:
        nivel, aviso = "pausa_o_atrasado", f"El último partido registrado fue hace {dias} días: puede ser una pausa de temporada o un dato sin actualizar."
    else:
        nivel, aviso = "desactualizado", f"Datos desactualizados: el último partido registrado fue hace {dias} días ({str(hasta)[:10]}). No refleja la forma actual."
    return {"datos_hasta": str(hasta)[:10], "dias": dias, "nivel": nivel, "aviso": aviso}


def frescura_desde(fecha: str | None, referencia: date | None = None) -> dict:
    return _frescura(fecha, referencia)


def perfil_liga(consulta: str, *, referencia: date | None = None) -> dict:
    """Tasas base y cobertura de una liga; `estado` = ok | ambiguo | no_encontrada. Nunca inventa."""
    texto = str(consulta or "").strip()[:200]
    if not texto:
        raise ValueError("Indica la liga (nombre, país o código)")
    detectada = detectar_ligas(texto)
    cubiertas = {liga["codigo"]: liga for liga in ligas_cubiertas()}
    if detectada.ambiguo:
        return {"estado": "ambiguo", "consulta": texto, "candidatos": [cubiertas.get(c, {"codigo": c}) for c in detectada.codigos[:6]],
                "mensaje": "Ese nombre corresponde a varias ligas; indica el país."}
    codigo = next((c for c in detectada.codigos if c in cubiertas), None)
    if codigo is None:
        return {"estado": "no_encontrada", "consulta": texto, "ligas_cubiertas": [{"codigo": c, "nombre": v["nombre"], "pais": v["pais"]} for c, v in cubiertas.items() if v["tipo"] == "liga"],
                "mensaje": "No tengo datos históricos de esa liga, así que no puedo darte tasas base ni perfiles. No invento cifras."}
    return construir_perfil_liga(codigo, cubiertas[codigo], referencia)


def construir_perfil_liga(codigo: str, liga: dict, referencia: date | None = None) -> dict:
    tasas = tasas_base_liga_conocimiento(codigo)
    catalogo = _catalogo().get(codigo, {})
    frescura = _frescura(liga.get("datos_hasta"), referencia)
    avisos = [frescura["aviso"]] if frescura["aviso"] else []
    if liga["tipo"] == "copa":
        avisos.append("Es una copa: reúne equipos de distintas ligas y no tiene perfiles de equipo propios; úsala solo como referencia.")
    if tasas is None:
        avisos.append("No hay tasas base publicadas para esta liga (muestra insuficiente o datos demasiado viejos).")
    return {
        "estado": "ok", "liga": {k: liga[k] for k in ("codigo", "nombre", "pais", "tipo")},
        "tasas_base": None if tasas is None else {k: tasas.get(k) for k in ("partidos", "temporadas", "pct_local", "pct_empate", "pct_visitante", "goles_por_partido", "pct_over25", "pct_btts")},
        "texto": None if tasas is None else tasas["texto"],
        "cobertura": {"cubierta": True, "partidos_historicos": catalogo.get("partidos"), "desde": catalogo.get("desde"), "hasta": catalogo.get("hasta"),
                      "temporadas_disponibles": len(catalogo.get("temporadas", [])) or None, "fuentes": catalogo.get("fuente")},
        "frescura": frescura, "avisos": avisos,
        "nota": "Tasas base históricas: describen lo ocurrido, no prometen lo que pasará en el próximo partido.",
    }


# --- Glosario, guías y FAQ -------------------------------------------------------------------

def _entradas_referencia() -> list[dict]:
    archivos = archivos_referencia()

    def construir() -> list[dict]:
        entradas = []
        for ruta in archivos:
            crudo = _leer_json(ruta)
            for e in crudo if isinstance(crudo, list) else []:
                meta = e.get("metadata") if isinstance(e, dict) else None
                if isinstance(meta, dict) and meta.get("tipo") in TIPOS_REFERENCIA and e.get("topic_key") and e.get("content"):
                    entradas.append({"clave": e["topic_key"], "tipo": meta["tipo"], "texto": e["content"], "namespace": e.get("namespace"),
                                     "terminos": [normalizar(t) for t in meta.get("terminos", []) if normalizar(t)]})
        return entradas
    return _cacheado("referencia", archivos, construir)  # type: ignore[return-value]


def _titulo(texto: str) -> str:
    return texto.split(":", 1)[0].strip() if ":" in texto[:90] else texto[:60]


def puntuar_referencia(entrada: dict, consulta_norm: str) -> float:
    """Frase completa de la consulta igual a un término: 100; término contenido en la consulta: 10 + largo;
    sin coincidencia: 0. Los términos son frases completas entre palabras («xg», «tasa base»)."""
    mejor = 0.0
    for termino in entrada["terminos"]:
        if termino == consulta_norm:
            return 100.0
        if len(termino) >= 2 and _contiene(consulta_norm, termino):
            mejor = max(mejor, 10.0 + len(termino))
    return mejor


def buscar_glosario(termino: str, *, maximo: int = 3) -> dict:
    """Entrada de glosario/guía/FAQ más relevante a `termino`. `estado` = ok | no_encontrado."""
    texto = str(termino or "").strip()[:200]
    if not texto:
        raise ValueError("Indica el término a consultar")
    consulta = normalizar(texto)
    puntuadas = sorted(((puntuar_referencia(e, consulta), e) for e in _entradas_referencia()), key=lambda par: (-par[0], par[1]["clave"]))
    aciertos = [(p, e) for p, e in puntuadas if p > 0][:maximo]
    if not aciertos:
        return {"estado": "no_encontrado", "termino": texto, "terminos_disponibles": sorted({_titulo(e["texto"]) for e in _entradas_referencia() if e["tipo"] == "glosario"}),
                "mensaje": "No tengo una definición de ese término."}
    mejor = aciertos[0][1]
    return {"estado": "ok", "termino": texto, "entrada": {"clave": mejor["clave"], "tipo": mejor["tipo"], "titulo": _titulo(mejor["texto"]), "texto": mejor["texto"]},
            "relacionados": [{"clave": e["clave"], "tipo": e["tipo"], "titulo": _titulo(e["texto"])} for _, e in aciertos[1:]]}


def fragmentos_referencia(consulta: str, maximo: int = 2) -> list[dict]:
    """Entradas de referencia que coinciden con la consulta (para el contexto del agente)."""
    consulta_norm = normalizar(consulta)
    puntuadas = sorted(((puntuar_referencia(e, consulta_norm), e) for e in _entradas_referencia()), key=lambda par: (-par[0], par[1]["clave"]))
    return [{**e, "puntos": p} for p, e in puntuadas if p > 0][:maximo]


# --- Versión del conocimiento ------------------------------------------------------------------

def version_conocimiento() -> dict:
    """Huella de `knowledge/` (ruta+tamaño), cantidad de equipos con perfil y fecha de los datos."""
    archivos = [p for p in dir_conocimiento().glob("**/*.json") if "qa" not in p.relative_to(dir_conocimiento()).parts[:-1]]
    firma = hashlib.sha1()
    ultima = 0.0
    for ruta in sorted(archivos):
        try:
            info = ruta.stat()
        except OSError:
            continue
        firma.update(f"{ruta.relative_to(dir_conocimiento()).as_posix()}:{info.st_size}".encode())
        ultima = max(ultima, info.st_mtime)
    from backend.api.services.conocimiento_equipos import contar_equipos

    catalogo = _catalogo()
    return {
        "version": firma.hexdigest()[:10], "archivos": len(archivos),
        "equipos_con_perfil": contar_equipos(),
        "ligas_cubiertas": sum(1 for liga in ligas_cubiertas() if liga["tipo"] == "liga"),
        "copas_con_tasas": sum(1 for c in COPAS if c in _tasas_base()),
        "datos_hasta": max((e.get("hasta") for e in catalogo.values() if e.get("hasta")), default=None),
        "conocimiento_actualizado": datetime.fromtimestamp(ultima, timezone.utc).date().isoformat() if ultima else None,
    }

