"""services/ai_metrics.py — instrumentación real de costo/latencia por proveedor de IA.

Mide la latencia de CADA intento (éxito o fallo) a un proveedor de la cascada de
`ai_client.py` (Gemini, Groq, OpenRouter, Ollama cloud/local y Claude, según el rol) y lo deja disponible de tres formas:

  1. Log estructurado (logger `laplace.ai_metrics`, con `extra={...}` por intento) —
     analizable con grep/jq sin dependencias nuevas.
  2. Un acumulador in-memory por proveedor (contador de intentos/éxitos/fallos + latencia
     promedio), reseteable, vive solo mientras el proceso esté arriba — útil para "¿cómo viene
     cada proveedor en esta corrida?" sin tocar la BD.
  3. Persistencia real en `metricas_ia_proveedor` (tabla creada por la migración
     `e0b8b0bd13dd`, aplicada y verificada contra la BD real 2026-09-10 — ver
     `.claude/rules/database-safety.md`). Sesión propia y corta vía `SessionLocal` (mismo
     patrón que usa `bot/laplace_bot.py` para operaciones sueltas que no reciben una sesión de
     request) — así no hace falta threadear `db: Session` a través de las 4 funciones de
     proveedor + `generar_texto_ia` + todos sus callers (bot, `analisis_completo.py`, etc.),
     que sería un refactor mucho más grande que lo que esta pieza necesita.

El INSERT nunca bloquea ni tumba la cascada real de IA: va en el mismo `try/except` amplio que
ya protegía el log/acumulador — si escribir la fila falla (BD lockeada, lo que sea), se loguea
la advertencia y se sigue, igual que antes.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from backend.api.core.tiempo import utc_ahora
from backend.api.db.session import SessionLocal
from backend.api.models.metricas import MetricaIaProveedor

log = logging.getLogger("laplace.ai_metrics")


def _now_str() -> str:
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class _AcumuladorProveedor:
    intentos: int = 0
    exitosos: int = 0
    fallidos: int = 0
    latencia_total_ms: float = 0.0

    @property
    def latencia_promedio_ms(self) -> float | None:
        return round(self.latencia_total_ms / self.intentos, 1) if self.intentos else None


_acumuladores: dict[str, _AcumuladorProveedor] = {}


def sanitizar_error(error: str | None) -> str | None:
    """Elimina secretos de URLs y headers antes de persistir o registrar un fallo HTTP."""
    if not error:
        return error
    limpio = re.sub(r"([?&](?:key|api[_-]?key|token|authorization)=)[^&\s]+", r"\1[REDACTED]", error, flags=re.I)
    return re.sub(r"(Bearer\s+)[^\s]+", r"\1[REDACTED]", limpio, flags=re.I)


def ms_desde(inicio_perf_counter: float) -> float:
    """`time.perf_counter()` tomado antes del intento -> milisegundos transcurridos reales.
    Helper compartido para no repetir `(time.perf_counter() - inicio) * 1000` en cada uno de
    los proveedores de `ai_client.py`."""
    return (time.perf_counter() - inicio_perf_counter) * 1000


def registrar_intento(
    proveedor: str, *, exitoso: bool, latencia_ms: float, modelo: str | None = None, error: str | None = None
) -> None:
    """Registra un intento (éxito o fallo) a `proveedor` — log estructurado + acumulador
    in-memory. Nunca lanza: la instrumentación no debe poder tumbar la cascada real de IA que
    está midiendo (si esto fallara y propagara, un usuario real se quedaría sin predicción por
    un bug de métricas, inaceptable)."""
    error_seguro = sanitizar_error(error)
    try:
        acumulador = _acumuladores.setdefault(proveedor, _AcumuladorProveedor())
        acumulador.intentos += 1
        if exitoso:
            acumulador.exitosos += 1
        else:
            acumulador.fallidos += 1
        acumulador.latencia_total_ms += latencia_ms

        log.info(
            "metrica_ia_proveedor proveedor=%s exitoso=%s latencia_ms=%.1f modelo=%s",
            proveedor, exitoso, latencia_ms, modelo,
            extra={
                "proveedor": proveedor,
                "modelo": modelo,
                "exitoso": exitoso,
                "latencia_ms": round(latencia_ms, 1),
                "error": error_seguro[:200] if error_seguro else None,
            },
        )

        db = SessionLocal()
        try:
            db.add(MetricaIaProveedor(
                proveedor=proveedor, modelo=modelo, exitoso=1 if exitoso else 0,
                latencia_ms=latencia_ms, error=(error_seguro[:500] if error_seguro else None),
                creado_en=_now_str(),
            ))
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — instrumentación nunca debe romper la cascada real de IA
        log.warning("ai_metrics.registrar_intento falló al registrar (no bloqueante): %s", type(exc).__name__)


def resumen_metricas() -> dict[str, dict]:
    """Snapshot in-memory de intentos/éxitos/fallos/latencia promedio por proveedor, acumulado
    desde que arrancó el proceso (se resetea en cada restart — no persiste, ver docstring del
    módulo sobre por qué no hay tabla SQL conectada todavía)."""
    return {
        proveedor: {
            "intentos": a.intentos,
            "exitosos": a.exitosos,
            "fallidos": a.fallidos,
            "latencia_promedio_ms": a.latencia_promedio_ms,
        }
        for proveedor, a in _acumuladores.items()
    }


def resetear() -> None:
    """Solo para tests — limpia el acumulador in-memory entre casos. Ver fixture autouse en
    `conftest.py`."""
    _acumuladores.clear()
