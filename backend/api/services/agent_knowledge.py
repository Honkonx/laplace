"""Conocimiento declarativo del agente: sincronización desde `knowledge/` y recuperación por relevancia.

- La sincronización excluye `knowledge/qa/` (casos de prueba, no conocimiento), exige
  `namespace`, `topic_key` y `content` no vacíos, y solo corre cuando cambian los archivos
  (firma por ruta+mtime+tamaño, por base de datos), no en cada request.
- Las entradas que dejan de existir en los JSON se retiran marcándolas inactivas
  (`metadata_json.inactive = true`); nunca se borran filas.
- Los perfiles de equipo (`knowledge/sports/equipos-*.json`, ~925 equipos, ~2,7 MB) NO se cargan en
  la tabla: cada consulta de chat recorre toda la tabla y esos perfiles solo se piden por equipo, así
  que `conocimiento_equipos` los lee bajo demanda de los archivos (con caché por firma).
- La recuperación (`recuperar_conocimiento`) puntúa por relevancia: equipo mencionado (perfil), liga
  mencionada (tasas base), término de glosario/guía/FAQ y coincidencia de palabras; devuelve un bloque
  acotado en caracteres, marcado como dato de referencia no instruccional.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.models.agent_runtime import AgentKnowledge
from backend.api.services import conocimiento_equipos, conocimiento_referencia

log = logging.getLogger("laplace.agent_knowledge")

NAMESPACES_CONTEXTO = ("general", "laplace", "futbol")
EXCLUIDOS = {"qa"}
MAX_CARACTERES_CONOCIMIENTO = 4000  # ~1000 tokens
_FIRMAS: "weakref.WeakKeyDictionary[object, tuple]" = weakref.WeakKeyDictionary()
_STOPWORDS = {"de", "la", "el", "los", "las", "un", "una", "que", "y", "en", "con", "por", "para", "del", "al", "vs", "versus", "contra", "hoy", "manana", "predice", "prediccion", "bot", "analiza", "pronostico", "liga", "ligas", "partido", "partidos", "futbol", "cuota", "cuotas", "tasa", "base", "dime", "dame", "quien", "gana", "cual", "como"}
# Entradas que se incluyen siempre (poco texto, definen el alcance del agente).
BASE_SIEMPRE = {("general", "scope"), ("laplace", "modes")}
PUNTOS_EQUIPO, PUNTOS_LIGA, PUNTOS_BASE = 100.0, 60.0, 0.0


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _archivos_conocimiento() -> list[Path]:
    root = settings.repo_root / "backend" / "knowledge"
    return sorted(p for p in root.glob("**/*.json") if not (set(p.relative_to(root).parts[:-1]) & EXCLUIDOS) and not p.name.startswith("equipos-"))


def _firma(archivos: list[Path]) -> tuple:
    firma = []
    for ruta in archivos:
        try:
            info = ruta.stat()
            firma.append((str(ruta), info.st_mtime_ns, info.st_size))
        except OSError:
            continue
    return tuple(firma)


def _meta(fila: AgentKnowledge) -> dict:
    try:
        valor = json.loads(fila.metadata_json or "{}")
    except ValueError:
        return {}
    return valor if isinstance(valor, dict) else {}


def esta_activo(fila: AgentKnowledge) -> bool:
    return not _meta(fila).get("inactive")


def _entradas_validas(ruta: Path) -> tuple[list[dict], int]:
    try:
        data = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("No se pudo leer conocimiento JSON %s: %s", ruta, exc)
        return [], 0
    entradas = data if isinstance(data, list) else data.get("entries", []) if isinstance(data, dict) else []
    validas, descartadas = [], 0
    for item in entradas:
        if not isinstance(item, dict):
            descartadas += 1
            continue
        campos = {k: str(item.get(k, "")).strip() for k in ("namespace", "topic_key", "content")}
        if not all(campos.values()):
            descartadas += 1
            continue
        validas.append({**campos, "source": str(item.get("source", ruta.name)), "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {}})
    if descartadas:
        log.warning("%s: %d entradas descartadas por faltar namespace/topic_key/content", ruta.name, descartadas)
    return validas, descartadas


def sincronizar_conocimiento_json(db: Session, *, forzar: bool = False) -> int:
    """Carga `knowledge/**/*.json` (salvo `qa/`) y retira lo obsoleto. Devuelve filas creadas."""
    archivos = _archivos_conocimiento()
    firma = _firma(archivos)
    motor = db.get_bind()
    if not forzar:
        try:
            if _FIRMAS.get(motor) == firma:
                return 0
        except TypeError:
            pass
    root = settings.repo_root / "backend" / "knowledge"
    ahora = _ahora()
    creados = 0
    vistos: set[tuple[str, str]] = set()
    existentes = {(f.namespace, f.topic_key): f for f in db.query(AgentKnowledge).all()}
    for ruta in archivos:
        origen = ruta.relative_to(root).as_posix()
        entradas, _ = _entradas_validas(ruta)
        for item in entradas:
            clave = (item["namespace"], item["topic_key"])
            vistos.add(clave)
            metadata = {**item["metadata"], "sync_file": origen}
            fila = existentes.get(clave)
            if fila is None:
                fila = AgentKnowledge(namespace=clave[0], topic_key=clave[1], content=item["content"], source=item["source"], metadata_json=json.dumps(metadata, ensure_ascii=False), creado_en=ahora, actualizado_en=ahora)
                db.add(fila)
                existentes[clave] = fila
                creados += 1
                continue
            nuevo_meta = json.dumps(metadata, ensure_ascii=False)
            if (fila.content, fila.source, fila.metadata_json) != (item["content"], item["source"], nuevo_meta):
                fila.content, fila.source, fila.metadata_json, fila.actualizado_en = item["content"], item["source"], nuevo_meta, ahora
    for clave, fila in existentes.items():
        if clave in vistos or not esta_activo(fila):
            continue
        meta = _meta(fila)
        vacia = not (fila.content or "").strip()
        if vacia or meta.get("sync_file"):
            meta.update({"inactive": True, "inactive_reason": "contenido vacío" if vacia else "ya no está en knowledge/", "inactive_at": ahora})
            fila.metadata_json = json.dumps(meta, ensure_ascii=False)
            fila.actualizado_en = ahora
    db.commit()
    try:
        _FIRMAS[motor] = firma
    except TypeError:
        pass
    return creados


# --- Recuperación por relevancia ---------------------------------------------------------------

def _normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", plano)


def _terminos(consulta: str) -> set[str]:
    return {t for t in _normalizar(consulta).split() if len(t) >= 3 and t not in _STOPWORDS}


def puntuar(fila: AgentKnowledge, terminos: set[str], codigos: set[str], consulta_norm: str = "") -> float:
    """Relevancia de una entrada para la consulta.

    Suma: frase de glosario/guía/FAQ (`metadata.terminos`) contenida en la consulta, liga mencionada
    (`metadata.liga_codigo`) y palabras de la consulta en el topic/contenido (más peso en el encabezado)."""
    meta = _meta(fila)
    puntos = 0.0
    if consulta_norm and meta.get("terminos"):
        puntos += conocimiento_referencia.puntuar_referencia({"terminos": [conocimiento_referencia.normalizar(t) for t in meta["terminos"]]}, consulta_norm)
    if str(meta.get("liga_codigo", "")) in codigos:
        puntos += PUNTOS_LIGA
    if not terminos:
        return puntos
    cabecera = _normalizar(f"{fila.topic_key} {(fila.content or '')[:120]}").split()
    cuerpo = set(_normalizar(fila.content or "").split())
    return puntos + sum(2.0 for t in terminos if t in cabecera) + sum(0.5 for t in terminos if t in cuerpo)


def _codigos_liga(consulta: str) -> set[str]:
    detectada = conocimiento_referencia.detectar_ligas(consulta)
    return set() if detectada.ambiguo and len(detectada.codigos) > 3 else set(detectada.codigos)


def _filas_activas(db: Session) -> list[AgentKnowledge]:
    filas = db.query(AgentKnowledge).filter(AgentKnowledge.namespace.in_(NAMESPACES_CONTEXTO)).order_by(AgentKnowledge.namespace, AgentKnowledge.topic_key).all()
    return [f for f in filas if esta_activo(f)]


def _puntuadas(db: Session, consulta: str) -> tuple[list[AgentKnowledge], list[tuple[float, AgentKnowledge]]]:
    filas = _filas_activas(db)
    terminos, codigos, consulta_norm = _terminos(consulta), _codigos_liga(consulta), _normalizar(consulta).strip()
    base = [f for f in filas if (f.namespace, f.topic_key) in BASE_SIEMPRE]
    puntuadas = sorted(((puntuar(f, terminos, codigos, consulta_norm), f) for f in filas if f not in base), key=lambda par: -par[0])
    return base, [par for par in puntuadas if par[0] > 0]


def seleccionar_conocimiento(db: Session, consulta: str, *, max_entradas: int = 6, max_caracteres: int = MAX_CARACTERES_CONOCIMIENTO) -> list[AgentKnowledge]:
    """Entradas de la tabla relevantes a la consulta (base + las mejor puntuadas), acotadas en caracteres."""
    base, puntuadas = _puntuadas(db, consulta)
    elegidas = [*base, *(fila for _, fila in puntuadas)][:max(max_entradas, len(base))]
    resultado, usados = [], 0
    for fila in elegidas:
        usados += len(fila.content or "")
        if usados > max_caracteres and resultado:
            break
        resultado.append(fila)
    return resultado


@dataclass(frozen=True)
class Fragmento:
    """Pieza de conocimiento para el contexto: viene de la tabla o de un perfil de equipo leído bajo demanda."""
    namespace: str
    topic_key: str
    content: str
    tipo: str
    puntos: float


def recuperar_conocimiento(db: Session, consulta: str, *, max_entradas: int = 6, max_caracteres: int = MAX_CARACTERES_CONOCIMIENTO) -> list[Fragmento]:
    """Perfil(es) de los equipos mencionados + entradas de la tabla por relevancia, con tope de caracteres.

    Orden: base, equipos mencionados («cómo viene Colo-Colo»), y luego liga/glosario/guías por puntuación.
    Equipo ambiguo («River») no se inyecta: no se adivina."""
    base, puntuadas = _puntuadas(db, consulta)
    candidatos = [Fragmento(f.namespace, f.topic_key, f.content or "", "base", PUNTOS_BASE) for f in base]
    for hallazgo in conocimiento_equipos.detectar_equipos_en_texto(consulta, maximo=2):
        fragmento = conocimiento_equipos.fragmento_equipo(hallazgo["club"])
        candidatos.append(Fragmento(fragmento["namespace"], fragmento["topic_key"], fragmento["content"], "equipo", PUNTOS_EQUIPO))
    candidatos += [Fragmento(f.namespace, f.topic_key, f.content or "", "tabla", puntos) for puntos, f in puntuadas]
    elegidos, usados = [], 0
    for fragmento in candidatos[:max(max_entradas, len(base))]:
        usados += len(fragmento.content)
        if usados > max_caracteres and elegidos and fragmento.tipo != "base":
            break
        elegidos.append(fragmento)
    return elegidos
