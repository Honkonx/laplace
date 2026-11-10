"""services/_matematica.py — Helpers matemáticos compartidos del motor estadístico.

Extraído 2026-09-09 de la duplicación real encontrada en pronostico.py, consenso.py, h2h.py,
form_recent.py, tabla_pos.py y odds.py (auditoría de esta sesión): `_safe_float`/`_safe_int`/
`_safe_bool`/`_clamp` estaban reimplementadas casi idénticas en los 6 archivos, y el patrón de
renormalización de probabilidades 1X2 (dividir por un total → redondear a 4 decimales → corregir
el remanente de redondeo sumándolo a la componente local) se repetía en h2h.py, tabla_pos.py,
odds.py y consenso.py — con un clamp mínimo 0.05 previo compartido entre h2h.py y tabla_pos.py.

Refactor puro — comportamiento numérico idéntico al original en cada call site, verificado
comparando outputs reales antes/después con casos de borde (h2h_total=0, min_prob clamp,
posiciones extremas, odds muy dispares) — no solo "los tests siguen pasando".

Nota real: `odds._safe_float` tenía una variante propia con guarda extra de NaN/Inf (las cuotas
de mercado pueden llegar corruptas de una fuente externa) — se preserva vía el parámetro
`finito=True`, no se generaliza al resto de los call sites porque ninguno la necesitaba.

Nota real 2: `form_recent.py` tiene su PROPIO clamp mínimo con redistribución de déficit (si una
probabilidad queda bajo 0.05, le resta el déficit a la mayor de las otras dos en vez de un simple
`max()`) — es un algoritmo genuinamente distinto al de h2h.py/tabla_pos.py, no una duplicación
más del mismo patrón. No se unifica acá para no alterar su resultado numérico real; form_recent.py
sigue calculando ese clamp localmente y solo reutiliza `corregir_redondeo` para el cierre final
(redondeo a 4 decimales + corrección de remanente), que sí es idéntico en los 5 archivos.
"""
from __future__ import annotations

import math


def safe_float(val, default: float = 0.0, *, finito: bool = False) -> float:
    """Convierte `val` a float con fallback a `default` si no es convertible.
    `finito=True` además descarta NaN/Inf (comportamiento propio que tenía odds.py)."""
    try:
        v = float(val) if val is not None else default
    except (TypeError, ValueError):
        return default
    if finito and (math.isnan(v) or math.isinf(v)):
        return default
    return v


def safe_int(val, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def safe_bool(val, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    if isinstance(val, int):
        return val != 0
    return default


def clamp(val, mn, mx):
    return max(mn, min(mx, val))


def clamp_prob_minima(prob_local, prob_empate, prob_visit, min_prob: float = 0.05):
    """Clamp mínimo simple (sin redistribuir déficit) sobre las 3 probabilidades 1X2 antes de
    renormalizar — patrón compartido por h2h.py y tabla_pos.py."""
    return max(min_prob, prob_local), max(min_prob, prob_empate), max(min_prob, prob_visit)


def corregir_redondeo(prob_local, prob_empate, prob_visit):
    """Redondea las 3 probabilidades 1X2 a 4 decimales y corrige el remanente de redondeo
    sumándolo a la componente local — último paso común a toda renormalización de probabilidades
    1X2 del proyecto (h2h.py, tabla_pos.py, odds.py, consenso.py, form_recent.py)."""
    prob_local = round(prob_local, 4)
    prob_empate = round(prob_empate, 4)
    prob_visit = round(prob_visit, 4)
    diff = round(1.0 - prob_local - prob_empate - prob_visit, 4)
    prob_local = round(prob_local + diff, 4)
    return prob_local, prob_empate, prob_visit


def normalizar_probabilidades(prob_local, prob_empate, prob_visit, total):
    """Divide las 3 probabilidades 1X2 por `total` y aplica `corregir_redondeo` — patrón
    compartido por h2h.py, tabla_pos.py y odds.py (que normalizan contra la suma de las 3) y
    consenso.py (que normaliza contra un acumulador de peso distinto — por eso `total` es un
    parámetro explícito en vez de recalcularse como prob_local+prob_empate+prob_visit)."""
    return corregir_redondeo(prob_local / total, prob_empate / total, prob_visit / total)
