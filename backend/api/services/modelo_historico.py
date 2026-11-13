"""services/modelo_historico.py — módulo `historico` del motor: Dixon-Coles entrenado con histórico.

Usa los artefactos que genera `backend/scripts/evaluar_modelo_historico.py`
(`ml/artefactos/dixon_coles_ligas.json`, opcionalmente `apilador_dc_mercado.json`). Es Python
puro: no necesita numpy/scipy en el servidor. Si los artefactos no existen, o la liga/equipos
no están cubiertos, el módulo simplemente no participa (`validar_historico` devuelve False con
la razón) — nunca inventa una probabilidad.

Por qué existe: en la evaluación walk-forward con 55.557 partidos reales (ver
`EVALUACION_MODELO_HISTORICO_2026-09-29.md`) el Poisson de `pronostico.py` (promedios
de la temporada en curso + ventaja de local fija) quedó claramente por detrás de este modelo
(RPS y log-loss menores en el periodo de prueba) y ambos por detrás del mercado. Con cuotas
disponibles, el apilador combina modelo y mercado.

Cobertura: solo las ligas con histórico descargado (football-data.co.uk: 18 divisiones europeas y 16
países más; NO incluye Chile, Colombia, Arabia Saudita ni Corea — ver `RESUMEN.md`).
La liga se resuelve por nombre; los nombres ambiguos (ej. "Serie B" italiana vs brasileña) se
desambiguan comprobando que AMBOS equipos existan en el modelo de esa liga.
"""
from __future__ import annotations

from datetime import date
import json
import logging
import math
from functools import lru_cache
from pathlib import Path

from backend.api.core.config import settings
from backend.api.ml import dixon_coles, mercado
from backend.api.services._matematica import safe_float
# Reexportados: otros módulos, scripts y pruebas los consumen como `modelo_historico.<nombre>`.
from backend.api.services.modelo_historico_equipos import (  # noqa: F401
    _MAX_CACHE_EQUIPOS, _buscar_equipo, _hay_candidato_ambiguo, _parecido_unico, _resolver_equipo, unir_alias,
)
from backend.api.services.modelo_historico_ligas import (  # noqa: F401
    LIGAS_POR_NOMBRE, _MAX_CACHE_LIGAS, _calcular_ligas_candidatas, _entero, _normalizar_liga, _variantes_liga,
    construir_tabla_ligas,
)
from backend.api.services.modelo_historico_nombres import (  # noqa: F401
    _MAX_LONGITUD_NOMBRE, _Nombre, _acotar, _analizar_nombre, _compatibles, _fusionar_iniciales, _normalizar,
)

log = logging.getLogger("laplace.modelo_historico")

DIR_ARTEFACTOS = Path(__file__).resolve().parents[1] / "ml" / "artefactos"
RUTA_TASAS = Path(__file__).resolve().parents[3] / "backend" / "knowledge" / "sports" / "ligas-estadisticas.json"
DIR_ALIAS = Path(__file__).resolve().parents[1] / "ml" / "alias"
RUTA_ALIAS_LIGAS = DIR_ALIAS / "ligas_alias.json"
RUTA_ALIAS_EQUIPOS_VIVO = DIR_ALIAS / "equipos_alias_vivo.json"
RUTA_ALIAS = Path(__file__).resolve().parents[3] / "backend" / "data" / "datos" / "football-data" / "equipos_alias.json"


def _firma_archivos_modelo() -> tuple[tuple[str, int, int], ...]:
    """Firma de artefactos y aliases para detectar regeneraciones sin reiniciar FastAPI."""
    rutas = (
        DIR_ARTEFACTOS / "dixon_coles_ligas.json",
        DIR_ARTEFACTOS / "apilador_dc_mercado.json",
        RUTA_ALIAS,
        RUTA_ALIAS_LIGAS,
        RUTA_ALIAS_EQUIPOS_VIVO,
    )
    firma = []
    for ruta in rutas:
        try:
            stat = ruta.stat()
            firma.append((str(ruta), stat.st_mtime_ns, stat.st_size))
        except OSError:
            firma.append((str(ruta), -1, -1))
    return tuple(firma)


