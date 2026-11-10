"""
db/usuarios_repo.py — Acceso a `usuarios`, `uso_diario_app`, `uso_diario_ia_app`.

Port de las funciones de db_query.py que WF-A (Telegram) y WF-A2 (App) llaman
hoy vía `db_query <funcion> '<json>'`. Misma lógica de negocio (mismos límites, mismas reglas
de admin) — SQLAlchemy ORM en vez de `sqlite3` crudo, devuelve dict/tuplas Python en vez del
`ok()/error()` de n8n (el router HTTP decide el formato de respuesta).

Nota sobre `verificar_limite`: en WF-A (`Verificar Límite Plan`, wfa-045) y WF-B (`Verificar
Límite Plan`, wfb-020) la llamada equivalente en n8n tiene un bug real (variable no declarada
en el `try`, la excepción cae al `catch` que hace `puede = true` — fail-open, el límite de
plan `pro` nunca se aplica). Ese bug NO se reproduce acá: si la consulta falla, la excepción
se propaga al caller (no hay un `try/except` que la esconda) — fail-closed por diseño, más
seguro para el negocio que fail-open.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.config import settings
from backend.api.db.auditoria_repo import registrar_accion_admin
from backend.api.db.jobs_repo import rango_utc_dia_chile
from backend.api.models.usuarios import UsoDiarioApp, UsoDiarioIaApp, Usuario
from backend.api.models.jobs import Job
from backend.api.models.predicciones import AnalisisComparativo

LIMITES_IA_TELEGRAM = {"free": 0, "pro": 10, "max": 30}
MAX_FAVORITOS_LIGAS = 3
# rol — 2026-09-10, separado de plan (ver models/usuarios.py §v7). "agente" es la identidad de
# servicio de `laplace-agents` (hoy solo un string suelto `USUARIO_SISTEMA` en
# laplace_agents/core.py, sin fila real en `usuarios` todavía).
ROLES_VALIDOS = ("usuario", "admin", "agente")


def _hoy() -> str:
    """Día calendario de negocio (partición de `uso_diario_app`/`uso_diario_ia_app`,
    `activo_hasta`) — deliberadamente NO es UTC: es "qué día es" para el usuario, no "cuándo
    pasó algo" en el sistema (ver `jobs_repo.rango_utc_dia_chile` para la contraparte que sí
    filtra columnas de timestamp UTC como `Job.creado_en`)."""
    return datetime.now().strftime("%Y-%m-%d")


def _now_str() -> str:
    """`creado_en` de `usuarios` — normalizado a UTC 2026-09-09 (ver docstring de
    `jobs_repo._now_str`). Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def _es_admin(identificador: str) -> bool:
    return identificador in settings.admin_ids


def _tiene_rol_admin(usuario: Usuario | None) -> bool:
    """Segunda fuente de admin, además de `_es_admin` (lista fija `settings.admin_ids` en
    `.env`) — un usuario promovido a `rol='admin'` (vía `/gestionarusuario rol:admin` en
    Telegram o el futuro dashboard) también cuenta, sin necesitar tocar `.env`."""
    return usuario is not None and usuario.rol == "admin"


def verificar_acceso(db: Session, user_id: str) -> dict:
    """Plan + flag admin de un usuario de Telegram (`device_id` guarda el `user_id` numérico
    de Telegram en la misma columna que usa la app para su `device_id` — mismo esquema que
    el original)."""
    usuario = db.query(Usuario).filter(Usuario.device_id == user_id).first()
    if _es_admin(user_id) or _tiene_rol_admin(usuario):
        return {"autorizado": True, "plan": "admin", "es_admin": True}

    if usuario is None:
        return {"autorizado": False, "plan": None, "es_admin": False}
    return {"autorizado": bool(usuario.activo), "plan": usuario.plan, "es_admin": False}


