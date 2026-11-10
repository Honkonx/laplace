"""db/codigos_repo.py — Códigos de acceso (`codigos_acceso`): activar, generar, listar, asignar.

Port de `activar_codigo`/`generar_codigos_lote`/`listar_codigos`/`asignar_codigo` de
db_query.py. Regla dura: 1 código = 1 usuario, irreversible;
`device_id_asignado` (si está seteado) fija el único device_id que puede activarlo.
`generar_codigos_lote`/`listar_codigos`/`asignar_codigo` ningún workflow n8n las llamaba —
son herramientas de gestión del negocio (vender códigos), expuestas ahora como comandos de
admin del bot (ver `backend/api/bot/laplace_bot.py`).
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.db.auditoria_repo import registrar_cambio_plan
from backend.api.models.usuarios import CodigoAcceso, Usuario


def _now_str() -> str:
    """`creado_en`/`usado_en` — normalizado a UTC 2026-09-09 (ver docstring de
    `jobs_repo._now_str`). Filas anteriores a este commit pueden estar en hora local de Chile.
    Distinto de `hoy`/`activo_hasta` más abajo (día calendario de negocio, se queda en hora
    local — no es "cuándo pasó algo", es "hasta qué día está vigente el plan")."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def activar_codigo(db: Session, codigo: str, device_id: str) -> dict:
    codigo = codigo.strip().upper()
    fila = db.query(CodigoAcceso).filter(CodigoAcceso.codigo == codigo).first()

    if fila is None:
        return {"activado": False, "error": "codigo_invalido",
                "mensaje": "Código incorrecto. Verifica que lo ingresaste bien."}
    if fila.usado == 1:
        return {"activado": False, "error": "codigo_usado",
                "mensaje": "Este código ya fue utilizado por otro usuario."}
    if fila.device_id_asignado and fila.device_id_asignado != device_id:
        return {"activado": False, "error": "codigo_no_asignado",
                "mensaje": "Este código no está disponible para tu dispositivo."}

    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    hoy = datetime.now().strftime("%Y-%m-%d")
    if usuario and usuario.plan not in ("free", None) and usuario.activo_hasta and usuario.activo_hasta >= hoy:
        return {"activado": False, "error": "plan_activo",
                "mensaje": f"Ya tienes un plan {usuario.plan} activo hasta {usuario.activo_hasta}."}

    activo_hasta = (datetime.now() + timedelta(days=fila.dias)).strftime("%Y-%m-%d")
    ahora = _now_str()
    plan_anterior = usuario.plan if usuario is not None else None

    fila.usado = 1
    fila.device_id_usado = device_id
    fila.usado_en = ahora

    if usuario is None:
        db.add(Usuario(device_id=device_id, activo=1, plan=fila.plan, activo_hasta=activo_hasta,
                        origen="app", creado_en=ahora))
    else:
        usuario.plan = fila.plan
        usuario.activo_hasta = activo_hasta
        usuario.activo = 1

    db.commit()
    # Trazabilidad de POR QUÉ cambió el plan (código canjeado, no asignación manual de admin) —
    # ver models/auditoria.py::HistorialPlan.
    registrar_cambio_plan(db, device_id, plan_anterior, fila.plan, medio="codigo", detalle=codigo)
    return {"activado": True, "plan": fila.plan, "dias": fila.dias, "activo_hasta": activo_hasta,
            "mensaje": f"¡Plan {fila.plan.upper()} activado hasta {activo_hasta}!"}


def _generar_codigo_unico(db: Session, plan: str) -> str:
    """Formato `KS-PLAN-XXXXXXX`, excluye caracteres confusos (O/0/I/1) — mismo generador que
    el original. Reintenta hasta 10 veces si colisiona (extremadamente improbable)."""
    chars = (string.ascii_uppercase + string.digits).translate(str.maketrans("", "", "O0I1"))
    prefijo = "PRO" if plan == "pro" else "MAX"
    for _ in range(10):
        parte = "".join(secrets.choice(chars) for _ in range(7))
        codigo = f"KS-{prefijo}-{parte}"
        if db.query(CodigoAcceso).filter(CodigoAcceso.codigo == codigo).first() is None:
            return codigo
    raise RuntimeError("No se pudo generar un código único tras 10 intentos")


def generar_codigos_lote(db: Session, plan: str, dias: int, cantidad: int) -> dict:
    plan = plan.lower()
    if plan not in ("pro", "max"):
        return {"error": "plan inválido: usar pro o max"}
    if not (1 <= cantidad <= 100):
        return {"error": "cantidad debe estar entre 1 y 100"}
    if not (1 <= dias <= 3650):
        return {"error": "dias debe estar entre 1 y 3650"}

    ahora = _now_str()
    generados = []
    for _ in range(cantidad):
        codigo = _generar_codigo_unico(db, plan)
        db.add(CodigoAcceso(codigo=codigo, plan=plan, dias=dias, usado=0, creado_en=ahora))
        generados.append(codigo)
    db.commit()
    return {"generados": len(generados), "plan": plan, "dias": dias, "codigos": generados}


def listar_codigos(db: Session, filtro: str = "disponibles") -> dict:
    query = db.query(CodigoAcceso)
    if filtro == "disponibles":
        query = query.filter(CodigoAcceso.usado == 0)
    elif filtro == "usados":
        query = query.filter(CodigoAcceso.usado == 1)
    filas = query.order_by(CodigoAcceso.creado_en.desc()).all()

    codigos = [
        {
            "codigo": f.codigo, "plan": f.plan, "dias": f.dias, "usado": bool(f.usado),
            "device_id_asignado": f.device_id_asignado, "device_id_usado": f.device_id_usado,
            "creado_en": f.creado_en, "usado_en": f.usado_en,
        }
        for f in filas
    ]
    return {"filtro": filtro, "total": len(codigos), "codigos": codigos}


def asignar_codigo(db: Session, codigo: str, device_id: str) -> dict:
    """`device_id` vacío libera la asignación (código vuelve a ser genérico)."""
    codigo = codigo.strip().upper()
    fila = db.query(CodigoAcceso).filter(CodigoAcceso.codigo == codigo).first()
    if fila is None:
        return {"asignado": False, "error": "Código no encontrado"}
    if fila.usado == 1:
        return {"asignado": False, "error": "El código ya fue utilizado, no se puede reasignar"}

    nuevo_asignado = device_id or None
    fila.device_id_asignado = nuevo_asignado
    db.commit()

    if nuevo_asignado:
        return {"asignado": True, "codigo": codigo, "device_id": nuevo_asignado,
                "mensaje": f"Código {codigo} reservado para {nuevo_asignado}"}
    return {"asignado": True, "codigo": codigo, "device_id": None,
            "mensaje": f"Código {codigo} liberado (ahora es genérico)"}
