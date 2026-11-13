"""
db/jobs_repo.py — Acceso a `jobs` (cola de análisis Telegram + App).

Port de las funciones de cola de trabajo de db_query.py. En el diseño nuevo
(FastAPI, sin cron de 15s) esta tabla sigue existiendo para: (1) que la app pueda hacer polling
de un análisis en curso vía `GET /analisis/{job_id}`, y (2) deduplicar (`verificar_job_activo`)
para no lanzar dos análisis del mismo partido en paralelo — pero el procesamiento real ya NO
pasa por `leer_job_pendiente` en un loop; `services/analisis_completo.py` marca
`procesando`→`listo`/`error` de punta a punta dentro de la misma corrutina, así que un job no
puede quedar "colgado" en `procesando` para siempre por un fallo silencioso a mitad de camino
(la clase entera de bug de WF-B `Guardar en BD` con `cmd: ''` deja de ser posible).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.jobs import Job

TZ_CHILE = ZoneInfo("America/Santiago")


def _now_str() -> str:
    """`creado_en`/`completado_en` de `jobs` — normalizado a UTC 2026-09-09 (auditoría de
    fechas mezclando `datetime.now()`/`utc_ahora()` entre repos sin ninguna marca que
    distinga cuál es cuál al leer la columna). Limitación conocida: filas escritas ANTES de
    este commit quedaron en hora local de Chile (aprox. UTC-4/-3) — no compararlas ciegamente
    contra filas nuevas sin tenerlo en cuenta."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def rango_utc_dia_chile(fecha_chile: str | None = None) -> tuple[str, str]:
    """Convierte un día calendario de Chile (`fecha_chile` formato YYYY-MM-DD; "hoy" en Chile
    si no se pasa) al rango UTC `[inicio, fin)` que le corresponde.

    Necesario porque `Job.creado_en`/`Job.completado_en` se persisten en UTC (ver `_now_str`)
    mientras varias consultas de negocio (límite diario de análisis, "¿ya hay un análisis de
    HOY para este partido?") distinguen el día en hora de Chile, no UTC — un
    `LIKE 'YYYY-MM-DD%'` sobre la columna dejó de ser válido al normalizarla a UTC (antes
    funcionaba solo porque columna y 'hoy' eran ambos hora local sin timezone, por accidente,
    no por diseño). Compartida por `usuarios_repo.verificar_limite` y
    `analisis_repo.verificar_partido_completo` — ambas filtran `Job` por el día de Chile."""
    if fecha_chile:
        inicio_cl = datetime.strptime(fecha_chile, "%Y-%m-%d").replace(tzinfo=TZ_CHILE)
    else:
        ahora_cl = datetime.now(TZ_CHILE)
        inicio_cl = ahora_cl.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_cl = inicio_cl + timedelta(days=1)
    inicio_utc = inicio_cl.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fin_utc = fin_cl.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return inicio_utc, fin_utc


def crear_job(db: Session, match_id: str, fecha: str, chat_id: str, user_id: str, plan: str = "free") -> dict:
    job_id = f"job_{match_id}_{int(datetime.now().timestamp() * 1000)}"
    db.add(Job(job_id=job_id, match_id=match_id, fecha_partido=fecha, chat_id=chat_id,
               user_id=user_id, plan=plan, origen="telegram", status="pendiente",
               intentos=0, creado_en=_now_str()))
    db.commit()
    return {"job_id": job_id, "match_id": match_id, "chat_id": chat_id, "user_id": user_id, "plan": plan}


MAX_ESPERAS_POR_PARTIDO = 50


def registrar_espera(db: Session, match_id: str, fecha: str, chat_id: str, user_id: str, plan: str = "free") -> dict | None:
    """Anota que `user_id` espera el análisis que otra persona ya pidió para `match_id` (H-011, 2026-11-11): antes se le decía «en progreso» y el resultado nunca le llegaba, porque el análisis
    se envía solo al chat que lo pidió. Devuelve None si ya hay demasiada gente esperando ese partido."""
    ya = db.query(Job).filter(Job.match_id == match_id, Job.user_id == user_id, Job.origen == "telegram", Job.status.in_(["pendiente", "procesando", "esperando"])).first()
    if ya is not None:
        return {"job_id": ya.job_id, "ya_esperando": True}
    if db.query(Job).filter(Job.match_id == match_id, Job.status == "esperando").count() >= MAX_ESPERAS_POR_PARTIDO:
        return None
    job_id = f"espera_{match_id}_{int(datetime.now().timestamp() * 1000)}_{user_id}"
    db.add(Job(job_id=job_id, match_id=match_id, fecha_partido=fecha, chat_id=chat_id, user_id=user_id, plan=plan, origen="telegram", status="esperando", intentos=0, creado_en=_now_str()))
    db.commit()
    return {"job_id": job_id, "ya_esperando": False}


def esperas_de(db: Session, match_id: str) -> list[Job]:
    return db.query(Job).filter(Job.match_id == match_id, Job.status == "esperando").order_by(Job.creado_en).all()


def crear_job_app(db: Session, match_id: str, fecha: str, device_id: str, plan: str,
                   local: str = "", visitante: str = "", liga: str = "") -> dict:
    job_id = f"job_{match_id}_{int(datetime.now().timestamp() * 1000)}"
    db.add(Job(job_id=job_id, match_id=match_id, fecha_partido=fecha, chat_id="",
               user_id=device_id, device_id_app=device_id, plan=plan, origen="app",
               status="pendiente", intentos=0, creado_en=_now_str(),
               local_app=local, visitante_app=visitante, liga_app=liga))
    db.commit()
    return {"job_id": job_id, "match_id": match_id, "device_id": device_id, "plan": plan}