def verificar_limite(db: Session, user_id: str, plan: str) -> dict:
    """Límite diario de análisis con IA para Telegram (plan `pro`=10/día, `max`=30/día,
    `free`=0 pero siempre `puede=True` porque free no pide IA, solo estadístico)."""
    if _es_admin(user_id) or plan == "admin":
        return {"puede": True, "plan": "admin", "limite": 9999, "usados": 0,
                "restantes": 9999, "es_free": False, "es_admin": True}

    limite = LIMITES_IA_TELEGRAM.get(plan, 0)

    if plan == "free":
        return {"puede": True, "plan": plan, "limite": 0, "usados": 0,
                "restantes": 0, "es_free": True, "es_admin": False}

    if not user_id:
        return {"puede": False, "plan": plan, "limite": limite, "usados": 0,
                "restantes": 0, "es_free": False, "es_admin": False}

    # `Job.creado_en` se persiste en UTC (ver jobs_repo._now_str) pero el límite diario es un
    # concepto de negocio en hora de Chile — un LIKE 'YYYY-MM-DD%' con `_hoy()` (local) ya no
    # es válido acá; se usa el rango UTC del día de Chile (ver jobs_repo.rango_utc_dia_chile).
    inicio_utc, fin_utc = rango_utc_dia_chile()
    usados = (
        db.query(Job)
        .filter(Job.user_id == user_id, Job.plan.in_(["pro", "max"]),
                Job.status.in_(["listo", "procesando"]),
                Job.creado_en >= inicio_utc, Job.creado_en < fin_utc)
        .count()
    )
    puede = usados < limite
    return {"puede": puede, "plan": plan, "limite": limite, "usados": usados,
            "restantes": max(0, limite - usados), "es_free": False, "es_admin": False}


def registrar_usuario_telegram(db: Session, user_id: str, chat_id: str, first_name: str) -> dict:
    """Idempotente: si ya existe no toca plan/datos (solo informa)."""
    existente = db.query(Usuario).filter(Usuario.device_id == user_id).first()
    if existente is not None:
        return {"nuevo": False, "plan": existente.plan, "user_id": user_id,
                "mensaje": "Usuario ya registrado"}

    db.add(Usuario(device_id=user_id, activo=1, plan="free",
                    nickname=first_name or None, origen="telegram", creado_en=_now_str()))
    db.commit()
    return {"nuevo": True, "plan": "free", "user_id": user_id,
            "mensaje": f"Usuario {user_id} registrado como free"}


def registrar_usuario_app(db: Session, device_id: str, nickname: str) -> dict:
    """Registra/actualiza un usuario de la app. Nickname único (case-insensitive)."""
    if nickname:
        choque = (
            db.query(Usuario)
            .filter(Usuario.nickname.isnot(None))
            .filter(Usuario.device_id != device_id)
            .all()
        )
        if any((u.nickname or "").lower() == nickname.lower() for u in choque):
            return {"registrado": False, "error": "nickname_ocupado",
                    "mensaje": f'El nombre "{nickname}" ya está en uso. Elige otro.'}

    existente = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    if existente is not None:
        if nickname:
            existente.nickname = nickname
            db.commit()
        return {"registrado": True, "nuevo": False, "device_id": device_id,
                "plan": existente.plan, "nickname": nickname or existente.nickname,
                "activo_hasta": existente.activo_hasta}

    db.add(Usuario(device_id=device_id, activo=1, plan="free", nickname=nickname or None,
                    origen="app", creado_en=_now_str()))
    db.commit()
    return {"registrado": True, "nuevo": True, "device_id": device_id, "plan": "free",
            "nickname": nickname or None, "activo_hasta": None}


def obtener_usuario_app(db: Session, device_id: str) -> dict:
    """Perfil completo para ProfileScreen. Auto-registra si no existe. Degrada a `free` si
    `activo_hasta` venció."""
    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    if usuario is None:
        usuario = Usuario(device_id=device_id, activo=1, plan="free", origen="app", creado_en=_now_str())
        db.add(usuario)
        db.commit()

    hoy = _hoy()
    # `rol == 'admin'` nunca se degrada a free por vencimiento — un admin no depende de
    # `activo_hasta` (ese campo es del ciclo de vida del PLAN pagado, no del permiso).
    if usuario.activo_hasta and usuario.plan != "free" and usuario.rol != "admin" and usuario.activo_hasta < hoy:
        usuario.plan = "free"
        usuario.activo_hasta = None
        db.commit()

    uso = db.get(UsoDiarioApp, (device_id, hoy))
    usadas_hoy = uso.predicciones_usadas if uso else 0

    es_admin = _tiene_rol_admin(usuario) or _es_admin(device_id)
    limite_py = 999 if es_admin else {"free": 999, "pro": 999, "max": 999}.get(usuario.plan, 999)
    limite_ia = 999 if es_admin else {"free": 0, "pro": 10, "max": 999}.get(usuario.plan, 0)

    return {
        "device_id": device_id, "plan": usuario.plan, "nickname": usuario.nickname,
        "activo_hasta": usuario.activo_hasta, "creado_en": usuario.creado_en,
        "predicciones_hoy": usadas_hoy, "limite_diario": limite_py,
        "restantes_hoy": max(0, limite_py - usadas_hoy), "puede_pedir": usadas_hoy < limite_py,
        "limite_ia_diario": limite_ia,
    }


