"""jobs.py — los trabajos programados del modelo Laplace (los registra `main.py`, que solo les pasa su fábrica de sesiones).

- `evaluar_modelo_diario`: evalúa el modelo en sombra (`origen sombra`) y el activo (`origen vivo`) contra los resultados verificados, compara en vivo contra las demás variantes del laboratorio
  y avisa UNA vez al cruzar 50 y 200 partidos con resultado. No promueve nada: pasar a `activo` exige aprobador (`registro.promover`).
- `reentrenar_semanal`: lanza el reentreno por subproceso (el servidor no tiene numpy) y registra el resultado.
Reciben la fábrica de sesiones por parámetro: así no importan `main` y se prueban con una base en memoria.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

from sqlalchemy.orm import Session

log = logging.getLogger("laplace.modelo_jobs")


async def evaluar_modelo_diario(fabrica_sesion: Callable[[], Session]) -> None:
    from backend.api.db import scheduler_repo
    from backend.api.ml.laplace import auditoria, deriva, registro
    from backend.api.routers.scheduler import JOB_MODELO_LAPLACE
    from backend.api.services import laboratorio_pronosticos
    from backend.api.services.alerting import emitir_alerta

    with fabrica_sesion() as db:
        try:
            partes = []
            proximos = await asyncio.to_thread(laboratorio_pronosticos.registrar_proximos, db)
            partes.append(f"proximos: {proximos['registrados']} nuevos de {proximos['candidatos']}")
            previo = scheduler_repo.ultimo_run(db, JOB_MODELO_LAPLACE)
            coincidencia = re.search(r"lab=(\d+)", (previo.detalle or "") if previo else "")
            previo_lab = int(coincidencia.group(1)) if coincidencia else 0
            for modelo, origen in ((registro.modelo_sombra(db), "sombra"), (registro.modelo_vigente(db), "vivo")):
                if modelo is None:
                    continue
                informe = await asyncio.to_thread(registro.evaluar_sombra, db, modelo.id, origen)
                partes.append(f"{origen}: " + ("sin casos todavía" if informe is None else f"{informe['propio']['n']} casos"))
                try:  # accesorio: la memoria de errores nunca rompe la evaluación diaria
                    partes.append(f"errores+{await asyncio.to_thread(auditoria.cerrar_bucle, db, modelo.id)}")
                except Exception:
                    db.rollback()
                    log.exception("no se pudo cerrar el bucle de errores del modelo %s", modelo.id)
            try:
                cadena = await asyncio.to_thread(auditoria.verificar_cadena, db)
                partes.append("cadena ok" if cadena["ok"] else f"CADENA ROTA en {cadena['ruptura']['id']}")
                if not cadena["ok"]:
                    emitir_alerta("modelo_laplace_cadena_rota", cadena["ruptura"])
            except Exception:
                db.rollback()
                log.exception("no se pudo verificar la cadena de sellos")
            try:  # MP-12: alerta de deriva de lo que el modelo produce (accesoria: nunca rompe la evaluación)
                activo = registro.modelo_vigente(db)
                if activo is not None:
                    d = await asyncio.to_thread(deriva.deriva_de_salidas, db, activo.id)
                    partes.append(f"DERIVA {d['peor']} PSI {d['psi'][d['peor']]}" if d["alarma"] else ("deriva ok" if d["psi"] else "deriva: sin base"))
                    if d["alarma"]:
                        emitir_alerta("modelo_laplace_deriva", {k: d[k] for k in ("modelo_id", "psi", "peor", "n_referencia", "n_reciente")})
            except Exception:
                db.rollback()
                log.exception("no se pudo calcular la deriva del modelo")
            vivo = laboratorio_pronosticos.comparar_en_vivo(db)
            for cruce in laboratorio_pronosticos.cruces_de_umbral(previo_lab, vivo["evaluados"]):
                log.info("modelo Laplace: evidencia en vivo suficiente (%s) con %s partidos", cruce, vivo["evaluados"])
                emitir_alerta("modelo_laplace_evidencia", {"kind": cruce, "evaluados": vivo["evaluados"]})
            partes.append(f"lab={vivo['evaluados']}")
            scheduler_repo.registrar_run(db, JOB_MODELO_LAPLACE, ok=True, detalle="; ".join(partes))
        except Exception:
            log.exception("Fallo la evaluación diaria del modelo Laplace")
            scheduler_repo.registrar_run(db, JOB_MODELO_LAPLACE, ok=False, detalle="excepcion inesperada")


async def reentrenar_semanal(fabrica_sesion: Callable[[], Session]) -> None:
    from backend.api.db import scheduler_repo
    from backend.api.ml.laplace import job_reentreno
    from backend.api.routers.scheduler import JOB_REENTRENO_LAPLACE

    if not job_reentreno.reentreno_activo():
        log.info("reentreno del modelo Laplace desactivado (LAPLACE_REENTRENO_AUTOMATICO)")
        return
    with fabrica_sesion() as db:
        try:
            r = await asyncio.to_thread(job_reentreno.ejecutar_reentreno)
            scheduler_repo.registrar_run(db, JOB_REENTRENO_LAPLACE, ok=r["ok"], detalle=str(r.get("detalle", ""))[:300])
        except Exception:
            log.exception("Fallo el reentreno semanal del modelo Laplace")
            scheduler_repo.registrar_run(db, JOB_REENTRENO_LAPLACE, ok=False, detalle="excepcion inesperada")