def _artefactos() -> dict | None:
    # La caché se indexa por firma: una reconstrucción de modelos o aliases en disco pasa a
    # estar disponible en el proceso activo en la siguiente consulta, sin reiniciar el backend.
    return _cargar_artefactos(_firma_archivos_modelo())


@lru_cache(maxsize=2)
def _cargar_artefactos(_firma: tuple[tuple[str, int, int], ...]) -> dict | None:
    ruta = DIR_ARTEFACTOS / "dixon_coles_ligas.json"
    if not ruta.exists():
        return None
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        ligas = {c: dixon_coles.ModeloLiga.de_dict(m) for c, m in crudo["ligas"].items()}
    except (OSError, ValueError, KeyError):
        log.warning("Artefacto de Dixon-Coles ilegible: %s", ruta, exc_info=True)
        return None
    indices = {c: {_normalizar(e): e for e in m.ataque} for c, m in ligas.items()}
    apilador = None
    ruta_ap = DIR_ARTEFACTOS / "apilador_dc_mercado.json"
    if ruta_ap.exists():
        try:
            apilador = json.loads(ruta_ap.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Artefacto del apilador ilegible: %s", ruta_ap, exc_info=True)
    return {"version": crudo.get("version"), "ligas": ligas, "indices": indices, "apilador": apilador,
            "estructura": {c: [(e, _analizar_nombre(e)) for e in m.ataque] for c, m in ligas.items()},
            "alias": _alias_por_liga(), "tabla_ligas": _tabla_ligas(),
            "cache_equipos": {}, "cache_ligas": {}}


# Compatibilidad con el mecanismo de aislamiento de tests y herramientas de diagnóstico.
_artefactos.cache_clear = _cargar_artefactos.cache_clear  # type: ignore[attr-defined]


def _leer_json(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _alias_por_liga() -> dict[str, dict[str, str]]:
    """{liga: {nombre_normalizado_alternativo: nombre_canonico}} desde `equipos_alias.json` (histórico) y
    `ml/alias/equipos_alias_vivo.json` (nombres como los escriben las fuentes en vivo). La clave "*" del
    segundo vale para cualquier liga; el canónico se valida contra el modelo de la liga al resolver."""
    return unir_alias((_leer_json(RUTA_ALIAS).get("mapeo", {}), _leer_json(RUTA_ALIAS_EQUIPOS_VIVO).get("mapeo", {})))


def _tabla_ligas() -> dict:
    """Tabla declarativa de ligas (`ml/alias/ligas_alias.json`) + `LIGAS_POR_NOMBRE` como respaldo."""
    return construir_tabla_ligas(_leer_json(RUTA_ALIAS_LIGAS))


def ligas_candidatas(d: dict) -> list[str]:
    """Códigos de liga del histórico (presentes en el artefacto) que podrían corresponder al partido,
    solo por liga/país/id: aún falta validar los equipos (`validar_historico`)."""
    art = _artefactos()
    if art is None:
        return []
    clave = (_acotar(d.get("liga", "")), _acotar(d.get("pais")), _acotar(d.get("liga_id")))
    if clave not in art["cache_ligas"]:
        if len(art["cache_ligas"]) >= _MAX_CACHE_LIGAS:
            art["cache_ligas"].clear()
        art["cache_ligas"][clave] = _calcular_ligas_candidatas(art, d)
    return art["cache_ligas"][clave]


def _resolver(d: dict) -> tuple[str, dixon_coles.ModeloLiga, str, str] | tuple[None, str]:
    art = _artefactos()
    if art is None:
        return None, "Sin artefactos del modelo histórico (correr evaluar_modelo_historico.py)"
    for codigo in ligas_candidatas(d):
        local = _resolver_equipo(art, codigo, _acotar(d.get("local", "")))
        visitante = _resolver_equipo(art, codigo, _acotar(d.get("visitante", ""))) if local else None
        if local and visitante and local != visitante:
            return codigo, art["ligas"][codigo], local, visitante
    return None, "Liga o equipos fuera de la cobertura del histórico"


# Prior de un equipo ausente del ajuste (ascendido o recién llegado), medido por
# `backend/scripts/evaluar_equipo_nuevo.py` con el periodo de desarrollo (< 2023-07-01) y evaluado en el de
# prueba: con UN equipo desconocido (877 partidos) RPS 0,2198 vs 0,2293 de la tasa base; con AMBOS desconocidos
# (98 partidos) no mejora a la tasa base (0,2196 vs 0,2184) y por eso no se usa. El mercado sigue ganando
# (0,2035 vs 0,2162 en los 326 con cuotas): con cuotas reales se usa solo el mercado y este camino no corre.
PRIOR_EQUIPO_NUEVO_ATAQUE = -0.0725
PRIOR_EQUIPO_NUEVO_DEFENSA = -0.0465
_NOMBRE_EQUIPO_NUEVO = "(equipo sin historial)"


def _resolver_equipo_nuevo(d: dict) -> tuple[str, dixon_coles.ModeloLiga, str | None, str | None] | None:
    """Liga resuelta, exactamente UN equipo resuelto y el otro sin historial claro (ni ambiguo). None si no aplica
    o si hay cuotas reales (con ellas, el mercado solo es lo medido como mejor)."""
    art = _artefactos()
    if art is None or _cuotas(d) is not None:
        return None
    for codigo in ligas_candidatas(d):
        nombres = (_acotar(d.get("local", "")), _acotar(d.get("visitante", "")))
        resueltos = [_resolver_equipo(art, codigo, n) for n in nombres]
        if sum(r is not None for r in resueltos) != 1:
            continue
        faltante = nombres[resueltos.index(None)]
        if _hay_candidato_ambiguo(art, codigo, faltante):
            continue
        return codigo, art["ligas"][codigo], resueltos[0], resueltos[1]
    return None


def validar_historico(d: dict) -> tuple[bool, str]:
    r = _resolver(d)
    if r[0]:
        return True, "ok"
    return (True, "equipo_sin_historial") if _resolver_equipo_nuevo(d) else (False, r[1])


def _cuotas(d: dict) -> tuple[float, float, float] | None:
    h, e, a = (safe_float(d.get(k), 0.0, finito=True) for k in ("odds_local", "odds_empate", "odds_visit"))
    return (h, e, a) if d.get("odds_disponibles") and mercado.cuotas_validas(h, e, a) else None


def _apilar(apilador: dict, pd_: tuple[float, float, float], pm: tuple[float, float, float]) -> tuple[float, float, float]:
    x = [math.log(pd_[0] / pd_[1]), math.log(pd_[2] / pd_[1]), math.log(pm[0] / pm[1]), math.log(pm[2] / pm[1])]
    z = [b + sum(c * v for c, v in zip(fila, x)) for fila, b in zip(apilador["coef"], apilador["intercepto"])]
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return e[0] / s, e[1] / s, e[2] / s


PESO_LAPLACE_EN_MEZCLA = 0.55


def _mezclar_con_laplace(d: dict, dc: tuple[float, float, float]) -> tuple[tuple[float, float, float], dict | None]:
    """Sin cuotas, mezcla lineal 55 % modelo Laplace + 45 % Dixon-Coles (MB-12). Medido el 2026-11-11 sobre 43.602 partidos (peso elegido en la primera mitad de la prueba, medido en la segunda):
    Dixon-Coles 1,0205, Laplace 1,0191, mezcla 1,0179 de log loss (−0,0012 frente a Laplace solo, z = 3,0). Con cuotas no se toca: el apilador ya ancla al mercado. Si el modelo no cubre el partido, queda Dixon-Coles."""
    from backend.api.ml.laplace import servicio

    propio = servicio.pronostico_propio({"local": d.get("local", ""), "visitante": d.get("visitante", ""), "liga": d.get("liga", ""), "pais": d.get("pais"), "liga_id": d.get("liga_id")})
    if not propio or "p1x2" not in propio:
        return dc, None
    p = propio["p1x2"]
    lap = (p["local"], p["empate"], p["visitante"])
    mezcla = tuple(PESO_LAPLACE_EN_MEZCLA * a + (1 - PESO_LAPLACE_EN_MEZCLA) * b for a, b in zip(lap, dc))
    return mezcla, {"peso": PESO_LAPLACE_EN_MEZCLA, "version": (propio.get("modelo") or {}).get("version")}  # type: ignore[return-value]


def analizar(d: dict) -> dict:
    """Mismo contrato que los demás módulos: `ok`, `pick`, `prob_*`, `confianza_score`. Con cuotas
    reales del partido combina modelo y mercado (apilador); sin ellas usa solo Dixon-Coles."""
    r = _resolver(d)
    equipo_nuevo = False
    if not r[0]:
        nuevo = _resolver_equipo_nuevo(d)
        if not nuevo:
            return {"ok": False, "razon": r[1]}
        r, equipo_nuevo = nuevo, True
    codigo, modelo, local, visitante = r  # type: ignore[misc]
    lam_h, lam_a, _ = dixon_coles.lambdas(modelo, local or _NOMBRE_EQUIPO_NUEVO, visitante or _NOMBRE_EQUIPO_NUEVO)
    if equipo_nuevo:
        if local is None:
            lam_h, lam_a = lam_h * math.exp(PRIOR_EQUIPO_NUEVO_ATAQUE), lam_a * math.exp(-PRIOR_EQUIPO_NUEVO_DEFENSA)
        else:
            lam_a, lam_h = lam_a * math.exp(PRIOR_EQUIPO_NUEVO_ATAQUE), lam_h * math.exp(-PRIOR_EQUIPO_NUEVO_DEFENSA)
    probs = dixon_coles.probabilidades_desde_lambdas(lam_h, lam_a, modelo.rho)
    metodo = "dixon_coles_equipo_nuevo" if equipo_nuevo else "dixon_coles"

    art = _artefactos()
    cuotas = _cuotas(d)
    mezcla_laplace = None
    if not cuotas and not equipo_nuevo and settings.CONSENSO_HISTORICO_CON_LAPLACE:
        probs, mezcla_laplace = _mezclar_con_laplace(d, probs)
        if mezcla_laplace:
            metodo = "dixon_coles_mas_laplace"
    if cuotas and art and art.get("apilador"):
        probs = _apilar(art["apilador"], probs, mercado.quitar_margen_shin(*cuotas))
        metodo = "dc_mas_mercado"

    etiquetas = ("Local", "Empate", "Visitante")
    mejor = max(range(3), key=lambda i: probs[i])
    confianza_score = int(max(25, min(80, 40 + 100 * (probs[mejor] - 1 / 3))))
    # Antigüedad de los ratings (2026-10-07). Medido con datos reales (14 ligas, cortes 2019/2021/2022):
    # sin reajustar, Dixon-Coles sigue superando a la tasa base incluso a 3 años (RPS 0,2141 vs 0,2263),
    # pero pierde ~0,005 de RPS frente a reajustarlo. Sirve, pero la confianza baja y se avisa.
    edad_dias = (date.today().toordinal() - modelo.fecha_corte) if modelo.fecha_corte else None
    if edad_dias is not None and edad_dias > 730:
        confianza_score = max(25, confianza_score - 10)
    elif edad_dias is not None and edad_dias > 365:
        confianza_score = max(25, confianza_score - 5)
    if equipo_nuevo:
        # Un solo equipo conocido: la fuerza del otro es un promedio de equipos nuevos, no un dato suyo.
        confianza_score = min(confianza_score, 35)
    return {
        "ok": True, "modulo": "historico", "metodo": metodo, "liga_codigo": codigo, "equipo_sin_historial": equipo_nuevo,
        "edad_modelo_dias": edad_dias, "modelo_desactualizado": bool(edad_dias is not None and edad_dias > 365),
        "pick": etiquetas[mejor],
        "prob_local": round(probs[0], 4), "prob_empate": round(probs[1], 4), "prob_visitante": round(probs[2], 4),
        "lambda_local": round(lam_h, 3), "lambda_visit": round(lam_a, 3),
        "muestra_ajuste": modelo.n_partidos, "laplace_en_mezcla": mezcla_laplace,
        "confianza_score": confianza_score,
        "confianza": "ALTA" if confianza_score >= 65 else "MEDIA" if confianza_score >= 45 else "BAJA",
    }


@lru_cache(maxsize=1)
def _tasas_por_liga() -> dict[str, dict]:
    """{codigo_liga: metadata} de `knowledge/sports/ligas-estadisticas.json` (lo genera
    `backend/scripts/generar_conocimiento_ligas.py` con datos reales medidos)."""
    try:
        entradas = json.loads(RUTA_TASAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {e["metadata"]["liga_codigo"]: e["metadata"] for e in entradas if "liga_codigo" in e.get("metadata", {})}


def tasas_base_liga(d: dict) -> dict | None:
    """Tasas históricas reales de la liga del partido, o None si la liga no está cubierta.

    Solo se devuelven cuando AMBOS equipos se reconocen en esa liga (`_resolver`), así una
    "Serie B" brasileña nunca recibe las tasas de la italiana solo por compartir nombre."""
    r = _resolver(d)
    return _tasas_por_liga().get(r[0]) if r[0] else None


def resumen_tasa_base(d: dict) -> dict | None:
    """Tasas históricas reales de la liga del partido en forma lista para mostrar al usuario (web, app,
    Telegram), o None si la liga no está cubierta o los equipos no se reconocen. Nunca inventa."""
    meta = tasas_base_liga(d)
    if not meta:
        return None
    return {
        "liga_codigo": meta.get("liga_codigo"), "partidos": meta.get("partidos"), "temporadas": meta.get("temporadas"),
        "pct_local": meta.get("pct_local"), "pct_empate": meta.get("pct_empate"), "pct_visitante": meta.get("pct_visitante"),
        "goles_por_partido": meta.get("goles_por_partido"), "fuente": "football-data.co.uk (histórico medido)",
    }


# Promedio mundial medido de resultados de fútbol (documentado en `form_recent.py`): último recurso cuando ni
# siquiera la liga se reconoce. Se rotula como "general", nunca como dato de esa liga.
_TASA_GENERAL_RESPALDO = {"pct_local": 44.1, "pct_empate": 26.3, "pct_visitante": 29.6}


def _tasa_general() -> dict:
    """Promedio ponderado por partidos de todas las ligas con conocimiento medido; el respaldo fijo si no hay."""
    tasas = _tasas_por_liga().values()
    total = sum(t.get("partidos") or 0 for t in tasas)
    if not total:
        return {**_TASA_GENERAL_RESPALDO, "partidos": None}
    return {
        **{k: round(sum((t.get(k) or 0) * (t.get("partidos") or 0) for t in tasas) / total, 1) for k in _TASA_GENERAL_RESPALDO},
        "partidos": total,
    }


def referencia_sin_pronostico(d: dict) -> dict:
    """Contexto honesto cuando no hay pronóstico propio: frecuencias históricas de la liga del partido (basta con
    reconocer la liga, no hace falta conocer a los equipos) o, si ni la liga se reconoce, el promedio general.
    Es una REFERENCIA, no un pronóstico: no distingue a los dos equipos. Siempre devuelve algo."""
    candidatas = ligas_candidatas(d)
    meta = _tasas_por_liga().get(candidatas[0]) if len(candidatas) == 1 else None
    if meta:
        return {
            "nivel": "liga", "liga_codigo": meta.get("liga_codigo"), "partidos": meta.get("partidos"),
            "pct_local": meta.get("pct_local"), "pct_empate": meta.get("pct_empate"),
            "pct_visitante": meta.get("pct_visitante"), "datos_hasta": meta.get("datos_hasta"),
            "fuente": "football-data.co.uk (histórico medido)",
        }
    return {"nivel": "general", "liga_codigo": None, **_tasa_general(), "datos_hasta": None,
            "fuente": "promedio de las ligas con histórico medido"}


def motivos_sin_historico(d: dict) -> list[str]:
    """Por qué `historico` no pudo responder, en lenguaje llano y sin inventar: sirve para explicar el 'sin pronóstico'."""
    if validar_historico(d)[0]:
        return []
    if _artefactos() is None:
        return ["el modelo histórico no está disponible"]
    if not ligas_candidatas(d):
        return ["la liga no está en el histórico del bot"]
    return ["algún equipo no figura en el histórico de su liga (o son dos equipos nuevos a la vez)"]