def verificar_limite_app(db: Session, device_id: str) -> dict:
    """Límite de análisis Python/estadístico (no IA) por device_id — hoy 999/día para todos
    los planes, la restricción real de negocio está en `verificar_limite_ia_app`."""
    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    plan = usuario.plan if usuario else "free"
    limite = {"free": 999, "pro": 999, "max": 999}.get(plan, 999)

    if _tiene_rol_admin(usuario) or _es_admin(device_id):
        return {"puede": True, "plan": "admin", "usadas": 0, "limite": limite, "restantes": limite}

    uso = db.get(UsoDiarioApp, (device_id, _hoy()))
    usadas = uso.predicciones_usadas if uso else 0
    return {"puede": usadas < limite, "plan": plan, "usadas": usadas,
            "limite": limite, "restantes": max(0, limite - usadas)}


def verificar_limite_ia_app(db: Session, device_id: str) -> dict:
    """free=0/día, pro=10/día, max/admin=999/día (ilimitado efectivo)."""
    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    plan = usuario.plan if usuario else "free"
    limite = {"free": 0, "pro": 10, "max": 999}.get(plan, 0)

    if _tiene_rol_admin(usuario) or _es_admin(device_id):
        return {"puede": True, "plan": "admin", "usados_hoy": 0, "limite_ia": limite, "restantes_ia": limite}

    uso = db.get(UsoDiarioIaApp, (device_id, _hoy()))
    usados = uso.usados if uso else 0
    return {"puede": usados < limite, "plan": plan, "usados_hoy": usados,
            "limite_ia": limite, "restantes_ia": max(0, limite - usados)}


def registrar_uso_app(db: Session, device_id: str) -> dict:
    hoy = _hoy()
    uso = db.get(UsoDiarioApp, (device_id, hoy))
    if uso is None:
        uso = UsoDiarioApp(device_id=device_id, fecha=hoy, predicciones_usadas=1)
        db.add(uso)
    else:
        uso.predicciones_usadas += 1
    db.commit()
    return {"registrado": True, "usadas_hoy": uso.predicciones_usadas}


def registrar_uso_ia_app(db: Session, device_id: str) -> dict:
    hoy = _hoy()
    uso = db.get(UsoDiarioIaApp, (device_id, hoy))
    if uso is None:
        uso = UsoDiarioIaApp(device_id=device_id, fecha=hoy, usados=1)
        db.add(uso)
    else:
        uso.usados += 1
    db.commit()
    return {"registrado": True, "usados_hoy": uso.usados}


def leer_racha(db: Session, device_id: str | None = None) -> dict:
    """Racha actual (consecutivos aciertos o fallos), global o de un device_id."""
    if device_id:
        filas = (
            db.query(AnalisisComparativo.pick_correcto)
            .join(Job, Job.match_id == AnalisisComparativo.partido_id)
            .filter(Job.device_id_app == device_id, Job.origen == "app",
                    AnalisisComparativo.pick_correcto.isnot(None))
            .order_by(Job.completado_en.desc())
            .limit(50)
            .all()
        )
    else:
        filas = (
            db.query(AnalisisComparativo.pick_correcto)
            .filter(AnalisisComparativo.pick_correcto.isnot(None))
            .order_by(AnalisisComparativo.fecha.desc(), AnalisisComparativo.creado_en.desc())
            .limit(50)
            .all()
        )

    if not filas:
        return {"racha": 0, "tipo": "sin_datos", "ultimo_resultado": None, "total_evaluados": 0}

    valores = [f[0] for f in filas]
    primer_val = valores[0]
    racha = 0
    for v in valores:
        if v == primer_val:
            racha += 1
        else:
            break

    return {
        "racha": racha,
        "tipo": "aciertos" if primer_val == 1 else "fallos",
        "ultimo_resultado": "acierto" if primer_val == 1 else "fallo",
        "total_evaluados": len(valores),
    }


