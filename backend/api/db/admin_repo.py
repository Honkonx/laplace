"""db/admin_repo.py — Operaciones de administración manual (`verificar_admin`,
`gestionar_usuario`, `leer_stats_modulos`, `guardar_prediccion_externa`).

Port de las funciones equivalentes de db_query.py — ninguna la llama un
workflow n8n; son herramientas que el dueño del proyecto corría a mano (antes vía
`python3 db_query.py <función> '<json>'`, ahora expuestas como comandos de admin del bot, ver
`backend/api/bot/laplace_bot.py`). `setup_inicial` NO se porta — Alembic ya reemplaza esa
función (creación de esquema), es código muerto en el original.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.config import settings
from backend.api.db.auditoria_repo import registrar_cambio_plan
from backend.api.models.predicciones import AnalisisComparativo, Prediccion
from backend.api.models.usuarios import Usuario

PLANES_VALIDOS = ("free", "pro", "max")
# 2026-09-10 — "admin" ya no es un valor de plan válido (era el pseudo-valor de permiso previo
# a separar `Usuario.rol` de `Usuario.plan`, ver models/usuarios.py §v7 y
# `PROPUESTA_DASHBOARD_ADMIN.md`). El permiso de admin se asigna con
# `usuarios_repo.asignar_rol(db, device_id, "admin", ...)`, nunca con `gestionar_usuario`.
# Verificado (grep) que nada llama `gestionar_usuario`/`PLANES_VALIDOS` con plan="admin" antes
# de sacarlo de la tupla — ni tests, ni `bot/laplace_bot.py::cmd_gestionarusuario` (ese comando
# separa `plan:` de `rol:` desde el mismo cambio de 2026-09-10).


def _now_str() -> str:
    """`creado_en` — normalizado a UTC 2026-09-09 (ver docstring de `jobs_repo._now_str`).
    Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def verificar_admin(user_id: str) -> dict:
    return {"es_admin": user_id in settings.admin_ids, "user_id": user_id}


def gestionar_usuario(db: Session, accion: str, user_id: str, plan: str = "free",
                       actor_admin_id: str | None = None) -> dict:
    """Acciones: agregar | activar | desactivar | cambiar_plan | eliminar.

    `actor_admin_id` (agregado 2026-09-08): quién ejecutó el cambio de plan — se persiste en
    `HistorialPlan.detalle` (ver `models/auditoria.py`) para poder distinguir "código canjeado
    por el usuario" de "asignación manual de este admin puntual". Opcional para no romper
    llamadas existentes que no lo pasan (queda `detalle=None` en ese caso)."""
    if not accion or not user_id:
        return {"error": "accion y user_id son requeridos"}

    if accion in ("agregar", "cambiar_plan") and plan not in PLANES_VALIDOS:
        return {"error": f"plan inválido: {plan}. Válidos: {PLANES_VALIDOS}"}

    usuario = db.query(Usuario).filter(Usuario.device_id == user_id).first()

    if accion == "agregar":
        plan_anterior = usuario.plan if usuario is not None else None
        if usuario is not None:
            usuario.activo, usuario.plan = 1, plan
            db.commit()
            registrar_cambio_plan(db, user_id, plan_anterior, plan, medio="admin", detalle=actor_admin_id)
            return {"accion": "reactivado", "user_id": user_id, "plan": plan}
        db.add(Usuario(device_id=user_id, activo=1, plan=plan, creado_en=_now_str()))
        db.commit()
        registrar_cambio_plan(db, user_id, plan_anterior, plan, medio="admin", detalle=actor_admin_id)
        return {"accion": "agregado", "user_id": user_id, "plan": plan}

    if usuario is None:
        return {"error": f"usuario {user_id} no encontrado"}

    if accion == "activar":
        usuario.activo = 1
        db.commit()
        return {"accion": "activado", "user_id": user_id}
    if accion == "desactivar":
        usuario.activo = 0
        db.commit()
        return {"accion": "desactivado", "user_id": user_id}
    if accion == "cambiar_plan":
        plan_anterior = usuario.plan
        usuario.plan = plan
        db.commit()
        registrar_cambio_plan(db, user_id, plan_anterior, plan, medio="admin", detalle=actor_admin_id)
        return {"accion": "plan_actualizado", "user_id": user_id, "plan": plan}
    if accion == "eliminar":
        db.delete(usuario)
        db.commit()
        return {"accion": "eliminado", "user_id": user_id}

    return {"error": f"accion inválida: {accion}. Válidas: agregar|activar|desactivar|cambiar_plan|eliminar"}


