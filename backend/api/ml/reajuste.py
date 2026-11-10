"""ml/reajuste.py — reajuste rápido de los Dixon-Coles con la capa en vivo, con validación.

Reentrena SOLO las ligas que recibieron partidos en vivo nuevos (o todas con `todas=True`), con los
hiperparámetros ya elegidos en el artefacto vigente (xi, ridge, rho): sin tuning ni evaluación
completa, unos segundos por liga. El artefacto nuevo no reemplaza al anterior sin pasar la
validación (`validar`): misma o mayor cobertura, ningún equipo desaparece, parámetros finitos y en
rango, y una comparación walk-forward corta sobre los partidos en vivo en la que el modelo con la
capa en vivo no puede ser peor (log-loss) que el entrenado solo con el maestro.

El ajuste (numpy/scipy) entra inyectado como `ajustador` (por defecto `dixon_coles.ajustar`): así la
lógica de validación se prueba sin numpy y el job del servidor la corre en un subproceso con el Python
que sí lo tiene. El runtime de producción solo lee el JSON resultante (`services/modelo_historico`).
"""
from __future__ import annotations

import copy
import json
import math
import os
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from backend.api.ml import dixon_coles, metricas

ESTRUCTURA_FIT = Callable[..., "dixon_coles.ModeloLiga | None"]

SEMANAS_EVALUACION = 8
BLOQUE_DIAS = 14
MIN_EVALUADOS = 100       # partidos en vivo cuya predicción difiere entre ambos modelos
TOLERANCIA_LOG_LOSS = 0.002  # ruido admitido: con n pequeño la diferencia ya es ruido de muestreo
MIN_VIVOS_PARA_AVANZAR_CORTE = 30
RANGO_PARAMETRO = 3.0     # |ataque|, |defensa|
RANGO_MU = (-2.5, 2.5)
RANGO_GAMMA = (-0.6, 1.6)


def _tuplas(partidos: list[dict]) -> list[tuple[int, str, str, int, int]]:
    return [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in partidos]


def reajustar_ligas(
    artefacto: dict,
    por_liga: dict[str, list[dict]],
    fecha_ref: int,
    ligas: list[str],
    ajustador: ESTRUCTURA_FIT = dixon_coles.ajustar,
    min_vivos_corte: int = MIN_VIVOS_PARA_AVANZAR_CORTE,
) -> dict:
    """Copia del artefacto con las `ligas` reajustadas. El resto queda byte a byte igual.

    `fecha_corte` solo avanza más allá del último partido del maestro si la liga tiene al menos
    `min_vivos_corte` partidos en vivo: con tres partidos sueltos de 2026 un modelo con ratings de 2024
    no está "al día", y `modelo_historico` usa `fecha_corte` para penalizar la confianza por antigüedad."""
    hp = artefacto["hiperparametros"]
    nuevo = copy.deepcopy(artefacto)
    for codigo in ligas:
        partidos = por_liga.get(codigo, [])
        modelo = ajustador(_tuplas(partidos), fecha_ref, xi=hp["xi"], ridge=hp["ridge"], rho=hp["rho"])
        if modelo is None:
            continue
        vivos = sum(1 for p in partidos if p.get("vivo"))
        dia_maestro = max((p["dia"] for p in partidos if not p.get("vivo")), default=modelo.fecha_corte)
        entrada = {"nombre": artefacto["ligas"][codigo].get("nombre", ""), **modelo.a_dict()}
        if vivos < min_vivos_corte:
            entrada["fecha_corte"] = min(dia_maestro, modelo.fecha_corte)
        entrada["n_partidos_vivos"] = vivos
        nuevo["ligas"][codigo] = entrada
    return nuevo