def verificar_job_activo(db: Session, match_id: str) -> dict:
    """True si ya hay un job pendiente/procesando para este match_id — evita duplicados."""
    job = (
        db.query(Job)
        .filter(Job.match_id == match_id, Job.status.in_(["pendiente", "procesando"]))
        .order_by(Job.creado_en.desc())
        .first()
    )
    if job is None:
        return {"job_activo": False, "job_id": None}
    return {"job_activo": True, "job_id": job.job_id}


def leer_job_pendiente(db: Session) -> dict:
    """Resetea jobs colgados >10min en 'procesando' (huérfanos de una corrida anterior que
    murió a mitad de camino) y devuelve el más antiguo 'pendiente'.

    Nota: en el diseño con orquestación síncrona (`services/analisis_completo.py`) esta
    función ya no la consume un cron — queda para diagnóstico/recuperación manual y para
    compatibilidad si algún día se reintroduce un worker asíncrono."""
    limite = (utc_ahora() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    colgados = db.query(Job).filter(Job.status == "procesando", Job.creado_en < limite).all()
    for j in colgados:
        j.status = "pendiente"
        j.intentos += 1
    if colgados:
        db.commit()

    job = db.query(Job).filter(Job.status == "pendiente").order_by(Job.creado_en.asc()).first()
    if job is None:
        return {"job_id": None}
    return {
        "job_id": job.job_id, "match_id": job.match_id, "fecha_partido": job.fecha_partido,
        "chat_id": job.chat_id, "user_id": job.user_id or "", "plan": job.plan,
        "origen": job.origen, "device_id_app": job.device_id_app or "",
    }


def actualizar_job(db: Session, job_id: str, status: str) -> dict:
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if job is not None:
        job.status = status
        job.completado_en = _now_str()
        db.commit()
    return {"job_id": job_id, "status": status}


def actualizar_job_app(db: Session, job_id: str, status: str, resultado: dict | None) -> dict:
    import json

    job = db.query(Job).filter(Job.job_id == job_id).first()
    if job is None:
        return {"job_id": job_id, "status": status, "guardado": False}
    job.status = status
    job.completado_en = _now_str()
    job.resultado_app = json.dumps(resultado, ensure_ascii=False) if resultado else None
    db.commit()
    return {"job_id": job_id, "status": status, "guardado": True}


def leer_job_especifico(db: Session, job_id: str, device_id: str) -> dict:
    """Filtra por job_id AND (device_id_app OR user_id) — un usuario no puede leer el job de
    otro."""
    import json

    job = (
        db.query(Job)
        .filter(Job.job_id == job_id, (Job.device_id_app == device_id) | (Job.user_id == device_id))
        .first()
    )
    if job is None:
        return {"encontrado": False, "job_id": job_id,
                "error": "Job no encontrado o no pertenece a este dispositivo"}

    contenido = None
    if job.resultado_app:
        try:
            contenido = json.loads(job.resultado_app)
        except Exception:
            contenido = job.resultado_app

    return {
        "encontrado": True, "job_id": job.job_id, "match_id": job.match_id, "status": job.status,
        "plan": job.plan or "free", "creado_en": job.creado_en, "completado_en": job.completado_en,
        "content": contenido,
    }


def listar_jobs(db: Session, status: str = "", limit: int = 50, offset: int = 0) -> dict:
    """Lista paginada de la cola completa (Telegram + app) para el dashboard de admin — `status`
    filtra opcionalmente por `pendiente`/`procesando`/`listo`/`error`; vacío = todos."""
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    total = query.count()
    filas = query.order_by(Job.id.desc()).offset(offset).limit(limit).all()
    jobs = [
        {"job_id": j.job_id, "match_id": j.match_id, "fecha_partido": j.fecha_partido,
         "origen": j.origen, "status": j.status, "intentos": j.intentos, "plan": j.plan,
         "device_id_app": j.device_id_app, "creado_en": j.creado_en, "completado_en": j.completado_en}
        for j in filas
    ]
    return {"total": total, "limit": limit, "offset": offset, "jobs": jobs}


def reset_jobs_colgados(db: Session, timeout_min: int = 15, todos: bool = False) -> dict:
    """Resetea a `error` jobs pendientes/procesando más viejos que `timeout_min`. Corre
    automático cada 15 min vía `AsyncIOScheduler` (ver `main.py::_job_reset_jobs_colgados`,
    cableada 2026-09-09 tras la auditoría que encontró que esta función existía pero nunca se
    llamaba — un job podía quedar huérfano para siempre si el proceso moría a mitad de un
    análisis). También sigue disponible para invocación manual/diagnóstico puntual."""
    limite = (utc_ahora() - timedelta(minutes=timeout_min)).strftime("%Y-%m-%d %H:%M:%S")
    consulta = db.query(Job).filter(Job.status.in_(["pendiente", "procesando", "esperando"]))
    colgados = (consulta if todos else consulta.filter(Job.creado_en < limite)).all()  # `todos`: al arrancar, ningún trabajo de un proceso anterior puede seguir en vuelo

    detalle = []
    for j in colgados:
        status_anterior = j.status
        j.status = "error"
        j.completado_en = _now_str()
        detalle.append({"job_id": j.job_id, "match_id": j.match_id, "status_anterior": status_anterior, "chat_id": j.chat_id, "origen": j.origen})
    if colgados:
        db.commit()
    return {"reseteados": len(colgados), "detalle": detalle, "timeout_min": timeout_min}
