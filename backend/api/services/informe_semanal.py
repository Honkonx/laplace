"""informe_semanal.py — qué tanto acertó el sistema en los últimos días, calculado solo con lo que se verificó solo (AU-6 y GO-3).

Mide sobre `pronosticos_experimentales` (cada fila trae las probabilidades, los goles esperados y, ya cerrado el partido, el resultado y los goles reales de cada equipo):
- embudo de verificación (la cola `verificaciones`): cuántos pronósticos hay, cuántos cerraron, cuántos esperan y cuántos llevan atraso;
- 1X2 por variante: aciertos, log loss, RPS y Brier, comparados con la tasa base de `resultados_partidos` (misma cantidad de partidos), con IC95 de la diferencia;
- goles de cada equipo: error absoluto y log-verosimilitud de Poisson frente a la media de goles de la propia ventana (referencia sin información);
- por liga (variante `laplace_modelo`).
Una semana (~cientos de partidos) confirma que el circuito funciona; NO alcanza para decidir si se le gana al mercado: el informe lo dice con el n y el intervalo, no con adjetivos.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.api.core.horario import a_texto_utc
from backend.api.core.tiempo import utc_ahora
from backend.api.models.partidos import ResultadoPartido
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.services import verificacion

TASA_BASE_SIN_DATOS = (0.45, 0.27, 0.28)
MIN_PARTIDOS_LIGA = 5
VARIANTE_PRINCIPAL = "laplace_modelo"


def _tasa_base(db: Session) -> tuple[float, float, float]:
    filas = db.query(ResultadoPartido.ganador).filter(ResultadoPartido.ganador.isnot(None)).limit(50000).all()
    if len(filas) < 200:
        return TASA_BASE_SIN_DATOS
    n = len(filas)
    return tuple(sum(1 for (g,) in filas if g == k) / n for k in ("local", "empate", "visitante"))  # type: ignore[return-value]


def _indice(f: PronosticoExperimental) -> int:
    return 0 if f.goles_local_real > f.goles_visitante_real else 2 if f.goles_visitante_real > f.goles_local_real else 1


def _perdidas(probs: tuple[float, float, float], k: int) -> tuple[float, float, float]:
    """(log loss, RPS, Brier) de un pronóstico 1X2 y el resultado `k` (0 local, 1 empate, 2 visitante)."""
    uno = [1.0 if i == k else 0.0 for i in range(3)]
    ll = -math.log(max(probs[k], 1e-12))
    rps = 0.5 * ((probs[0] - uno[0]) ** 2 + ((probs[0] + probs[1]) - (uno[0] + uno[1])) ** 2)
    return ll, rps, sum((p - o) ** 2 for p, o in zip(probs, uno))


def _ic95(diferencias: list[float]) -> list[float] | None:
    if len(diferencias) < 5:
        return None
    media, error = statistics.fmean(diferencias), statistics.stdev(diferencias) / math.sqrt(len(diferencias))
    return [round(media - 1.96 * error, 5), round(media + 1.96 * error, 5)]


def _resumen_1x2(filas: list[PronosticoExperimental], base: tuple[float, float, float]) -> dict:
    ll, rps, br, ll_base, aciertos = [], [], [], [], 0
    for f in filas:
        probs = (f.prob_local, f.prob_empate, f.prob_visitante)
        k = _indice(f)
        a, b, c = _perdidas(probs, k)
        ll.append(a), rps.append(b), br.append(c)
        ll_base.append(_perdidas(base, k)[0])
        aciertos += f.pick_correcto == 1
    n = len(filas)
    dif = [x - y for x, y in zip(ll_base, ll)]   # positivo = el pronóstico mejora a la tasa base
    return {"n": n, "acierto": round(aciertos / n, 4), "log_loss": round(statistics.fmean(ll), 5), "rps": round(statistics.fmean(rps), 5), "brier": round(statistics.fmean(br), 5),
            "log_loss_tasa_base": round(statistics.fmean(ll_base), 5), "mejora_vs_tasa_base": round(statistics.fmean(dif), 5), "ic95_mejora": _ic95(dif)}


def _ll_poisson(lam: float, k: int) -> float:
    lam = max(lam, 1e-6)
    return -(k * math.log(lam) - lam - math.lgamma(k + 1))


def _resumen_goles(filas: list[PronosticoExperimental]) -> dict | None:
    con = [f for f in filas if f.goles_local_esperados is not None and f.goles_visitante_esperados is not None]
    if len(con) < 5:
        return None
    media_l, media_v = statistics.fmean(f.goles_local_real for f in con), statistics.fmean(f.goles_visitante_real for f in con)
    res = {"n": len(con)}
    for lado, esp, real, media in (("local", "goles_local_esperados", "goles_local_real", media_l), ("visitante", "goles_visitante_esperados", "goles_visitante_real", media_v)):
        mae = statistics.fmean(abs(getattr(f, esp) - getattr(f, real)) for f in con)
        mae_ref = statistics.fmean(abs(media - getattr(f, real)) for f in con)
        dif = [_ll_poisson(media, getattr(f, real)) - _ll_poisson(getattr(f, esp), getattr(f, real)) for f in con]
        res[lado] = {"error_abs": round(mae, 4), "error_abs_media_de_la_ventana": round(mae_ref, 4), "poisson_mejora_por_partido": round(statistics.fmean(dif), 5), "ic95": _ic95(dif)}
    res["marcador_probable_acertado"] = round(sum(1 for f in con if f.marcador_probable == f"{f.goles_local_real}-{f.goles_visitante_real}") / len(con), 4)
    return res


def _por_liga(filas: list[PronosticoExperimental], base: tuple[float, float, float]) -> list[dict]:
    grupos: dict[str, list[PronosticoExperimental]] = {}
    for f in filas:
        grupos.setdefault(f.liga or "?", []).append(f)
    salida = [{"liga": liga, **_resumen_1x2(g, base)} for liga, g in grupos.items() if len(g) >= MIN_PARTIDOS_LIGA]
    return sorted(salida, key=lambda x: -x["n"])[:15]


def generar(db: Session, dias: int = 7, ahora: datetime | None = None) -> dict:
    """Informe de la ventana `[ahora − dias, ahora]` sobre lo pronosticado dentro de ella y ya verificado."""
    ahora = ahora or utc_ahora().replace(tzinfo=None)
    desde = a_texto_utc(ahora - timedelta(days=dias))
    base = _tasa_base(db)
    todas = db.query(PronosticoExperimental).filter(PronosticoExperimental.creado_en >= desde.replace("T", " ")[:19]).all() or \
        db.query(PronosticoExperimental).filter(PronosticoExperimental.creado_en >= desde).all()
    cerradas = [f for f in todas if f.goles_local_real is not None and f.goles_visitante_real is not None and None not in (f.prob_local, f.prob_empate, f.prob_visitante)]
    por_variante: dict[str, list[PronosticoExperimental]] = {}
    for f in cerradas:
        por_variante.setdefault(f.variante, []).append(f)
    principal = por_variante.get(VARIANTE_PRINCIPAL, [])
    return {
        "ventana": {"desde": desde, "hasta": a_texto_utc(ahora), "dias": dias},
        "embudo": {"pronosticos_en_la_ventana": len(todas), "cerrados": len(cerradas), "sin_resultado_aun": len(todas) - len(cerradas), **verificacion.estado_cola(db, ahora)},
        "tasa_base": {"local": round(base[0], 4), "empate": round(base[1], 4), "visitante": round(base[2], 4)},
        "por_variante": {v: _resumen_1x2(fs, base) for v, fs in sorted(por_variante.items()) if len(fs) >= 5},
        "goles": _resumen_goles(principal),
        "por_liga": _por_liga(principal, base) if principal else [],
        "lectura": _lectura(principal, base),
    }


def _lectura(principal: list[PronosticoExperimental], base: tuple[float, float, float]) -> str:
    if len(principal) < 30:
        return f"Solo {len(principal)} partidos del modelo cerrados: es pronto para sacar conclusiones; sirve para comprobar que el circuito funciona."
    r = _resumen_1x2(principal, base)
    ic = r["ic95_mejora"]
    if ic and ic[0] > 0:
        return f"Con {r['n']} partidos el modelo mejora a la tasa base ({r['mejora_vs_tasa_base']:+.4f} de log loss, IC95 sin cero). Contra el mercado esta muestra no alcanza para decidir."
    return f"Con {r['n']} partidos todavía no se distingue del azar de la tasa base (IC95 incluye cero). Hace falta más muestra."


def texto(informe: dict) -> str:
    """Resumen corto para el administrador (máx. 10 líneas)."""
    e, p = informe["embudo"], informe["por_variante"].get(VARIANTE_PRINCIPAL)
    lineas = [f"📊 Informe de {informe['ventana']['dias']} días", f"Pronósticos: {e['pronosticos_en_la_ventana']} · cerrados {e['cerrados']} · esperando {e['sin_resultado_aun']} · atrasados {e['atrasadas']}"]
    if p:
        lineas.append(f"Modelo: acierto {p['acierto']:.1%} · log loss {p['log_loss']:.4f} (tasa base {p['log_loss_tasa_base']:.4f}) · n {p['n']}")
    g = informe.get("goles")
    if g:
        lineas.append(f"Goles: error local {g['local']['error_abs']:.2f} (ref. {g['local']['error_abs_media_de_la_ventana']:.2f}) · visitante {g['visitante']['error_abs']:.2f} (ref. {g['visitante']['error_abs_media_de_la_ventana']:.2f})")
    lineas.append(informe["lectura"])
    return "\n".join(lineas)