def comparar_parametros(viejo: dict, nuevo: dict, ligas: list[str]) -> dict[str, dict]:
    """Cuánto cambian los ratings de cada liga reajustada (mu, gamma, ataque, defensa)."""
    salida = {}
    for c in ligas:
        a, b = viejo["ligas"].get(c), nuevo["ligas"].get(c)
        if not a or not b:
            continue
        d_att = [abs(b["ataque"][e] - a["ataque"][e]) for e in a["ataque"] if e in b["ataque"]]
        d_def = [abs(b["defensa"][e] - a["defensa"][e]) for e in a["defensa"] if e in b["defensa"]]
        salida[c] = {
            "n_antes": a["n_partidos"], "n_despues": b["n_partidos"], "vivos": b.get("n_partidos_vivos", 0),
            "d_mu": round(b["mu"] - a["mu"], 5), "d_gamma": round(b["gamma"] - a["gamma"], 5),
            "d_ataque_medio": round(sum(d_att) / len(d_att), 5) if d_att else 0.0,
            "d_ataque_max": round(max(d_att), 5) if d_att else 0.0,
            "d_defensa_medio": round(sum(d_def) / len(d_def), 5) if d_def else 0.0,
            "d_defensa_max": round(max(d_def), 5) if d_def else 0.0,
            "fecha_corte_antes": a.get("fecha_corte"), "fecha_corte_despues": b.get("fecha_corte"),
        }
    return salida


def validar_estructura(viejo: dict, nuevo: dict) -> list[str]:
    """Problemas que impiden reemplazar el artefacto (lista vacía = estructura sana)."""
    problemas: list[str] = []
    if len(nuevo["ligas"]) < len(viejo["ligas"]):
        problemas.append(f"menos ligas: {len(viejo['ligas'])} -> {len(nuevo['ligas'])}")
    for codigo, a in viejo["ligas"].items():
        b = nuevo["ligas"].get(codigo)
        if b is None:
            problemas.append(f"{codigo}: la liga desaparece")
            continue
        perdidos = set(a["ataque"]) - set(b["ataque"])
        if perdidos:
            problemas.append(f"{codigo}: desaparecen {len(perdidos)} equipos ({', '.join(sorted(perdidos)[:3])}...)")
    for codigo, b in nuevo["ligas"].items():
        valores = [b["mu"], b["gamma"], b["rho"], *b["ataque"].values(), *b["defensa"].values()]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in valores):
            problemas.append(f"{codigo}: parametros no finitos")
            continue
        if not (RANGO_MU[0] <= b["mu"] <= RANGO_MU[1] and RANGO_GAMMA[0] <= b["gamma"] <= RANGO_GAMMA[1]):
            problemas.append(f"{codigo}: mu/gamma fuera de rango ({b['mu']}, {b['gamma']})")
        if any(abs(v) > RANGO_PARAMETRO for v in [*b["ataque"].values(), *b["defensa"].values()]):
            problemas.append(f"{codigo}: ataque/defensa fuera de +-{RANGO_PARAMETRO}")
    return problemas


