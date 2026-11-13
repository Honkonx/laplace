"""services/agent_marcador.py — rendimiento de las piezas (modelo y bot) por liga y pesos auditables (MA-20 … MA-24).

La previa sale del histórico (`backend/scripts/previa_piezas_por_liga.py`: log loss walk-forward de cada pieza por liga sobre los mismos partidos) y se actualiza con lo que mide el laboratorio EN VIVO
con una contracción `λ = n/(n+k)` hacia la previa: con pocos partidos en vivo manda el histórico; con muchos, lo vivo. Solo se nombra un «líder» si la diferencia es de al menos 0,002 de log loss.
Medido en la máquina de desarrollo: con un desvío pareado de 0,05–0,10 por partido, distinguir 0,005 exige 400–1.600 partidos POR LIGA; por eso la previa histórica es obligatoria y lo vivo solo ajusta.
Los pesos son una **recomendación de presentación** (qué pieza va primero y cómo se comunica): el agente NO cambia las cifras del bot ni del modelo.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

RAIZ = Path(__file__).resolve().parents[3]
RUTA_PREVIA = RAIZ / "backend" / "data" / "datos" / "resultados" / "previa_piezas_por_liga.json"
PIEZAS = ("modelo", "bot")
K_CONTRACCION = 150
MIN_VIVO = 30
ETA = 50.0
PESO_MIN, PESO_MAX = 0.2, 0.8
DIFERENCIA_MINIMA = 0.002
VARIANTE_A_PIEZA = {"laplace_modelo": "modelo", "dc_mas_mercado_historico": "bot"}


@lru_cache(maxsize=4)
def _leer(ruta: str, mtime_ns: int, tamano: int) -> dict:
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8")).get("ligas", {})
    except (OSError, ValueError):
        return {}


def cargar_previa(ruta: Path | None = None) -> dict:
    """{liga: {pieza: {n, log_loss, rps}}} del último cálculo histórico; vacío si no existe (el agente sigue sin pesos)."""
    r = Path(ruta or RUTA_PREVIA)
    try:
        estado = r.stat()
        return _leer(str(r), estado.st_mtime_ns, estado.st_size)
    except OSError:
        return {}


def vivo_desde_laboratorio(db: Session, liga: str) -> dict:
    """{pieza: {n, log_loss}} medido en vivo en el laboratorio para esa liga (nombre tal como lo guarda el laboratorio)."""
    from sqlalchemy import func

    from backend.api.models.predicciones import PronosticoExperimental as Obs

    salida: dict[str, dict] = {}
    for variante, pieza in VARIANTE_A_PIEZA.items():
        n, media = db.query(func.count(Obs.id), func.avg(Obs.log_loss)).filter(Obs.variante == variante, Obs.liga == liga, Obs.log_loss.is_not(None)).one()
        if n:
            salida[pieza] = {"n": int(n), "log_loss": float(media)}
    return salida


def ponderar(previa_liga: dict, vivo: dict | None = None) -> dict:
    """Pesos de presentación entre `modelo` y `bot` para una liga: previa histórica contraída con lo vivo, acotados a [0,2; 0,8]; líder solo con diferencia ≥ 0,002."""
    vivo = vivo or {}
    if not all(p in previa_liga for p in PIEZAS):
        return {"pesos": {}, "lider": None, "motivo": "sin previa histórica para esta liga", "n_vivo": 0}
    n_vivo = min(vivo.get(p, {}).get("n", 0) for p in PIEZAS)
    lam = n_vivo / (n_vivo + K_CONTRACCION) if n_vivo >= MIN_VIVO else 0.0
    perdida = {p: lam * vivo[p]["log_loss"] + (1 - lam) * previa_liga[p]["log_loss"] if lam else previa_liga[p]["log_loss"] for p in PIEZAS}
    crudo = {p: math.exp(-ETA * perdida[p]) for p in PIEZAS}
    total = sum(crudo.values())
    w_modelo = min(PESO_MAX, max(PESO_MIN, crudo["modelo"] / total))
    pesos = {"modelo": round(w_modelo, 4), "bot": round(1 - w_modelo, 4)}
    mejor = min(PIEZAS, key=lambda p: perdida[p])
    dif = abs(perdida["modelo"] - perdida["bot"])
    return {"pesos": pesos, "lider": mejor if dif >= DIFERENCIA_MINIMA else None, "diferencia": round(dif, 5), "perdida": {p: round(v, 5) for p, v in perdida.items()},
            "n_previa": min(previa_liga[p]["n"] for p in PIEZAS), "n_vivo": n_vivo, "lambda": round(lam, 3), "fuente": "previa histórica + vivo" if lam else "previa histórica"}


def resumen_liga(codigo: str, db: Session | None = None, nombre_liga: str | None = None, previa: dict | None = None) -> dict:
    previa = cargar_previa() if previa is None else previa
    vivo = vivo_desde_laboratorio(db, nombre_liga) if db is not None and nombre_liga else {}
    return {"liga": codigo, **ponderar(previa.get(codigo, {}), vivo)}


def linea_para_usuario(resumen: dict) -> str | None:
    """Una frase corta y con base («hoy confío más en X porque…») o la honesta «sin evidencia suficiente»; None si no hay previa."""
    if not resumen.get("pesos"):
        return None
    if resumen["lider"] is None:
        return f"En {resumen['liga']} el modelo y el bot rinden parecido en el histórico (diferencia {resumen['diferencia']:.4f} de log loss): no hay evidencia para preferir uno."
    nombre = "el modelo Laplace" if resumen["lider"] == "modelo" else "el bot"
    return (f"En {resumen['liga']} {nombre} rinde mejor en el histórico (log loss {resumen['perdida'][resumen['lider']]:.4f} frente a "
            f"{resumen['perdida']['bot' if resumen['lider'] == 'modelo' else 'modelo']:.4f}, {resumen['n_previa']} partidos): diferencia pequeña, no una garantía.")


def linea_de_partido(db: Session | None, liga: str, local: str, visitante: str) -> str | None:
    """Frase del marcador para el partido consultado (resuelve la liga con los alias del histórico); None si no hay previa o no se puede resolver."""
    try:
        from backend.api.ml.laplace import servicio

        r = servicio._resolver_real({"liga": liga, "local": local, "visitante": visitante})  # noqa: SLF001
        return linea_para_usuario(resumen_liga(r[0], db, liga)) if r else None
    except Exception:  # noqa: BLE001 — una frase accesoria nunca rompe una respuesta
        return None


def tabla_admin(previa: dict | None = None, limite: int = 12) -> list[dict]:
    """Las ligas con más partidos y su líder, para `/marcador`."""
    previa = cargar_previa() if previa is None else previa
    filas = [{"liga": c, **ponderar(p)} for c, p in previa.items() if all(x in p for x in PIEZAS)]
    return sorted(filas, key=lambda f: -f.get("n_previa", 0))[:limite]
