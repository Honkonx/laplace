"""liga.py — simulación Monte Carlo de temporadas, escenarios y caminos exactos (MM-22, MM-23, MM-24).

PYTHON PURO (solo librería estándar): el servidor no tiene numpy. Este módulo NO consulta ningún modelo: recibe
las lambdas (goles esperados) de cada partido pendiente y calcula tabla final, posiciones y cupos.

Decisiones de la versión 1 (ver `supuestos` y `limitaciones` en la salida):
- Los goles se muestrean con Poisson INDEPENDIENTE por inversión de la CDF precalculada (la corrección de
  Dixon-Coles `rho` solo se usa en `enumerar_caminos`, donde sale de la matriz de goles exacta).
- Reproducible: `random.Random(semilla)`; misma entrada y semilla => misma salida byte a byte.
- Desempate final de la tabla: sorteo aleatorio uniforme (no el orden alfabético, que sesgaría a favor de un
  nombre); la regla "enfrentamiento directo" no está implementada.
- `validado` es siempre False: no se declara fiable hasta un backtest de temporadas (MM-25).
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from pathlib import Path
from bisect import bisect_right
from collections.abc import Callable
from typing import Any

from backend.api.ml.laplace import motor_go, motor_rust

from backend.api.ml.laplace.pronostico import matriz_goles, resumen_matriz

MAX_SIMULACIONES = 20_000
MAX_EQUIPOS = 24
MAX_PENDIENTES = 500
MAX_FIJOS = 20
MAX_CAMINOS_PARTIDOS = 8
MAX_CAMINOS_DEVUELTOS = 50
MAX_NOMBRE = 120
LAMBDA_MAX = 10.0
APROVECHAMIENTO_MINIMO = 0.05
DESEMPATES_PERMITIDOS = ("puntos", "diferencia_goles", "goles_favor")
DESEMPATES_POR_DEFECTO = DESEMPATES_PERMITIDOS
VERSION_API = "ml-2"

Lambdas = dict[tuple[str, str], tuple[float, float]] | Callable[[str, str], tuple[float, float]]


class ErrorEntrada(ValueError):
    """Error cerrado de entrada: `codigo` ∈ {entrada_invalida, limite_excedido, datos_insuficientes}."""

    def __init__(self, codigo: str, campo: str, mensaje: str, maximo: float | None = None, corregible: bool = True):
        super().__init__(mensaje)
        self.codigo = codigo
        self.campo = campo
        self.maximo = maximo
        self.corregible = corregible

    def como_dict(self) -> dict:
        return {"ok": False, "error": self.codigo, "campo": self.campo, "maximo": self.maximo,
                "corregible": self.corregible, "mensaje": str(self)}


def _invalida(campo: str, mensaje: str) -> ErrorEntrada:
    return ErrorEntrada("entrada_invalida", campo, mensaje)


def _excedido(campo: str, mensaje: str, maximo: float) -> ErrorEntrada:
    return ErrorEntrada("limite_excedido", campo, mensaje, maximo=maximo)


def _es_entero(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _huella(obj: Any) -> str:
    texto = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ───────────────────────────── validación ─────────────────────────────

def _validar_tabla(tabla: Any) -> list[dict]:
    if not isinstance(tabla, (list, tuple)) or not tabla:
        raise _invalida("tabla", "la tabla debe ser una lista no vacía")
    if len(tabla) > MAX_EQUIPOS:
        raise _excedido("tabla", f"hay más de {MAX_EQUIPOS} equipos", MAX_EQUIPOS)
    filas, vistos = [], set()
    for i, f in enumerate(tabla):
        if not isinstance(f, dict):
            raise _invalida(f"tabla[{i}]", "cada fila debe ser un objeto")
        nombre = f.get("equipo")
        if not isinstance(nombre, str) or not nombre.strip():
            raise _invalida(f"tabla[{i}].equipo", "el nombre del equipo no puede estar vacío")
        if len(nombre) > MAX_NOMBRE:
            raise _excedido(f"tabla[{i}].equipo", "nombre de equipo demasiado largo", MAX_NOMBRE)
        if nombre in vistos:
            raise _invalida(f"tabla[{i}].equipo", f"nombre de equipo repetido: {nombre}")
        vistos.add(nombre)
        fila = {"equipo": nombre}
        for campo in ("pj", "pts", "gf", "gc"):
            v = f.get(campo)
            if not _es_entero(v) or v < 0:
                raise _invalida(f"tabla[{i}].{campo}", f"{campo} debe ser un entero >= 0")
            fila[campo] = v
        filas.append(fila)
    return filas


def _validar_pendientes(pendientes: Any, equipos: set[str], campo: str = "pendientes") -> list[tuple[str, str]]:
    if not isinstance(pendientes, (list, tuple)):
        raise _invalida(campo, "pendientes debe ser una lista")
    if len(pendientes) > MAX_PENDIENTES:
        raise _excedido(campo, f"hay más de {MAX_PENDIENTES} partidos pendientes", MAX_PENDIENTES)
    pares = []
    for i, p in enumerate(pendientes):
        if not isinstance(p, dict):
            raise _invalida(f"{campo}[{i}]", "cada partido debe ser un objeto")
        local, visitante = p.get("local"), p.get("visitante")
        for lado, nombre in (("local", local), ("visitante", visitante)):
            if nombre not in equipos:
                raise _invalida(f"{campo}[{i}].{lado}", f"equipo desconocido: {nombre!r}")
        if local == visitante:
            raise _invalida(f"{campo}[{i}]", "un equipo no juega contra sí mismo")
        pares.append((local, visitante))
    return pares


def _validar_desempates(desempates: Any) -> tuple[str, ...]:
    if not isinstance(desempates, (list, tuple)) or not desempates:
        raise _invalida("desempates", "desempates debe ser una lista no vacía")
    if len(set(desempates)) != len(desempates) or any(d not in DESEMPATES_PERMITIDOS for d in desempates):
        raise _invalida("desempates", f"solo se permiten, sin repetir: {', '.join(DESEMPATES_PERMITIDOS)}")
    if desempates[0] != "puntos":
        raise _invalida("desempates", "el primer criterio debe ser 'puntos'")
    return tuple(desempates)


def _validar_cupos(cupos: Any, n_equipos: int) -> list[dict]:
    if cupos is None:
        return []
    if not isinstance(cupos, (list, tuple)):
        raise _invalida("cupos", "cupos debe ser una lista")
    salida, etiquetas = [], set()
    for i, c in enumerate(cupos):
        et = c.get("etiqueta") if isinstance(c, dict) else None
        pos = c.get("posiciones") if isinstance(c, dict) else None
        if not isinstance(et, str) or not et.strip() or et in etiquetas:
            raise _invalida(f"cupos[{i}].etiqueta", "etiqueta vacía o repetida")
        if (not isinstance(pos, (list, tuple)) or len(pos) != 2 or not all(_es_entero(x) for x in pos)
                or not 1 <= pos[0] <= pos[1] <= n_equipos):
            raise _invalida(f"cupos[{i}].posiciones", f"debe ser [desde, hasta] dentro de 1..{n_equipos}")
        etiquetas.add(et)
        salida.append({"etiqueta": et, "posiciones": [pos[0], pos[1]]})
    return salida


def _validar_parametros(n_sim: Any, semilla: Any) -> None:
    if not _es_entero(n_sim) or n_sim < 1:
        raise _invalida("n_sim", "n_sim debe ser un entero >= 1")
    if n_sim > MAX_SIMULACIONES:
        raise _excedido("n_sim", f"n_sim supera {MAX_SIMULACIONES}", MAX_SIMULACIONES)
    if not _es_entero(semilla):
        raise _invalida("semilla", "la semilla debe ser un entero")


def _resolver_lambdas(lambdas: Lambdas, pares: list[tuple[str, str]]) -> list[tuple[float, float]]:
    salida = []
    for i, (local, visitante) in enumerate(pares):
        try:
            par = lambdas(local, visitante) if callable(lambdas) else lambdas[(local, visitante)]
            lam_h, lam_a = float(par[0]), float(par[1])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise _invalida(f"lambdas[{local} vs {visitante}]", "faltan o son inválidas las lambdas del partido") from exc
        for lado, lam in (("local", lam_h), ("visitante", lam_a)):
            if not (math.isfinite(lam) and 0 < lam < LAMBDA_MAX):
                raise _invalida(f"lambdas[{local} vs {visitante}].{lado}", f"lambda fuera de (0, {LAMBDA_MAX:g})")
        salida.append((lam_h, lam_a))
    return salida


# ───────────────────────────── muestreo ─────────────────────────────

def _cdf_poisson(lam: float) -> list[float]:
    """CDF acumulada de Poisson(lam) truncada donde la cola es < 1e-13; el último valor queda en 1.0."""
    p = math.exp(-lam)
    acum, cdf, k = p, [p], 0
    while acum < 1 - 1e-13 and k < 80:
        k += 1
        p *= lam / k
        acum += p
        cdf.append(acum)
    cdf[-1] = 1.0
    return cdf


def _ranking(n: int, pts: list[int], gf: list[int], gc: list[int], desempates: tuple[str, ...],
             sorteo: list[float]) -> list[int]:
    """Índices de equipos de la 1.ª a la última posición; empates totales se resuelven con `sorteo`."""
    def clave(i: int) -> tuple:
        valores = {"puntos": pts[i], "diferencia_goles": gf[i] - gc[i], "goles_favor": gf[i]}
        return (*(-valores[d] for d in desempates), sorteo[i])
    return sorted(range(n), key=clave)


def _percentil(ordenado: list[int], q: float) -> int:
    return ordenado[min(len(ordenado) - 1, int(q * (len(ordenado) - 1) + 0.5))]


PASO_FUERZA = 0.05
PRESUPUESTO_PYTHON = 5_000_000  # tope interno del bucle en Python (≈ 5 s): si Go falla, un pedido aprobado para Go no puede dejar a Python trabajando minutos


def motor_nativo_disponible() -> bool:
    return motor_rust.disponible() or motor_go.disponible()


def motor_para(filtros: dict) -> str:
    """El primero disponible de la cadena Rust → Go → Python; con filtros (funciones de Python) siempre `python`."""
    if filtros:
        return "python"
    return "rust" if motor_rust.disponible() else "go" if motor_go.disponible() else "python"


SIGMA_FUERZA_DEFECTO = 0.12  # elegido con el backtest de temporadas (57 temporadas de 10 ligas europeas: cobertura p05–p95 de 0,839 con 0 → ≈ 0,90 con 0,12)
RUTA_BACKTEST = Path(__file__).resolve().parents[4] / "backend" / "data" / "resultados" / "backtest_temporadas.json"


def _nucleo(filas: list[dict], pares: list[tuple[str, str]], lams: list[tuple[float, float]], n_sim: int,
            semilla: int, desempates: tuple[str, ...], fijos: dict[int, tuple[int, int]],
            filtros: dict[int, Callable[[int, int], bool]], sigma_fuerza: float = 0.0, motor: str = "python", usado: dict | None = None) -> tuple[list[list[int]], list[list[int]], int]:
    """Bucle Monte Carlo. Devuelve (conteo de posiciones por equipo, puntos finales por equipo, simulaciones útiles).

    `usado` (opcional) recibe `{"motor": …}` con el motor que REALMENTE corrió: si el pedido era Rust y cayó a Go o a Python, la respuesta lo declara.

    Siempre consume los mismos números aleatorios por simulación (aunque el partido esté fijado o la simulación se
    descarte), de modo que base y escenario con la misma semilla comparten aleatorios comunes.
    """
    n = len(filas)
    indice = {f["equipo"]: i for i, f in enumerate(filas)}
    if motor in ("rust", "go") and not filtros:  # núcleos nativos: Rust primero, Go de respaldo; sin ellos o ante cualquier fallo se sigue en Python
        args = ([{"pts": f["pts"], "gf": f["gf"], "gc": f["gc"]} for f in filas],
                [{"h": indice[loc], "a": indice[vis], "lh": lh, "la": la, "fijo": list(fijos[k]) if k in fijos else None} for k, ((loc, vis), (lh, la)) in enumerate(zip(pares, lams, strict=True))],
                n_sim, semilla, desempates, sigma_fuerza, PASO_FUERZA)
        for nombre, nucleo in (("rust", motor_rust), ("go", motor_go)):
            if motor == "go" and nombre == "rust":
                continue  # un motor pedido explícitamente como Go no pasa por Rust
            try:
                resultado = nucleo.correr(*args)
                if usado is not None:
                    usado["motor"] = nombre
                return resultado
            except motor_go.MotorNoDisponible:  # la misma clase para los dos
                continue
    if usado is not None:
        usado["motor"] = "python"
    if n_sim * max(1, len(pares)) > PRESUPUESTO_PYTHON:
        raise _excedido("n_sim", f"n_sim × partidos pendientes supera el presupuesto de {PRESUPUESTO_PYTHON} sorteos del cálculo en Python (el núcleo en Go no estuvo disponible)", PRESUPUESTO_PYTHON // max(1, len(pares)))
    cdfs: dict[float, list[float]] = {}

    def cdf(lam: float) -> list[float]:
        if lam not in cdfs:
            cdfs[lam] = _cdf_poisson(lam)
        return cdfs[lam]

    partidos = [(indice[loc], indice[vis], cdf(lh), cdf(la), fijos.get(k), filtros.get(k))
                for k, ((loc, vis), (lh, la)) in enumerate(zip(pares, lams, strict=True))]
    crudas = list(lams)
    cdfs_fuerza: dict[tuple[int, int], tuple[list[float], list[float]]] = {}
    rng_fuerza = random.Random(semilla + 7919)  # flujo aparte: el principal no cambia con sigma = 0
    pts0 = [f["pts"] for f in filas]
    gf0 = [f["gf"] for f in filas]
    gc0 = [f["gc"] for f in filas]
    conteo = [[0] * n for _ in range(n)]
    puntos: list[list[int]] = [[] for _ in range(n)]
    rnd = random.Random(semilla).random
    utiles = 0
    for _ in range(n_sim):
        pts, gf, gc = pts0[:], gf0[:], gc0[:]
        valida = True
        # incertidumbre de la fuerza de cada equipo (los parámetros del modelo no son exactos): cada simulación sortea un desvío por equipo, en pasos de 0,05 en log
        niveles = [round(rng_fuerza.gauss(0.0, sigma_fuerza) / PASO_FUERZA) for _ in range(n)] if sigma_fuerza > 0 else None
        for k, (ih, ia, ch, ca, fijo, filtro) in enumerate(partidos):
            if niveles is not None:
                d = max(-12, min(12, niveles[ih] - niveles[ia]))
                par = cdfs_fuerza.get((k, d))
                if par is None:
                    f = math.exp(PASO_FUERZA * d)
                    par = cdfs_fuerza[(k, d)] = (_cdf_poisson(min(crudas[k][0] * f, LAMBDA_MAX * 0.999)), _cdf_poisson(min(crudas[k][1] / f, LAMBDA_MAX * 0.999)))
                ch, ca = par
            a = bisect_right(ch, rnd())
            b = bisect_right(ca, rnd())
            if fijo is not None:
                a, b = fijo
            if filtro is not None and not filtro(a, b):
                valida = False
            gf[ih] += a
            gc[ih] += b
            gf[ia] += b
            gc[ia] += a
            if a > b:
                pts[ih] += 3
            elif a < b:
                pts[ia] += 3
            else:
                pts[ih] += 1
                pts[ia] += 1
        sorteo = [rnd() for _ in range(n)]
        if not valida:
            continue
        utiles += 1
        for pos, i in enumerate(_ranking(n, pts, gf, gc, desempates, sorteo)):
            conteo[i][pos] += 1
            puntos[i].append(pts[i])
    return conteo, puntos, utiles


def _resumir(filas: list[dict], conteo: list[list[int]], puntos: list[list[int]], utiles: int,
             cupos: list[dict]) -> tuple[dict, float]:
    posiciones, pts_res, eventos = {}, {}, {}
    p_max = 0.0
    for i, f in enumerate(filas):
        e = f["equipo"]
        probs = [c / utiles for c in conteo[i]]
        posiciones[e] = probs
        ordenado = sorted(puntos[i])
        pts_res[e] = {"media": sum(ordenado) / utiles, "p05": _percentil(ordenado, 0.05),
                      "p50": _percentil(ordenado, 0.50), "p95": _percentil(ordenado, 0.95)}
        eventos[e] = {c["etiqueta"]: sum(probs[c["posiciones"][0] - 1:c["posiciones"][1]]) for c in cupos}
        p_max = max(p_max, *(p * (1 - p) for p in [*probs, *eventos[e].values()]))
    error = math.sqrt(p_max / utiles)  # error estándar máximo sqrt(p(1-p)/n) sobre todos los eventos
    return {"posiciones": posiciones, "puntos": pts_res, "eventos": eventos}, error


SUPUESTOS = [
    "goles Poisson independientes con lambdas fijas por partido (sin corrección rho en el muestreo)",
    "independencia entre partidos",
    "sin lesiones, sanciones ni cambios de plantel",
    "empate total en la tabla resuelto por sorteo uniforme (sin enfrentamiento directo)",
]
LIMITACIONES = [
    "no se propaga la incertidumbre de los parámetros del modelo",
    "no validado con backtest de temporadas: no usar para decisiones",
]


def _backtest_vigente(sigma: float) -> dict | None:
    """Resumen del backtest de temporadas si existe EN ESTA MÁQUINA y se hizo con el mismo `sigma_fuerza`; si no, None (el simulador no se declara validado)."""
    try:
        datos = json.loads(RUTA_BACKTEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not datos.get("validado") or abs(float(datos.get("sigma_fuerza", -1)) - sigma) > 1e-9:
        return None
    return {k: datos[k] for k in ("n_temporadas", "cobertura_p05_p95", "mae_puntos_modelo", "mae_puntos_extrapolacion", "fraccion", "generado") if k in datos}


def _armar_salida(entrada_hash_base: dict, filas: list[dict], conteo: list[list[int]], puntos: list[list[int]],
                  utiles: int, n_sim: int, semilla: int, cupos: list[dict], extra_supuestos: list[str]) -> dict:
    resultado, error = _resumir(filas, conteo, puntos, utiles, cupos)
    backtest = _backtest_vigente(float(entrada_hash_base.get("sigma_fuerza", 0.0)))
    limitaciones = [LIMITACIONES[0]] + ([f"backtest en {backtest['n_temporadas']} temporadas de ligas europeas ({backtest['generado']}): cobertura del intervalo p05–p95 = {backtest['cobertura_p05_p95']}"] if backtest else [LIMITACIONES[1]])
    salida = {
        "ok": True, "version_api": VERSION_API, "semilla": semilla,
        "huella_entrada": _huella(entrada_hash_base), "motor": entrada_hash_base.get("motor", "python"), "validado": backtest is not None,
        "resultado": resultado,
        "error_montecarlo": {"max_evento": error, "n": utiles, "n_solicitado": n_sim},
        "supuestos": [*SUPUESTOS, *extra_supuestos, f"incertidumbre de la fuerza de cada equipo: desvío log {entrada_hash_base.get('sigma_fuerza', 0.0)}"], "limitaciones": limitaciones, "backtest": backtest,
    }
    salida["huella_salida"] = _huella({k: v for k, v in salida.items() if k != "huella_salida"})
    return salida


def _preparar(tabla, pendientes, lambdas, n_sim, semilla, desempates, cupos):
    _validar_parametros(n_sim, semilla)
    filas = _validar_tabla(tabla)
    pares = _validar_pendientes(pendientes, {f["equipo"] for f in filas})
    des = _validar_desempates(desempates)
    cups = _validar_cupos(cupos, len(filas))
    lams = _resolver_lambdas(lambdas, pares)
    entrada = {"tabla": filas, "pendientes": [[a, b, lh, la] for (a, b), (lh, la) in zip(pares, lams, strict=True)],
               "n_sim": n_sim, "semilla": semilla, "desempates": list(des), "cupos": cups}
    return filas, pares, lams, des, cups, entrada


# ───────────────────────────── MM-22: temporada ─────────────────────────────

def simular_temporada(tabla: list[dict], pendientes: list[dict], lambdas: Lambdas, n_sim: int = 10_000,
                      semilla: int = 12345, desempates: tuple[str, ...] = DESEMPATES_POR_DEFECTO,
                      cupos: list[dict] | None = None, rho: float = -0.10, sigma_fuerza: float | None = None, motor: str | None = None) -> dict:
    """Monte Carlo del resto de la temporada. `rho` se acepta por compatibilidad: v1 muestrea Poisson independiente. `sigma_fuerza` (en log, def. `SIGMA_FUERZA_DEFECTO`) añade la incertidumbre de la fuerza de cada equipo."""
    filas, pares, lams, des, cups, entrada = _preparar(tabla, pendientes, lambdas, n_sim, semilla, desempates, cupos)
    sigma = SIGMA_FUERZA_DEFECTO if sigma_fuerza is None else max(0.0, min(float(sigma_fuerza), 0.5))
    entrada["sigma_fuerza"] = sigma
    motor = motor_para({}) if motor is None else motor
    entrada["motor"] = motor
    usado: dict = {}
    conteo, puntos, utiles = _nucleo(filas, pares, lams, n_sim, semilla, des, {}, {}, sigma, motor, usado)
    entrada["motor"] = usado.get("motor", motor)
    entrada["capacidad"] = "simular_temporada"
    return _armar_salida(entrada, filas, conteo, puntos, utiles, n_sim, semilla, cups, [])


# ───────────────────────────── MM-23: escenarios ─────────────────────────────

def _validar_fijos(resultados_fijos: Any, pares: list[tuple[str, str]], modo: str):
    if not isinstance(resultados_fijos, (list, tuple)) or not resultados_fijos:
        raise _invalida("resultados_fijos", "debe ser una lista no vacía")
    if len(resultados_fijos) > MAX_FIJOS:
        raise _excedido("resultados_fijos", f"más de {MAX_FIJOS} resultados fijos", MAX_FIJOS)
    fijos: dict[int, tuple[int, int]] = {}
    filtros: dict[int, Callable[[int, int], bool]] = {}
    for i, r in enumerate(resultados_fijos):
        if not isinstance(r, dict) or (r.get("local"), r.get("visitante")) not in pares:
            raise _invalida(f"resultados_fijos[{i}]", "el partido no está entre los pendientes")
        k = pares.index((r["local"], r["visitante"]))
        if k in fijos or k in filtros:
            raise _invalida(f"resultados_fijos[{i}]", "partido repetido")
        res = r.get("resultado")
        if res is not None:
            if res not in ("1", "X", "2"):
                raise _invalida(f"resultados_fijos[{i}].resultado", "debe ser '1', 'X' o '2'")
            if modo == "forzar":
                raise _invalida(f"resultados_fijos[{i}].resultado", "en modo 'forzar' se exige marcador gl/gv")
            filtros[k] = (lambda a, b, res=res: ("1" if a > b else "2" if a < b else "X") == res)
            continue
        gl, gv = r.get("gl"), r.get("gv")
        if not (_es_entero(gl) and _es_entero(gv) and 0 <= gl <= 30 and 0 <= gv <= 30):
            raise _invalida(f"resultados_fijos[{i}]", "se requiere gl y gv enteros en 0..30 (o 'resultado')")
        if modo == "forzar":
            fijos[k] = (gl, gv)
        else:
            filtros[k] = (lambda a, b, gl=gl, gv=gv: a == gl and b == gv)
    return fijos, filtros


def _aplicar_ajustes(lams, pares, ajustes, equipos: set[str]):
    if ajustes is None:
        return lams
    if not isinstance(ajustes, dict):
        raise _invalida("ajustes", "ajustes debe ser {equipo: factor}")
    for e, f in ajustes.items():
        if e not in equipos or isinstance(f, bool) or not isinstance(f, (int, float)) or not 0.1 <= f <= 3:
            raise _invalida(f"ajustes[{e}]", "equipo desconocido o factor fuera de 0,1..3")
    salida = []
    for (loc, vis), (lh, la) in zip(pares, lams, strict=True):
        nuevo = (lh * ajustes.get(loc, 1.0), la * ajustes.get(vis, 1.0))
        for x in nuevo:
            if not 0 < x < LAMBDA_MAX:
                raise _invalida("ajustes", f"el ajuste lleva una lambda fuera de (0, {LAMBDA_MAX:g})")
        salida.append(nuevo)
    return salida


def _diferencia(base: dict, esc: dict) -> dict:
    dif: dict[str, dict] = {"posiciones": {}, "eventos": {}}
    for e, probs in esc["posiciones"].items():
        dif["posiciones"][e] = [a - b for a, b in zip(probs, base["posiciones"][e], strict=True)]
        dif["eventos"][e] = {k: v - base["eventos"][e][k] for k, v in esc["eventos"][e].items()}
    return dif


def simular_escenario(base: dict, resultados_fijos: list[dict], ajustes: dict | None = None, modo: str = "forzar") -> dict:
    """Escenario «¿y si…?» contra la base, con la MISMA semilla (aleatorios comunes).

    `base`: {tabla, pendientes, lambdas, n_sim, semilla, desempates?, cupos?}.
    `resultados_fijos`: [{local, visitante, gl, gv}] (modo "forzar": el partido se juega con ese marcador) o
    [{local, visitante, resultado:"1"|"X"|"2"} | {.., gl, gv}] (modo "filtrar": se descartan las simulaciones que no lo
    cumplen; `aprovechamiento` < 5 % => error `datos_insuficientes`).
    `ajustes`: {equipo: factor} multiplica las lambdas de los goles que marca ese equipo (0,1..3).
    """
    if modo not in ("forzar", "filtrar"):
        raise _invalida("modo", "modo debe ser 'forzar' o 'filtrar'")
    if not isinstance(base, dict):
        raise _invalida("base", "base debe ser un objeto")
    n_sim, semilla = base.get("n_sim", 10_000), base.get("semilla", 12345)
    filas, pares, lams, des, cups, entrada = _preparar(
        base.get("tabla"), base.get("pendientes"), base.get("lambdas"), n_sim, semilla,
        base.get("desempates", DESEMPATES_POR_DEFECTO), base.get("cupos"))
    fijos, filtros = _validar_fijos(resultados_fijos, pares, modo)
    lams_esc = _aplicar_ajustes(lams, pares, ajustes, {f["equipo"] for f in filas})

    sigma = SIGMA_FUERZA_DEFECTO if base.get("sigma_fuerza") is None else max(0.0, min(float(base["sigma_fuerza"]), 0.5))
    entrada["sigma_fuerza"] = sigma
    motor = base.get("motor") or motor_para(filtros)  # base y escenario con el MISMO motor: si hay filtros, los dos en Python
    if filtros:
        motor = "python"
    entrada["motor"] = motor
    u_base: dict = {}
    u_esc: dict = {}
    c0, p0, u0 = _nucleo(filas, pares, lams, n_sim, semilla, des, {}, {}, sigma, motor, u_base)
    c1, p1, u1 = _nucleo(filas, pares, lams_esc, n_sim, semilla, des, fijos, filtros, sigma, motor, u_esc)
    entrada["motor"] = u_esc["motor"] if u_esc.get("motor") == u_base.get("motor") else "mixto"  # base y escenario deberían coincidir; si no, se dice
    aprovechamiento = u1 / n_sim
    if modo == "filtrar" and aprovechamiento < APROVECHAMIENTO_MINIMO:
        raise ErrorEntrada("datos_insuficientes", "resultados_fijos",
                           f"solo {aprovechamiento:.1%} de las simulaciones cumple el escenario (mínimo 5 %)",
                           maximo=APROVECHAMIENTO_MINIMO, corregible=True)
    entrada.update({"capacidad": "simular_escenario", "modo": modo, "ajustes": ajustes,
                    "resultados_fijos": resultados_fijos})
    extra = [f"escenario en modo '{modo}' con aleatorios comunes respecto de la base (misma semilla)"]
    salida = _armar_salida(entrada, filas, c1, p1, u1, n_sim, semilla, cups, extra)
    base_res, _ = _resumir(filas, c0, p0, u0, cups)
    salida["aprovechamiento"] = aprovechamiento
    salida["modo"] = modo
    salida["base"] = base_res
    salida["diferencia"] = _diferencia(base_res, salida["resultado"])
    salida["huella_salida"] = _huella({k: v for k, v in salida.items() if k != "huella_salida"})
    return salida


# ───────────────────────────── MM-23: caminos exactos ─────────────────────────────

_MARCADORES = {"1": (1, 0), "X": (1, 1), "2": (0, 1)}


def enumerar_caminos(tabla: list[dict], pendientes: list[dict], lambdas: Lambdas, objetivo: dict,
                     rho: float = -0.10, desempates: tuple[str, ...] = DESEMPATES_POR_DEFECTO) -> dict:
    """Enumera exactamente los 3^k resultados 1X2 de k <= 8 partidos y marca cuáles cumplen el `objetivo`.

    `objetivo`: {equipo, evento: "titulo"|"cupo", posiciones: [desde, hasta]} (titulo = posición 1).
    APROXIMACIÓN: el 1X2 no fija la diferencia de goles, así que cada resultado se materializa con un marcador
    representativo (1-0, 1-1, 0-1) y los desempates por diferencia o goles a favor son indicativos. Empates totales
    se resuelven por nombre (determinista). Las probabilidades 1X2 sí son exactas (matriz de goles con rho).
    """
    filas = _validar_tabla(tabla)
    equipos = {f["equipo"] for f in filas}
    pares = _validar_pendientes(pendientes, equipos)
    if len(pares) > MAX_CAMINOS_PARTIDOS:
        raise _excedido("pendientes", f"enumerar_caminos admite como máximo {MAX_CAMINOS_PARTIDOS} partidos",
                        MAX_CAMINOS_PARTIDOS)
    des = _validar_desempates(desempates)
    lams = _resolver_lambdas(lambdas, pares)
    if not isinstance(objetivo, dict) or objetivo.get("equipo") not in equipos:
        raise _invalida("objetivo.equipo", "equipo desconocido")
    evento = objetivo.get("evento")
    if evento == "titulo":
        desde, hasta = 1, 1
    elif evento == "cupo":
        pos = objetivo.get("posiciones")
        if (not isinstance(pos, (list, tuple)) or len(pos) != 2 or not all(_es_entero(x) for x in pos)
                or not 1 <= pos[0] <= pos[1] <= len(filas)):
            raise _invalida("objetivo.posiciones", f"debe ser [desde, hasta] dentro de 1..{len(filas)}")
        desde, hasta = pos
    else:
        raise _invalida("objetivo.evento", "evento debe ser 'titulo' o 'cupo'")

    p1x2 = []
    for lh, la in lams:
        r = resumen_matriz(matriz_goles(lh, la, rho))["p1x2"]
        p1x2.append({"1": r["local"], "X": r["empate"], "2": r["visitante"]})

    indice = {f["equipo"]: i for i, f in enumerate(filas)}
    rango = {e: r for r, e in enumerate(sorted(equipos))}
    orden_nombre = [float(rango[f["equipo"]]) for f in filas]
    caminos, suma, objetivo_p = [], 0.0, 0.0
    for combo in itertools.product("1X2", repeat=len(pares)):
        prob = math.prod(p1x2[k][c] for k, c in enumerate(combo))
        pts = [f["pts"] for f in filas]
        gf = [f["gf"] for f in filas]
        gc = [f["gc"] for f in filas]
        for (loc, vis), c in zip(pares, combo, strict=True):
            a, b = _MARCADORES[c]
            ih, ia = indice[loc], indice[vis]
            gf[ih] += a
            gc[ih] += b
            gf[ia] += b
            gc[ia] += a
            pts[ih] += 3 if c == "1" else 1 if c == "X" else 0
            pts[ia] += 3 if c == "2" else 1 if c == "X" else 0
        orden = _ranking(len(filas), pts, gf, gc, des, orden_nombre)  # empate total: por nombre (determinista)
        posicion = orden.index(indice[objetivo["equipo"]]) + 1
        cumple = desde <= posicion <= hasta
        suma += prob
        if cumple:
            objetivo_p += prob
        caminos.append({"resultados": [{"local": loc, "visitante": vis, "resultado": c,
                                        "marcador": "{}-{}".format(*_MARCADORES[c])}
                                       for (loc, vis), c in zip(pares, combo, strict=True)],
                        "probabilidad": prob, "cumple": cumple, "posicion_final": posicion})
    caminos.sort(key=lambda x: (-x["probabilidad"], [r["resultado"] for r in x["resultados"]]))
    devueltos = caminos[:MAX_CAMINOS_DEVUELTOS]
    return {
        "ok": True, "version_api": VERSION_API, "validado": False,
        "huella_entrada": _huella({"tabla": filas, "pendientes": [[a, b, lh, la] for (a, b), (lh, la) in
                                                                  zip(pares, lams, strict=True)],
                                   "objetivo": objetivo, "rho": rho, "desempates": list(des)}),
        "n_caminos_total": len(caminos), "suma_probabilidades": suma,
        "probabilidad_objetivo": objetivo_p,
        "cobertura_de_caminos": sum(c["probabilidad"] for c in devueltos),
        "caminos": devueltos,
        "supuestos": ["probabilidad 1X2 exacta por partido (matriz de goles con corrección Dixon-Coles)",
                      "partidos independientes", "sin lesiones ni sanciones"],
        "limitaciones": ["aproximación: el 1X2 no fija diferencias de gol; marcadores representativos 1-0, 1-1, 0-1",
                         "no validado con backtest"],
    }