def walk_forward_vivo(
    por_liga_maestro: dict[str, list[dict]],
    por_liga_con_vivo: dict[str, list[dict]],
    vivos_eval: list[dict],
    hp: dict,
    semanas: int = SEMANAS_EVALUACION,
    bloque_dias: int = BLOQUE_DIAS,
    ajustador: ESTRUCTURA_FIT = dixon_coles.ajustar,
) -> dict:
    """Compara, SIN fuga del futuro, el modelo entrenado solo con el maestro (A) contra el entrenado con
    maestro + capa en vivo (B), sobre los partidos en vivo de las últimas `semanas`.

    Cada partido se predice con modelos ajustados únicamente con partidos de días anteriores al inicio
    de su bloque (`bloque_dias`). Solo cuentan los partidos cuya liga ya tenía algún partido en vivo
    NUEVO (no presente en el maestro) antes del bloque: en los demás A y B son idénticos y no informan."""
    if not vivos_eval:
        return {"n": 0, "log_loss_maestro": None, "log_loss_con_vivo": None, "rps_maestro": None, "rps_con_vivo": None, "por_liga": {}}
    fin = max(p["dia"] for p in vivos_eval)
    desde = fin - 7 * semanas
    inicio = min(p["dia"] for p in vivos_eval if p["dia"] >= desde)
    pares_a: list = []
    pares_b: list = []
    por_liga: dict[str, dict] = defaultdict(lambda: {"n": 0, "ll_a": 0.0, "ll_b": 0.0})
    bloques: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for p in vivos_eval:
        if p["dia"] >= desde:
            bloques[(p["liga"], (p["dia"] - inicio) // bloque_dias)].append(p)
    for (liga, nro), partidos in sorted(bloques.items()):
        t = inicio + nro * bloque_dias
        con_vivo = [x for x in por_liga_con_vivo.get(liga, []) if x["dia"] < t]
        if not any(x.get("vivo") for x in con_vivo):
            continue
        a = ajustador(_tuplas([x for x in por_liga_maestro.get(liga, []) if x["dia"] < t]), t, xi=hp["xi"], ridge=hp["ridge"], rho=hp["rho"])
        b = ajustador(_tuplas(con_vivo), t, xi=hp["xi"], ridge=hp["ridge"], rho=hp["rho"])
        if a is None or b is None:
            continue
        for p in partidos:
            pa = dixon_coles.probabilidades(a, p["local"], p["visitante"])
            pb = dixon_coles.probabilidades(b, p["local"], p["visitante"])
            pares_a.append((pa, p["resultado"]))
            pares_b.append((pb, p["resultado"]))
            acum = por_liga[liga]
            acum["n"] += 1
            acum["ll_a"] += metricas.log_loss(pa, p["resultado"])
            acum["ll_b"] += metricas.log_loss(pb, p["resultado"])
    n = len(pares_a)
    ra, rb = metricas.resumen(pares_a), metricas.resumen(pares_b)
    return {
        "n": n, "log_loss_maestro": ra["log_loss"], "log_loss_con_vivo": rb["log_loss"],
        "rps_maestro": ra["rps"], "rps_con_vivo": rb["rps"],
        "por_liga": {c: {"n": v["n"], "log_loss_maestro": round(v["ll_a"] / v["n"], 5), "log_loss_con_vivo": round(v["ll_b"] / v["n"], 5)}
                     for c, v in sorted(por_liga.items()) if v["n"]},
    }


def decidir(problemas: list[str], wf: dict, min_evaluados: int = MIN_EVALUADOS, tolerancia: float = TOLERANCIA_LOG_LOSS) -> tuple[bool, str]:
    """(reemplazar?, motivo). Sin datos suficientes o con un log-loss peor, NO reemplaza."""
    if problemas:
        return False, "validacion estructural fallida: " + "; ".join(problemas[:5])
    if wf["n"] < min_evaluados:
        return False, (f"datos en vivo insuficientes para validar: {wf['n']} partidos evaluables (< {min_evaluados}); "
                       "se conserva el artefacto vigente")
    if wf["log_loss_con_vivo"] > wf["log_loss_maestro"] + tolerancia:
        return False, (f"el modelo con capa en vivo es peor: log-loss {wf['log_loss_con_vivo']} vs "
                       f"{wf['log_loss_maestro']} (tolerancia {tolerancia}); se conserva el artefacto vigente")
    return True, (f"validado: log-loss {wf['log_loss_con_vivo']} vs {wf['log_loss_maestro']} "
                  f"sobre {wf['n']} partidos en vivo")


def reemplazar_atomico(nuevo: dict, destino: Path, respaldo_dir: Path) -> Path:
    """Guarda copia del vigente en `respaldo_dir` y reemplaza `destino` de forma atómica (`os.replace`
    sobre un temporal vecino). El backend en ejecución recoge el cambio sin reiniciar: la firma de
    `services/modelo_historico._firma_archivos_modelo` incluye mtime y tamaño de este archivo, y su
    caché (`_artefactos`) se reconstruye en la siguiente consulta que vea una firma distinta."""
    respaldo_dir.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    copia = respaldo_dir / f"{destino.stem}.{sello}{destino.suffix}"
    copia.write_bytes(destino.read_bytes())
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(json.dumps(nuevo, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, destino)
    return copia