def listar_usuarios(db: Session, q: str = "", limit: int = 50, offset: int = 0) -> dict:
    """Lista paginada para el dashboard de admin (`routers/admin.py`) — `q` busca por
    coincidencia parcial (case-insensitive) en `username` o `device_id`, ambos posibles
    identificadores de un usuario según su origen (Telegram/app usan device_id, login
    usuario+clave usa username)."""
    query = db.query(Usuario)
    if q:
        patron = f"%{q}%"
        query = query.filter(Usuario.username.ilike(patron) | Usuario.device_id.ilike(patron))
    total = query.count()
    filas = query.order_by(Usuario.id.desc()).offset(offset).limit(limit).all()
    usuarios = [
        {"id": u.id, "device_id": u.device_id, "username": u.username, "activo": bool(u.activo),
         "plan": u.plan, "rol": u.rol, "origen": u.origen, "nickname": u.nickname,
         "activo_hasta": u.activo_hasta, "creado_en": u.creado_en}
        for u in filas
    ]
    return {"total": total, "limit": limit, "offset": offset, "usuarios": usuarios}


def asignar_rol(db: Session, device_id: str, rol: str, actor_admin_id: str | None = None) -> dict:
    """Cambia el `rol` (usuario|admin|agente) de un usuario existente — separado de `plan`
    desde 2026-09-10 (ver models/usuarios.py §v7). Usado por `/gestionarusuario rol:<rol>`
    (Telegram, `laplace_bot.py`) — el dashboard web/PWA queda para una ronda futura (v1 del
    dashboard es solo-lectura por decisión ya tomada, ver `routers/admin.py`)."""
    if rol not in ROLES_VALIDOS:
        return {"error": f"rol inválido: {rol}. Válidos: {ROLES_VALIDOS}"}

    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    if usuario is None:
        return {"error": f"usuario {device_id} no encontrado"}

    rol_anterior = usuario.rol
    usuario.rol = rol
    db.commit()
    if actor_admin_id:
        registrar_accion_admin(
            db, actor_admin_id=actor_admin_id, accion="cambiar_rol",
            detalle=f"{device_id}: {rol_anterior} -> {rol}",
        )
    return {"accion": "rol_actualizado", "device_id": device_id, "rol_anterior": rol_anterior, "rol": rol}


def obtener_usuario_por_username(db: Session, username: str) -> Usuario | None:
    return db.query(Usuario).filter(Usuario.username == username).first()


