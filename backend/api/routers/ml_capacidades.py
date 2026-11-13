"""routers/ml_capacidades.py — capacidades del modelo Laplace para IAs y servicios internos, contrato `ml-2` (MM-20, MM-21, MM-22, MM-23).

El modelo CALCULA; la IA (o el servicio) pregunta, pasa datos y critica. Reglas de seguridad del contrato (diseño en el plan de mejoras, repo de trabajo):
- solo lectura y sin estado (nada se escribe en la base), todas con la clave interna `x-laplace-ml-key` (sin `ML_API_KEY` configurada los endpoints no existen: 404);
- entrada con esquema cerrado y límites; un error es siempre `{"ok": false, "error": <código>, "campo", "maximo", "corregible"}` (422), nunca un resultado parcial;
- toda salida lleva versión del contrato y del modelo, semilla y huellas SHA-256 de entrada y salida; lo no validado se declara (`validado: false`);
- los textos que devuelve el modelo son identificadores o enumeraciones, nunca texto libre del usuario.
Endpoints: `GET /capacidades`, `GET /tools`, `POST /sim/temporada`, `POST /sim/escenario`, `POST /sim/caminos`, `POST /eval/comparar`, `POST /verificar`.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.api.core.config import settings
from backend.api.core.rate_limit import limitar
from backend.api.ml import comparacion
from backend.api.ml.laplace import liga, servicio
from backend.api.routers.ml_modelo import DEFINICION_HERRAMIENTA

router = APIRouter(prefix="/api/v2/ml", tags=["modelo-laplace-v2"])
VERSION_CONTRATO = "ml-2"
TAMANO_MAXIMO_BYTES = 1_000_000
MAX_PARES_EVAL = 20_000
PRESUPUESTO_SORTEOS_GO = 40_000_000  # con el núcleo en Go (≈ 20 veces más rápido)
PRESUPUESTO_SORTEOS = 2_000_000  # partidos simulados por llamada (n_sim × pendientes; ×2 en escenarios): ≈ 2 s en Python puro
PLAZO_SEGUNDOS = 20.0
CAMPOS_VERIFICABLES = {
    "p1x2.local": ("p1x2", "local"), "p1x2.empate": ("p1x2", "empate"), "p1x2.visitante": ("p1x2", "visitante"),
    "btts.si": ("btts", "si"), "btts.no": ("btts", "no"),
    "mas_1_5": ("over_under", "1.5", "mas"), "mas_2_5": ("over_under", "2.5", "mas"), "mas_3_5": ("over_under", "3.5", "mas"),
    "goles_esperados.total": ("goles_esperados", "total"),
}


def _huella(obj) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=list).encode()).hexdigest()


def _error(codigo: str, campo: str, mensaje: str, maximo=None, corregible: bool = True) -> JSONResponse:
    return JSONResponse(status_code=422, content={"ok": False, "contrato": VERSION_CONTRATO, "error": codigo, "campo": campo, "maximo": maximo, "corregible": corregible, "mensaje": mensaje})


def _exigir_clave(clave: str) -> None:
    esperada = settings.ML_API_KEY
    if not esperada:
        raise HTTPException(status_code=404, detail="Capacidades del modelo deshabilitadas")
    if not hmac.compare_digest(clave.encode(), esperada.encode()):
        raise HTTPException(status_code=401, detail="Clave inválida")


async def _cuerpo(request: Request) -> dict:
    """Cuerpo JSON con tope de tamaño: se mira `Content-Length` ANTES de leer y se corta la lectura en cuanto se pasa del tope (no se acumula un cuerpo enorme en memoria)."""
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > TAMANO_MAXIMO_BYTES:
        raise liga.ErrorEntrada("limite_excedido", "cuerpo", "el cuerpo supera el tamaño máximo", maximo=TAMANO_MAXIMO_BYTES)
    partes, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > TAMANO_MAXIMO_BYTES:
            raise liga.ErrorEntrada("limite_excedido", "cuerpo", "el cuerpo supera el tamaño máximo", maximo=TAMANO_MAXIMO_BYTES)
        partes.append(trozo)
    try:
        datos = json.loads(b"".join(partes) or b"{}")
    except ValueError as exc:
        raise liga.ErrorEntrada("entrada_invalida", "cuerpo", "el cuerpo no es JSON válido") from exc
    if not isinstance(datos, dict):
        raise liga.ErrorEntrada("entrada_invalida", "cuerpo", "el cuerpo debe ser un objeto JSON")
    return datos


def _version_modelo() -> str | None:
    info, _art, _ = servicio._modelo_vigente(None)  # noqa: SLF001
    return (info or {}).get("version")


def _envoltorio(capacidad: str, resultado: dict) -> dict:
    return {"contrato": VERSION_CONTRATO, "capacidad": capacidad, "version_modelo": _version_modelo(), **resultado}


def _lambdas(datos: dict, pendientes: list) -> dict:
    """`lambdas` explícitas ([{local, visitante, lam_local, lam_visitante}]) o, con `lambdas_de_modelo`, las del modelo Laplace para cada partido pendiente."""
    if datos.get("lambdas_de_modelo"):
        nombre_liga = str(datos.get("liga", ""))[:120]
        salida = {}
        for p in pendientes[:liga.MAX_PENDIENTES]:
            if not isinstance(p, dict) or not p.get("local") or not p.get("visitante"):
                raise liga.ErrorEntrada("entrada_invalida", "pendientes", "cada partido pendiente necesita local y visitante")
            r = servicio.pronostico_propio({"local": str(p["local"]), "visitante": str(p["visitante"]), "liga": nombre_liga})
            g = (r or {}).get("goles_esperados")
            if not g:
                raise liga.ErrorEntrada("datos_insuficientes", "lambdas_de_modelo", f"el modelo no cubre {str(p['local'])[:60]} vs {str(p['visitante'])[:60]}", corregible=False)
            salida[(p["local"], p["visitante"])] = (g["local"], g["visitante"])
        return salida
    lista = datos.get("lambdas")
    if not isinstance(lista, list):
        raise liga.ErrorEntrada("entrada_invalida", "lambdas", "faltan las lambdas (lista) o `lambdas_de_modelo: true`")
    try:
        return {(x["local"], x["visitante"]): (float(x["lam_local"]), float(x["lam_visitante"])) for x in lista}
    except (KeyError, TypeError, ValueError) as exc:
        raise liga.ErrorEntrada("entrada_invalida", "lambdas", "cada lambda necesita local, visitante, lam_local y lam_visitante numéricos") from exc


def _simulacion(datos: dict) -> dict:
    return {"tabla": datos.get("tabla"), "pendientes": datos.get("pendientes") or [], "lambdas": _lambdas(datos, datos.get("pendientes") or []), "n_sim": datos.get("n_sim", 10_000),
            "semilla": datos.get("semilla", 12345), "desempates": tuple(datos.get("desempates") or liga.DESEMPATES_POR_DEFECTO), "cupos": datos.get("cupos")}


def _presupuesto(n_sim, pendientes, factor: int = 1, motor_python: bool = False) -> None:
    """Tope de TRABAJO total (n_sim × partidos pendientes × factor), no solo de cada factor por separado: 20.000 × 500 cumpliría cada límite y serían 10 millones de sorteos."""
    try:
        trabajo = int(n_sim) * max(1, len(pendientes)) * factor
    except (TypeError, ValueError):
        return  # el validador de `liga` rechaza el tipo con su error cerrado
    tope = PRESUPUESTO_SORTEOS_GO if liga.motor_nativo_disponible() and not motor_python else PRESUPUESTO_SORTEOS  # el tope grande vale solo si el cálculo irá en Go
    if trabajo > tope:
        raise liga.ErrorEntrada("limite_excedido", "n_sim", f"n_sim × partidos pendientes supera el presupuesto de {tope} sorteos por llamada", maximo=tope // max(1, len(pendientes)) // factor)


async def _ejecutar(capacidad: str, llamada) -> JSONResponse | dict:
    """Corre el cálculo en un hilo (no bloquea el servidor) con plazo; el error de entrada se devuelve como error cerrado."""
    try:
        resultado = await asyncio.wait_for(asyncio.to_thread(llamada), timeout=PLAZO_SEGUNDOS)
        return _envoltorio(capacidad, resultado)
    except liga.ErrorEntrada as exc:
        return JSONResponse(status_code=422, content={**exc.como_dict(), "contrato": VERSION_CONTRATO})
    except TimeoutError:
        return JSONResponse(status_code=504, content={"ok": False, "contrato": VERSION_CONTRATO, "error": "limite_excedido", "campo": "plazo", "maximo": PLAZO_SEGUNDOS, "corregible": True,
                                                      "mensaje": "el cálculo superó el plazo; baja n_sim o el número de partidos pendientes"})


@router.get("/capacidades")
def capacidades(x_laplace_ml_key: str = Header(default="")) -> dict:
    _exigir_clave(x_laplace_ml_key)
    return {"contrato": VERSION_CONTRATO, "version_modelo": _version_modelo(), "capacidades": [
        {"nombre": "pronosticar_partido", "ruta": "POST /api/v1/ml/predict", "validado": True, "limites": "120/min por IP"},
        {"nombre": "simular_temporada", "ruta": "POST /api/v2/ml/sim/temporada", "validado": False, "limites": "n_sim ≤ 20.000; ≤ 24 equipos; ≤ 500 pendientes"},
        {"nombre": "simular_escenario", "ruta": "POST /api/v2/ml/sim/escenario", "validado": False, "limites": "≤ 20 resultados fijos"},
        {"nombre": "enumerar_caminos", "ruta": "POST /api/v2/ml/sim/caminos", "validado": False, "limites": "≤ 8 partidos pendientes"},
        {"nombre": "comparar_pronosticos", "ruta": "POST /api/v2/ml/eval/comparar", "validado": True, "limites": f"≤ {MAX_PARES_EVAL} partidos"},
        {"nombre": "verificar_afirmacion", "ruta": "POST /api/v2/ml/verificar", "validado": True, "campos": sorted(CAMPOS_VERIFICABLES)}]}


def _herramientas() -> list[dict]:
    esquema_sim = {"type": "object", "properties": {"tabla": {"type": "array", "items": {"type": "object"}}, "pendientes": {"type": "array", "items": {"type": "object"}},
                                                    "liga": {"type": "string", "maxLength": 120}, "n_sim": {"type": "integer", "maximum": 20000}, "semilla": {"type": "integer"}}, "required": ["tabla", "pendientes"]}
    return [DEFINICION_HERRAMIENTA,
            {"name": "laplace_simular_temporada", "description": "Simula el resto de una temporada con el modelo Laplace (Monte Carlo reproducible con semilla): probabilidad de cada posición, título y descenso. "
             "Es una estimación sin validar; no recomienda apostar.", "input_schema": esquema_sim},
            {"name": "laplace_verificar_afirmacion", "description": "Compara una cifra que dio una IA con la que calcula el modelo y responde coincide/difiere con la diferencia; no corrige la cifra.",
             "input_schema": {"type": "object", "properties": {"entrada": {"type": "object", "properties": {"local": {"type": "string"}, "visitante": {"type": "string"}, "liga": {"type": "string"}}, "required": ["local", "visitante"]},
                                                                "afirmacion": {"type": "object", "properties": {"campo": {"type": "string", "enum": sorted(CAMPOS_VERIFICABLES)}, "valor": {"type": "number"}}, "required": ["campo", "valor"]},
                                                                "tolerancia": {"type": "number", "minimum": 0.001, "maximum": 0.2}}, "required": ["entrada", "afirmacion"]}}]


@router.get("/tools")
def herramientas(x_laplace_ml_key: str = Header(default="")) -> dict:
    """Herramientas del modelo en formato Anthropic (`input_schema`) y OpenAI (`function`)."""
    _exigir_clave(x_laplace_ml_key)
    d = _herramientas()
    return {"contrato": VERSION_CONTRATO, "anthropic": d, "openai": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in d]}


@router.post("/sim/temporada")
@limitar("30/minute")
async def sim_temporada(request: Request, x_laplace_ml_key: str = Header(default="")):
    _exigir_clave(x_laplace_ml_key)
    try:
        datos = await _cuerpo(request)
        entrada = _simulacion(datos)
        _presupuesto(entrada["n_sim"], entrada["pendientes"])
    except liga.ErrorEntrada as exc:
        return JSONResponse(status_code=422, content={**exc.como_dict(), "contrato": VERSION_CONTRATO})
    return await _ejecutar("simular_temporada", lambda: liga.simular_temporada(entrada["tabla"], entrada["pendientes"], entrada["lambdas"], entrada["n_sim"], entrada["semilla"], entrada["desempates"], entrada["cupos"]))


@router.post("/sim/escenario")
@limitar("30/minute")
async def sim_escenario(request: Request, x_laplace_ml_key: str = Header(default="")):
    _exigir_clave(x_laplace_ml_key)
    try:
        datos = await _cuerpo(request)
        base = datos.get("base")
        if not isinstance(base, dict):
            raise liga.ErrorEntrada("entrada_invalida", "base", "falta `base` con tabla, pendientes y lambdas")
        entrada = _simulacion(base)
        _presupuesto(entrada["n_sim"], entrada["pendientes"], factor=2, motor_python=str(datos.get("modo", "forzar")) == "filtrar")  # la base y el escenario; «filtrar» siempre va en Python
    except liga.ErrorEntrada as exc:
        return JSONResponse(status_code=422, content={**exc.como_dict(), "contrato": VERSION_CONTRATO})
    return await _ejecutar("simular_escenario", lambda: liga.simular_escenario(entrada, datos.get("resultados_fijos") or [], datos.get("ajustes"), str(datos.get("modo", "forzar"))))


@router.post("/sim/caminos")
@limitar("30/minute")
async def sim_caminos(request: Request, x_laplace_ml_key: str = Header(default="")):
    _exigir_clave(x_laplace_ml_key)
    try:
        datos = await _cuerpo(request)
        entrada = _simulacion(datos)
    except liga.ErrorEntrada as exc:
        return JSONResponse(status_code=422, content={**exc.como_dict(), "contrato": VERSION_CONTRATO})
    return await _ejecutar("enumerar_caminos", lambda: liga.enumerar_caminos(entrada["tabla"], entrada["pendientes"], entrada["lambdas"], datos.get("objetivo") or {}, desempates=entrada["desempates"]))


@router.post("/eval/comparar")
@limitar("30/minute")
async def eval_comparar(request: Request, x_laplace_ml_key: str = Header(default="")):
    """Compara dos listas de pronósticos 1X2 sobre los MISMOS partidos: diferencia media de log loss, z, Diebold-Mariano-HLN e IC95 por bootstrap (positiva = `b` mejor)."""
    _exigir_clave(x_laplace_ml_key)
    try:
        datos = await _cuerpo(request)
        a, b, res = datos.get("a"), datos.get("b"), datos.get("resultados")
        if not (isinstance(a, list) and isinstance(b, list) and isinstance(res, list) and len(a) == len(b) == len(res)):
            raise liga.ErrorEntrada("entrada_invalida", "a/b/resultados", "a, b y resultados deben ser listas del mismo largo")
        if not 3 <= len(a) <= MAX_PARES_EVAL:
            raise liga.ErrorEntrada("limite_excedido", "a", f"se aceptan entre 3 y {MAX_PARES_EVAL} partidos", maximo=MAX_PARES_EVAL)
        n_boot, semilla = int(datos.get("n_boot", 300)), int(datos.get("semilla", 7))
        if not 10 <= n_boot <= 2000:
            raise liga.ErrorEntrada("limite_excedido", "n_boot", "n_boot debe estar entre 10 y 2000", maximo=2000)

        def probs(fila, campo):
            if not (isinstance(fila, list) and len(fila) == 3 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in fila) and abs(sum(fila) - 1) < 1e-3):
                raise liga.ErrorEntrada("entrada_invalida", campo, "cada pronóstico son tres probabilidades entre 0 y 1 que suman 1")
            return tuple(float(x) for x in fila)

        if any(r not in ("H", "D", "A") for r in res):
            raise liga.ErrorEntrada("entrada_invalida", "resultados", "los resultados son «H», «D» o «A»")
        pa, pb = [(probs(x, "a"), r) for x, r in zip(a, res)], [(probs(x, "b"), r) for x, r in zip(b, res)]
        bloques = [i // 25 for i in range(len(pa))]  # bloques de 25 partidos consecutivos (el orden de entrada se respeta)
        r = comparacion.comparar_predicciones(pa, pb, bloques=bloques, n_boot=n_boot, semilla=semilla)
    except liga.ErrorEntrada as exc:
        return JSONResponse(status_code=422, content={**exc.como_dict(), "contrato": VERSION_CONTRATO})
    salida = {"ok": True, "semilla": semilla, "n": r["n"], "diferencia_media": r["diferencia_media"], "error_estandar": r["error_estandar"], "z": r["z"], "dm_hln": r["dm_hln"], "p_dm_hln": r["p_dm_hln"],
              "ic95": list(r["ic95"]), "perdida_a": r["perdida_a"], "perdida_b": r["perdida_b"], "cumple_puerta": r["acepta"], "supuestos": ["bloques de 25 partidos consecutivos", "log loss"],
              "huella_entrada": _huella({"a": a, "b": b, "resultados": res, "n_boot": n_boot, "semilla": semilla}), "validado": True}
    salida["huella_salida"] = _huella(salida)
    return _envoltorio("comparar_pronosticos", salida)


@router.post("/verificar")
@limitar("60/minute")
async def verificar(request: Request, x_laplace_ml_key: str = Header(default="")):
    """«La IA propone, el modelo calcula, la IA critica»: recalcula la cifra que afirmó una IA y dice si coincide. NO la corrige. Solo campos validados (los que el modelo muestra)."""
    _exigir_clave(x_laplace_ml_key)
    try:
        datos = await _cuerpo(request)
        entrada, afirmacion = datos.get("entrada"), datos.get("afirmacion")
        if not isinstance(entrada, dict) or not isinstance(afirmacion, dict):
            raise liga.ErrorEntrada("entrada_invalida", "entrada/afirmacion", "faltan `entrada` y `afirmacion`")
        campo, valor = afirmacion.get("campo"), afirmacion.get("valor")
        if campo not in CAMPOS_VERIFICABLES:
            raise liga.ErrorEntrada("entrada_invalida", "afirmacion.campo", f"campos permitidos: {', '.join(sorted(CAMPOS_VERIFICABLES))}")
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise liga.ErrorEntrada("entrada_invalida", "afirmacion.valor", "el valor debe ser un número")
        tolerancia = datos.get("tolerancia", 0.02)
        if isinstance(tolerancia, bool) or not isinstance(tolerancia, (int, float)) or not 0.001 <= tolerancia <= 0.2:
            raise liga.ErrorEntrada("limite_excedido", "tolerancia", "la tolerancia debe estar entre 0,001 y 0,2", maximo=0.2)
    except liga.ErrorEntrada as exc:
        return JSONResponse(status_code=422, content={**exc.como_dict(), "contrato": VERSION_CONTRATO})
    modelo = servicio.publico(servicio.pronosticar_partido(None, {"local": entrada.get("local"), "visitante": entrada.get("visitante"), "liga": entrada.get("liga") or ""}, canal="http"))
    if not modelo.get("ok"):
        return _error("modelo_no_disponible", "entrada", str(modelo.get("motivo", "el modelo no cubre el partido")), corregible=False)
    actual = modelo
    for clave in CAMPOS_VERIFICABLES[campo]:
        actual = actual.get(clave) if isinstance(actual, dict) else None
    if actual is None:
        return _error("no_validado", "afirmacion.campo", f"el modelo no tiene {campo} validado para este partido: no se puede verificar", corregible=False)
    diferencia = float(valor) - float(actual)
    salida = {"ok": True, "coincide": abs(diferencia) <= float(tolerancia), "valor_modelo": round(float(actual), 6), "valor_afirmado": float(valor), "diferencia": round(diferencia, 6), "tolerancia": float(tolerancia),
              "fuente": modelo.get("fuente"), "degradado": bool(modelo.get("degradado")), "supuestos": ["se compara con el pronóstico actual del modelo para ese partido"],
              "huella_entrada": _huella({"entrada": entrada, "afirmacion": afirmacion, "tolerancia": tolerancia}), "validado": True}
    salida["huella_salida"] = _huella(salida)
    return _envoltorio("verificar_afirmacion", salida)