def guardar_prediccion_externa(db: Session, partido_id: str, pick: str, confianza_pct: float,
                                fuente: str = "api_football", detalle_json: dict | str | None = None,
                                job_id: str = "") -> dict:
    if not partido_id:
        return {"error": "partido_id es obligatorio"}

    detalle = detalle_json if isinstance(detalle_json, str) else json.dumps(detalle_json or {}, ensure_ascii=False)
    confianza_txt = "ALTA" if confianza_pct >= 65 else "MEDIA" if confianza_pct >= 45 else "BAJA"
    razonamiento = f"Fuente: {fuente} | Pick: {pick} | Confianza: {confianza_pct}%"
    ahora = _now_str()

    db.add(Prediccion(
        partido_id=partido_id, fuente=f"{fuente}_predictions", pick=pick, confianza=confianza_txt,
        confianza_score=int(confianza_pct), razonamiento=razonamiento, texto_completo=detalle,
        creado_en=ahora,
    ))

    comparativo = db.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == partido_id).first()
    if comparativo is not None:
        comparativo.pick_externo = pick
        comparativo.pick_externo_score = confianza_pct
        comparativo.fuente_externo = fuente
        comparativo.pick_externo_detalle = detalle

    db.commit()
    return {"guardado": True, "partido_id": partido_id, "pick": pick, "confianza": confianza_txt, "fuente": fuente}


def leer_stats_modulos(db: Session, fecha: str = "", fecha_fin: str = "", dias: int = 0) -> dict:
    """Winrate desglosado por módulo (poisson/forma/h2h/odds/tabla/claude/externo) + niveles
    de consenso + mercados (over 2.5/BTTS). Mismo cálculo que el original, ahora en Python en
    vez de SQL crudo con CASE WHEN (SQLAlchemy no cambia el resultado, solo cómo se arma)."""
    if dias > 0:
        fecha = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        fecha_fin = datetime.now().strftime("%Y-%m-%d")
    elif not fecha:
        fecha = fecha_fin = datetime.now().strftime("%Y-%m-%d")
    elif not fecha_fin:
        fecha_fin = fecha

    filas = (
        db.query(AnalisisComparativo)
        .filter(
            AnalisisComparativo.fecha >= fecha, AnalisisComparativo.fecha <= fecha_fin,
            AnalisisComparativo.resultado_real.isnot(None), AnalisisComparativo.resultado_real != "CANC",
        )
        .all()
    )

    def _wr(ok: int, tot: int) -> float | None:
        return round(ok / tot * 100, 1) if tot > 0 else None

    def _modulo(campo_correcto: str) -> dict:
        vals = [getattr(f, campo_correcto) for f in filas if getattr(f, campo_correcto) is not None]
        ok = sum(1 for v in vals if v == 1)
        return {"ok": ok, "total": len(vals), "winrate": _wr(ok, len(vals))}

    ok_final = sum(1 for f in filas if f.pick_correcto == 1)
    total = len(filas)

    consenso = {}
    for nivel_clave, nivel_valor in (("fuerte", "FUERTE"), ("moderado", "MODERADO"), ("debil", "DEBIL")):
        del_nivel = [f for f in filas if f.consenso_nivel == nivel_valor]
        ok_nivel = sum(1 for f in del_nivel if f.pick_correcto == 1)
        consenso[nivel_clave] = {"ok": ok_nivel, "total": len(del_nivel), "winrate": _wr(ok_nivel, len(del_nivel))}

    def _mercado(campo: str) -> dict:
        vals = [getattr(f, campo) for f in filas if getattr(f, campo) is not None]
        ok = sum(1 for v in vals if v == 1)
        return {"total": len(vals), "winrate": _wr(ok, len(vals))}

    return {
        "periodo": {"desde": fecha, "hasta": fecha_fin, "total_partidos": total},
        "final": {"ok": ok_final, "total": total, "winrate": _wr(ok_final, total)},
        "poisson": _modulo("pick_python_correcto"),
        "forma": _modulo("pick_form_correcto"),
        "h2h": _modulo("pick_h2h_correcto"),
        "odds": _modulo("pick_odds_correcto"),
        "tabla": _modulo("pick_tabla_correcto"),
        "claude": _modulo("pick_claude_correcto"),
        "externo": _modulo("pick_externo_correcto"),
        "consenso": consenso,
        "mercados": {"over25": _mercado("over25_correcto"), "btts": _mercado("btts_correcto")},
    }