def crear_usuario_credenciales(db: Session, username: str, password_hash: str, origen: str, terms_version: str) -> Usuario:
    """Registro por usuario+clave (app/web, sin correo) — agregado 2026-09-07. `device_id`
    pasa a ser simplemente el identificador interno único de la fila (un UUID generado acá),
    no "el dispositivo físico" como para el resto de usuarios de app — no hay device real
    todavía para alguien que se registra por usuario/clave."""
    import uuid

    nuevo = Usuario(
        device_id=str(uuid.uuid4()), activo=1, plan="free", creado_en=_now_str(),
        origen=origen, username=username, password_hash=password_hash,
        terms_version=terms_version, terms_accepted_at=_now_str(),
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


def listar_favoritos_ligas(db: Session, user_id: str) -> list[str]:
    """Ligas favoritas de un usuario (`/favoritos` del bot, agregado 2026-09-08) — texto libre
    tal cual lo escribió (no hay catálogo fijo de ligas), en orden de agregado."""
    usuario = db.query(Usuario).filter(Usuario.device_id == user_id).first()
    if usuario is None or not usuario.favoritos_ligas:
        return []
    return [liga for liga in usuario.favoritos_ligas.split("|") if liga]


def agregar_favorito_liga(db: Session, user_id: str, liga: str) -> dict:
    """Agrega `liga` a los favoritos de `user_id` — máximo `MAX_FAVORITOS_LIGAS`, sin
    duplicados (comparación case-insensitive)."""
    liga = liga.strip()
    if not liga:
        return {"agregado": False, "error": "liga_vacia", "favoritos": [],
                "mensaje": "Indica el nombre de la liga a agregar."}

    usuario = db.query(Usuario).filter(Usuario.device_id == user_id).first()
    if usuario is None:
        return {"agregado": False, "error": "usuario_no_encontrado", "favoritos": [],
                "mensaje": "Usa /start primero para registrarte."}

    actuales = listar_favoritos_ligas(db, user_id)
    if any(l.lower() == liga.lower() for l in actuales):
        return {"agregado": False, "error": "ya_existe", "favoritos": actuales,
                "mensaje": f'"{liga}" ya está en tus favoritos.'}
    if len(actuales) >= MAX_FAVORITOS_LIGAS:
        return {"agregado": False, "error": "limite_alcanzado", "favoritos": actuales,
                "mensaje": f"Ya tienes {MAX_FAVORITOS_LIGAS} ligas favoritas (el máximo). "
                           "Quita una con /favoritos quitar <liga>."}

    nuevos = actuales + [liga]
    usuario.favoritos_ligas = "|".join(nuevos)
    db.commit()
    return {"agregado": True, "favoritos": nuevos, "mensaje": f'"{liga}" agregada a tus favoritos.'}


def quitar_favorito_liga(db: Session, user_id: str, liga: str) -> dict:
    """Quita `liga` de los favoritos de `user_id` (comparación case-insensitive)."""
    liga = liga.strip()
    usuario = db.query(Usuario).filter(Usuario.device_id == user_id).first()
    if usuario is None:
        return {"quitado": False, "error": "usuario_no_encontrado", "favoritos": [],
                "mensaje": "Usa /start primero para registrarte."}

    actuales = listar_favoritos_ligas(db, user_id)
    nuevos = [l for l in actuales if l.lower() != liga.lower()]
    if len(nuevos) == len(actuales):
        return {"quitado": False, "error": "no_encontrada", "favoritos": actuales,
                "mensaje": f'"{liga}" no estaba en tus favoritos.'}

    usuario.favoritos_ligas = "|".join(nuevos) if nuevos else None
    db.commit()
    return {"quitado": True, "favoritos": nuevos, "mensaje": f'"{liga}" quitada de tus favoritos.'}


def vincular_cuenta_telegram(db: Session, telegram_user_id: str, cuenta_web: Usuario) -> dict:
    """Sincroniza el plan activo y `activo_hasta` entre una cuenta con credenciales (`cuenta_web`,
    creada en Web o App Android) y la fila de Telegram (`device_id == telegram_user_id`), sin
    violar la restricción UNIQUE de `usuarios.username`. El plan de mayor jerarquía vigente
    (`free` < `pro` < `max`) se propaga a ambas filas y queda registrado en auditoría."""
    from backend.api.db.auditoria_repo import registrar_cambio_plan

    usuario_tg = db.query(Usuario).filter(Usuario.device_id == telegram_user_id).first()
    if usuario_tg is None:
        usuario_tg = Usuario(
            device_id=telegram_user_id, activo=1, plan="free",
            origen="telegram", creado_en=_now_str(),
        )
        db.add(usuario_tg)
        db.flush()

    hoy = _hoy()
    jerarquia = {"free": 0, "pro": 1, "max": 2}

    def _plan_vigente(u: Usuario) -> tuple[str, str | None]:
        plan_u = (u.plan or "free").lower()
        if plan_u != "free" and u.activo_hasta and u.activo_hasta < hoy and u.rol != "admin":
            return "free", None
        return plan_u, u.activo_hasta

    plan_web, vence_web = _plan_vigente(cuenta_web)
    plan_tg, vence_tg = _plan_vigente(usuario_tg)

    rango_web = jerarquia.get(plan_web, 0)
    rango_tg = jerarquia.get(plan_tg, 0)

    if rango_web > rango_tg or (rango_web == rango_tg and (vence_web or "") >= (vence_tg or "")):
        plan_final, vence_final = plan_web, vence_web
    else:
        plan_final, vence_final = plan_tg, vence_tg

    plan_tg_anterior = usuario_tg.plan
    plan_web_anterior = cuenta_web.plan

    usuario_tg.plan = plan_final
    usuario_tg.activo_hasta = vence_final
    if not usuario_tg.nickname and cuenta_web.username:
        usuario_tg.nickname = cuenta_web.username

    cuenta_web.plan = plan_final
    cuenta_web.activo_hasta = vence_final
    db.commit()

    if plan_tg_anterior != plan_final:
        registrar_cambio_plan(
            db, telegram_user_id, plan_tg_anterior, plan_final,
            medio="codigo", detalle=f"vincular:{cuenta_web.username}",
        )
    if plan_web_anterior != plan_final:
        registrar_cambio_plan(
            db, cuenta_web.device_id, plan_web_anterior, plan_final,
            medio="codigo", detalle=f"vincular_tg:{telegram_user_id}",
        )

    return {
        "vinculado": True,
        "username": cuenta_web.username,
        "plan": plan_final,
        "activo_hasta": vence_final,
        "mensaje": (
            f"Cuenta <b>{cuenta_web.username}</b> vinculada con éxito. "
            f"Plan activo sincronizado: <b>{plan_final.upper()}</b>"
            + (f" (hasta {vence_final})." if vence_final else ".")
        ),
    }

