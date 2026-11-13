"""ml/laplace/lote.py — el modelo como sistema que se ejecuta sin Telegram ni servidor: partidos de entrada (CSV o JSON) → pronósticos de salida (CSV o JSON).

Es la misma función que sirve `/api/v1/ml/predict` (`servicio.pronosticar_partido`), así que da las mismas probabilidades por cualquier vía: HTTP, línea de comandos (`modelo_laplace.py predecir`), el bot, la web o una IA.
No escribe nada en la base: es un cálculo de solo lectura sobre el modelo vigente (por el puntero en disco).

ENTRADA (una fila por partido). Obligatorias: `local`, `visitante`. Opcionales: `liga` (nombre), `pais` (desambigua ligas homónimas: «Serie B» de Brasil o de Italia), `liga_id` (id de API-Football) y
`cuota_local`, `cuota_empate`, `cuota_visitante` (decimales previas al partido; activan `p_*_con_mercado`).
SALIDA (una fila por partido, mismo orden): `ok`, `fuente` (`modelo_laplace`, `dixon_coles_historico` o `referencia_de_liga`), `degradado`, `p_local`, `p_empate`, `p_visitante` (suman 1),
`p_*_con_mercado` si hubo cuotas, `goles_local` y `goles_visitante` solo si el mercado de goles superó a la tasa base fuera de muestra, y `motivo` si no hay pronóstico. Una fila mala no detiene el lote.
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable

from backend.api.ml.laplace import servicio

MAX_FILAS = 5000
COLUMNAS_ENTRADA = ("local", "visitante", "liga", "pais", "liga_id", "cuota_local", "cuota_empate", "cuota_visitante")
COLUMNAS_SALIDA = ("local", "visitante", "liga", "pais", "ok", "fuente", "degradado", "p_local", "p_empate", "p_visitante",
                   "p_local_con_mercado", "p_empate_con_mercado", "p_visitante_con_mercado", "goles_local", "goles_visitante", "motivo")


def entradas_de_texto(texto: str, formato: str) -> list[dict]:
    """Filas de entrada desde CSV (con cabecera) o JSON (una lista de objetos). Lanza ValueError con un mensaje claro si el formato no sirve."""
    if formato == "json":
        datos = json.loads(texto)
        if not isinstance(datos, list) or not all(isinstance(f, dict) for f in datos):
            raise ValueError("el JSON debe ser una lista de objetos, uno por partido")
        return datos
    if formato == "csv":
        lector = csv.DictReader(io.StringIO(texto.lstrip("﻿")))
        if not lector.fieldnames or "local" not in lector.fieldnames or "visitante" not in lector.fieldnames:
            raise ValueError("el CSV necesita una cabecera con al menos las columnas local y visitante")
        return list(lector)
    raise ValueError(f"formato desconocido: {formato}")


def _numero(valor: object) -> float | None:
    try:
        return float(str(valor).strip().replace(",", ".")) if str(valor).strip() else None
    except ValueError:
        return None


def normalizar(fila: dict) -> dict:
    """Entrada limpia para el servicio, o `{"_error": motivo}` si la fila no sirve."""
    local, visitante = str(fila.get("local") or "").strip(), str(fila.get("visitante") or "").strip()
    if not local or not visitante:
        return {"_error": "faltan local o visitante", "local": local, "visitante": visitante}
    if local == visitante:
        return {"_error": "local y visitante son el mismo equipo", "local": local, "visitante": visitante}
    entrada: dict = {"local": local[:120], "visitante": visitante[:120], "liga": str(fila.get("liga") or "").strip()[:120]}
    pais = str(fila.get("pais") or "").strip()
    if pais:
        entrada["pais"] = pais[:60]
    liga_id = _numero(fila.get("liga_id"))
    if liga_id is not None and liga_id >= 1:
        entrada["liga_id"] = int(liga_id)
    cuotas = [_numero(fila.get(c)) for c in ("cuota_local", "cuota_empate", "cuota_visitante")]
    if all(c is not None for c in cuotas):
        entrada["cuotas"] = cuotas
    return entrada


def aplanar(entrada: dict, salida: dict) -> dict:
    """Una fila de salida a partir de lo que devuelve el servicio (ya filtrado por `servicio.publico`)."""
    fila = dict.fromkeys(COLUMNAS_SALIDA, "")
    fila.update(local=entrada["local"], visitante=entrada["visitante"], liga=entrada.get("liga", ""), pais=entrada.get("pais", ""), ok=bool(salida.get("ok")))
    if not salida.get("ok"):
        fila["motivo"] = str(salida.get("motivo") or "sin pronóstico")
        return fila
    p = salida["p1x2"]
    fila.update(fuente=salida.get("fuente", ""), degradado=bool(salida.get("degradado")), p_local=round(p["local"], 4), p_empate=round(p["empate"], 4), p_visitante=round(p["visitante"], 4))
    mercado = salida.get("p1x2_con_mercado")
    if mercado:
        fila.update(p_local_con_mercado=round(mercado["local"], 4), p_empate_con_mercado=round(mercado["empate"], 4), p_visitante_con_mercado=round(mercado["visitante"], 4))
    goles = salida.get("goles_esperados")
    if goles:
        fila.update(goles_local=round(goles["local"], 2), goles_visitante=round(goles["visitante"], 2))
    return fila


def pronosticar_lote(filas: list[dict], pronosticar: Callable[..., dict] | None = None) -> list[dict]:
    """Un pronóstico por fila, en el mismo orden. `pronosticar` se puede sustituir en pruebas; por defecto es el del servicio, sin base (no registra nada)."""
    if len(filas) > MAX_FILAS:
        raise ValueError(f"demasiadas filas ({len(filas)} > {MAX_FILAS}): divide el archivo")
    pronosticar = pronosticar or servicio.pronosticar_partido
    salida = []
    for fila in filas:
        entrada = normalizar(fila)
        if "_error" in entrada:
            salida.append(aplanar({"local": entrada["local"], "visitante": entrada["visitante"]}, {"ok": False, "motivo": entrada["_error"]}))
            continue
        try:
            bruto = pronosticar(None, entrada, "http")
            resultado = servicio.publico(bruto) if bruto.get("ok") else bruto  # `publico` quita los mercados de goles que no superaron a la tasa base
        except Exception as exc:  # noqa: BLE001 — una fila mala no detiene el lote
            resultado = {"ok": False, "motivo": f"falló el cálculo: {type(exc).__name__}"}
        salida.append(aplanar(entrada, resultado))
    return salida


def a_csv(filas: list[dict]) -> str:
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=COLUMNAS_SALIDA, lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return buffer.getvalue()


def a_json(filas: list[dict]) -> str:
    return json.dumps(filas, ensure_ascii=False, indent=1)
