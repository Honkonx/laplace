"""routers/admin.py — Dashboard de administración global.

v1 (`PROPUESTA_DASHBOARD_ADMIN.md` §2) fue solo-lectura (`GET`) por decisión
ya tomada — permitía verificar el dashboard en uso real antes de exponer escritura. v1.1
(2026-09-10) agrega los dos únicos cambios de escritura que la propuesta original ya preveía
como siguiente paso natural: cambiar `rol` (permiso) y `plan` (tier) de un usuario existente —
ambos ya tenían su función de repo real con tests (`usuarios_repo.asignar_rol`,
`admin_repo.gestionar_usuario`), esta ronda solo agrega el borde HTTP. Sigue sin existir
generación de códigos ni cualquier otra acción — eso queda para una ronda futura si se necesita.

Todos los endpoints exigen `Depends(requerir_admin)` (JWT de sesión válido + `Usuario.rol ==
"admin"`, separado de `plan` desde 2026-09-10, ver `core/auth_deps.py` y
`models/usuarios.py` §v7) — nunca `x-kairos-key` (ese header autentica al gateway de la app, no
a una persona con rol).

Contrato de paginación uniforme en los cuatro endpoints de listado (`usuarios`, `historial-plan`,
`intentos-login`, `jobs`): query params `limit` (1-200, default 50) y `offset` (>=0, default 0),
respuesta `{"total": int, "limit": int, "offset": int, "<clave>": [...]}` — el frontend que
consume esto (construido en paralelo) puede asumir esta forma en los cuatro.

Contrato de error uniforme en los dos endpoints `PATCH`: ambos envuelven una función de repo que
devuelve `{"error": "..."}` en vez de lanzar — tanto un valor inválido (`rol`/`plan` fuera de lo
permitido) como un `device_id` inexistente devuelven el mismo `{"error": ...}`, sin un campo que
distinga el motivo. Se mapean ambos a 400 acá (no 404 para el caso "no encontrado") para no
inventar una distinción que el repo no expone — separarlos requeriría parsear el texto del
mensaje de error, más frágil que un código uniforme. Justifica además la letra del pedido
original de esta ronda ("Devuelve 400 si `asignar_rol` devuelve `{"error": ...}` (rol inválido o
usuario no encontrado)").
"""
from __future__ import annotations

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.core.auth_deps import requerir_admin
from backend.api.core.config import settings
from backend.api.db import admin_repo, auditoria_repo, codigos_repo, jobs_repo, usuarios_repo
from backend.api.db.analisis_repo import leer_stats_aciertos
from backend.api.db.session import get_db
from backend.api.models.metricas import EstadoFuenteDeportiva
from backend.api.models.partidos import PartidoDia
from backend.api.services.calibracion import calcular_metricas_calibracion
from backend.api.services.laboratorio_pronosticos import reporte_laboratorio
from backend.api.services.laboratorio_pronosticos import registrar_pronostico, registrar_referencia_humana
from backend.api.schemas.laboratorio import PronosticoExperimentalInput, PronosticoHumanoAdminInput
from backend.api.services.source_health import verificar_fuentes
from backend.api.core import conexiones as cx
from backend.api.services import admin_env
from backend.api.services.admin_env import guardar_proveedor_env, proveedores_permitidos
from backend.api.services.ai_client import OLLAMA_CLOUD_FREE_MODELS

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(requerir_admin)])


class RolInput(BaseModel):
    rol: str


class PlanInput(BaseModel):
    plan: str


class ProveedorIaInput(BaseModel):
    provider: str
    api_key: str = Field(min_length=8, max_length=4096)
    model: str = Field(min_length=1, max_length=180)


class ConexionClaveInput(BaseModel):
    clave: str = Field(min_length=8, max_length=512)
    probar_antes: bool = True
    confirmar_coste: bool = False


class OrdenIaInput(BaseModel):
    orden: list[str] = Field(min_length=1, max_length=10)


@router.get("/usuarios")
def listar_usuarios_admin(
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """`q` busca por coincidencia parcial en `username` o `device_id`."""
    return usuarios_repo.listar_usuarios(db, q=q, limit=limit, offset=offset)


@router.get("/codigos")
def listar_codigos_admin(filtro: str = "todos", db: Session = Depends(get_db)) -> dict:
    """`filtro`: `disponibles` | `usados` | `todos` (default) — envuelve
    `codigos_repo.listar_codigos`, sin paginar (mismo comportamiento que esa función)."""
    return codigos_repo.listar_codigos(db, filtro=filtro)


@router.get("/historial-plan")
def listar_historial_plan_admin(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Primer lector real de `HistorialPlan` — hasta ahora se escribía (`activar_codigo`,
    `gestionar_usuario`) pero nada la leía."""
    return auditoria_repo.listar_historial_plan(db, limit=limit, offset=offset)


@router.get("/intentos-login")
def listar_intentos_login_admin(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Primer lector real de `IntentoLoginFallido` — útil para detectar patrones de fuerza
    bruta contra un username. Nunca incluye la contraseña intentada (ver
    `.claude/rules/secrets-never-revealed.md` — el modelo ni siquiera la guarda)."""
    return auditoria_repo.listar_intentos_login_fallidos(db, limit=limit, offset=offset)


@router.get("/jobs")
def listar_jobs_admin(
    status: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """`status` filtra opcionalmente por `pendiente`/`procesando`/`listo`/`error`; vacío = todos."""
    return jobs_repo.listar_jobs(db, status=status, limit=limit, offset=offset)


@router.get("/stats")
def stats_admin(dias: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict:
    """Winrate real (no marketing, ver `.claude/rules/product-philosophy.md`) desde
    `AnalisisComparativo`/`Prediccion` — reusa `analisis_repo.leer_stats_aciertos`, la misma
    agregación que ya existe, sin reescribirla."""
    return leer_stats_aciertos(db, dias=dias)


@router.get("/calibracion")
def calibracion_admin(db: Session = Depends(get_db)) -> dict:
    """Winrate real por módulo (poisson/forma/h2h/odds/tabla/externo) + winrate del pick final
    + Brier score de calibración del módulo Poisson, leídos de `AnalisisComparativo`/
    `AnalisisModulo` reales — mismo cálculo que corre `backend/scripts/laplace_auditor.py`
    (`services/calibracion.py`, sin duplicar lógica). Cada bloque trae su propio `confiable`
    (bool) y `muestra_minima_requerida` — el número real siempre se devuelve, aunque la muestra
    sea insuficiente para que sea estadísticamente válido (ver
    `.claude/rules/product-philosophy.md`); el frontend decide cómo mostrar esa distinción, acá
    solo se expone la data honesta."""
    return calcular_metricas_calibracion(db)


@router.get("/laboratorio-pronosticos")
def laboratorio_pronosticos_admin(db: Session = Depends(get_db)) -> dict:
    """Comparación interna por variante, fuente y liga.

    Es administrativo y de solo lectura: las fuentes externas permanecen en sombra hasta una
    revisión explícita, aunque su métrica inicial parezca buena.
    """
    return reporte_laboratorio(db)


@router.post("/laboratorio-pronosticos", status_code=201)
def registrar_comparador_laboratorio(payload: PronosticoExperimentalInput, db: Session = Depends(get_db)) -> dict:
    """Ingresa una referencia autorizada al laboratorio, nunca al consenso del bot.

    Los adaptadores de APIs o sitios permitidos llaman este contrato desde el backend. El
    navegador no recibe ni administra proveedores, prompts o respuestas crudas.
    """
    try:
        fila = registrar_pronostico(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {"id": fila.id, "estado": "sombra", "partido_id": fila.partido_id, "variante": fila.variante}


@router.get("/laboratorio-pronosticos/partidos")
def partidos_para_referencia_humana(fecha: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), db: Session = Depends(get_db)) -> dict:
    """Lista fixtures del bot ya disponibles para el formulario de referencias humanas."""
    filas = db.query(PartidoDia).filter(PartidoDia.fecha == fecha).order_by(PartidoDia.kick_off_utc.asc()).all()
    return {"fecha": fecha, "partidos": [
        {"partido_id": f.match_id, "liga": f.liga_nombre, "local": f.local, "visitante": f.visitante,
         "hora_kickoff": f.kick_off_utc, "estado": f.status}
        for f in filas
    ]}


@router.post("/laboratorio-pronosticos/predicciones-humanas", status_code=201)
def registrar_referencia_humana_admin(
    payload: PronosticoHumanoAdminInput, admin: dict = Depends(requerir_admin), db: Session = Depends(get_db),
) -> dict:
    """Entrada exclusiva del administrador para pronósticos de amigos o analistas externos."""
    try:
        fila = registrar_referencia_humana(db, actor_id=str(admin.get("sub")), **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {"id": fila.id, "estado": "sombra", "partido_id": fila.partido_id, "fuente": fila.fuente}


def _valor_configurado(c: cx.Conexion) -> str:
    """Valor actual de la clave en el proceso (la de cuotas conserva su alias legado); solo para saber si está puesta, nunca se devuelve."""
    return settings.the_odds_api_key if c.id == "the-odds-api" else str(getattr(settings, c.variable, "") or "")


def _conexion_o_404(conexion_id: str) -> cx.Conexion:
    c = cx.por_id(conexion_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Conexión desconocida")
    return c


def _orden_ia_actual() -> list[str]:
    conocidos = [c.ia for c in cx.proveedores_ia()]
    texto = settings.AI_ROUTING_BOT or "ollama_cloud,groq,gemini,openrouter,claude"
    orden = [p for p in (x.strip() for x in texto.split(",")) if p in conocidos]
    return orden + [p for p in conocidos if p not in orden]


@router.get("/conexiones")
def listar_conexiones_admin() -> dict:
    """Las 13 conexiones externas (datos, IA y Telegram) con su estado de configuración. Nunca devuelve claves."""
    definidas = {c.id for c in cx.CONEXIONES if cx.valor_definido(_valor_configurado(c))}
    return {
        "grupos": [{"id": g.id, "titulo": g.titulo, "nota": g.nota} for g in cx.GRUPOS],
        "conexiones": [
            {"id": c.id, "numero": c.numero, "grupo": c.grupo, "nombre": c.nombre, "variable": c.variable, "sirve": c.sirve, "plan": c.plan, "enlace": c.enlace,
             "host": c.host, "configurada": c.id in definidas, "destacada": c.destacada, "cobra_por_llamada": c.prueba.cobra_por_llamada, "cuesta": c.prueba.cuesta}
            for c in cx.CONEXIONES
        ],
        "faltantes": cx.faltantes_para_pronosticar(definidas),
        "orden_ia": _orden_ia_actual(),
        "nota": "Las claves se guardan en .env, se prueban antes de guardarse y no vuelven a mostrarse. Para aplicar un cambio hay que reiniciar el backend y el agente.",
    }


@router.post("/conexiones/{conexion_id}/probar")
def probar_conexion_admin(conexion_id: str, confirmar_coste: bool = False) -> dict:
    """Prueba la clave guardada contra el host oficial. Las pruebas con coste (LiveScore6, Ollama) solo corren si se confirma."""
    c = _conexion_o_404(conexion_id)
    valor = _valor_configurado(c)
    if not cx.valor_definido(valor):
        raise HTTPException(status_code=400, detail="Esta conexión no tiene clave guardada")
    coste = "1 llamada de tu cuota" if c.prueba.cobra_por_llamada else c.prueba.cuesta
    if coste and not confirmar_coste:
        return {"id": c.id, "estado": cx.ESTADO_AVISO, "detalle": f"La prueba cuesta {coste}: confirma para hacerla", "requiere_confirmacion": True, "coste": coste}
    r = cx.probar(c, valor)
    return {"id": c.id, "estado": r.estado, "detalle": r.detalle, "http": r.http, "requiere_confirmacion": False}


@router.post("/conexiones/{conexion_id}")
def guardar_conexion_admin(conexion_id: str, payload: ConexionClaveInput, admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    """Guarda (o cambia) la clave de una conexión. Por defecto la prueba ANTES de guardar: si el proveedor la rechaza, no se escribe nada y la anterior sigue."""
    c = _conexion_o_404(conexion_id)
    clave = payload.clave.strip()
    motivo = cx.formato_invalido(clave)
    if motivo:
        raise HTTPException(status_code=422, detail=f"{motivo}. No se guardó nada.")
    resultado = None
    puede_probar = payload.probar_antes and not ((c.prueba.cobra_por_llamada or c.prueba.cuesta) and not payload.confirmar_coste)
    if puede_probar:
        resultado = cx.probar(c, clave)
        if resultado.estado == cx.ESTADO_FALLA:
            raise HTTPException(status_code=422, detail=f"{resultado.detalle}. No se guardó nada; la clave anterior sigue como estaba.")
    try:
        info = admin_env.guardar_clave_conexion(settings.repo_root, c.id, clave)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    setattr(settings, c.variable, clave)  # este proceso la usa ya; el agente (otro proceso) y el bot de Telegram necesitan reinicio
    auditoria_repo.registrar_accion_admin(db, str(admin.get("sub")), "conexion_configurada", c.id)  # sin el valor
    return {**info, "estado": resultado.estado if resultado else None, "detalle": resultado.detalle if resultado else "guardada sin probar",
            "message": "Guardada en .env. Reinicia el agente y el bot (laplace reiniciar) para que la usen."}


@router.delete("/conexiones/{conexion_id}")
def borrar_conexion_admin(conexion_id: str, admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    c = _conexion_o_404(conexion_id)
    info = admin_env.borrar_clave_conexion(settings.repo_root, c.id)
    setattr(settings, c.variable, "")
    auditoria_repo.registrar_accion_admin(db, str(admin.get("sub")), "conexion_borrada", c.id)
    return {**info, "message": "Clave borrada de .env. Reinicia para que deje de usarse."}


@router.put("/conexiones-orden-ia")
def guardar_orden_ia_admin(payload: OrdenIaInput, admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    try:
        info = admin_env.guardar_orden_ia(settings.repo_root, payload.orden)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for rol in cx.ROLES_IA:
        setattr(settings, rol, ",".join(payload.orden))
    auditoria_repo.registrar_accion_admin(db, str(admin.get("sub")), "orden_ia_cambiado", ",".join(payload.orden))
    return {**info, "message": "Orden guardado. Reinicia el backend y el agente para aplicarlo."}


@router.get("/ia/proveedores")
def proveedores_ia_admin() -> dict:
    """Estado seguro de proveedores: nunca devuelve claves ni secretos."""
    proveedores = []
    for ia in ("groq", "gemini", "openrouter", "ollama_cloud", "claude"):
        c = next(x for x in cx.proveedores_ia() if x.ia == ia)
        fila = {"id": ia, "configurado": bool(getattr(settings, c.variable)), "modelo": getattr(settings, c.modelo_variable)}
        if ia == "ollama_cloud":
            fila.update({"modelos_sugeridos": list(OLLAMA_CLOUD_FREE_MODELS), "cloud_only": True})
        proveedores.append(fila)
    return {
        "agent_ia_activa": settings.AGENT_IA_ACTIVA,
        "proveedores": proveedores,
        "configuracion": "Las claves se administran mediante este panel autenticado o el gestor de secretos del VPS. Nunca se devuelven ni se guardan en la base de datos.",
    }


@router.post("/ia/proveedores")
def configurar_proveedor_ia(payload: ProveedorIaInput, admin: dict = Depends(requerir_admin)) -> dict:
    """Escribe una clave en `.env` sin conservarla ni exponerla en logs o respuestas."""
    try:
        result = guardar_proveedor_env(settings.repo_root, payload.provider, payload.api_key, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "allowed_providers": proveedores_permitidos(), "message": "Configuración guardada. Reinicia agente y bot para aplicarla."}


@router.get("/sports/fuentes")
def fuentes_deportivas_admin(db: Session = Depends(get_db)) -> dict:
    """Inventario seguro de fuentes deportivas.

    Este endpoint comunica configuración, función y última evidencia conocida sin publicar
    claves. Un proveedor configurado no se presenta como sano hasta que el monitor registre
    una prueba válida.
    """
    filas = {fila.fuente: fila for fila in db.query(EstadoFuenteDeportiva).all()}

    def fuente(id_fuente: str, configurada: bool, rol: str) -> dict:
        estado = filas.get(id_fuente)
        return {
            "id": id_fuente,
            "configured": configurada,
            "role": rol,
            "healthy": bool(estado.saludable) if estado else None,
            "status_http": estado.status_http if estado else None,
            "latency_ms": estado.latencia_ms if estado else None,
            "quota_remaining": estado.cuota_restante if estado else None,
            "detail": estado.detalle if estado else None,
            "last_verified": estado.verificado_en if estado else None,
        }

    return {
        "sources": [
            fuente(c.id, cx.valor_definido(_valor_configurado(c)), c.rol_panel)
            for c in (cx.por_id(i) for i in ("livescore6", "api-football", "football-data", "the-odds-api", "bsd", "oddspapi"))
        ],
        "note": "Configurado significa que existe una credencial. La validación operativa requiere una respuesta reciente para un partido con cobertura.",
    }


@router.post("/sports/fuentes/verificar")
async def verificar_fuentes_deportivas_admin(db: Session = Depends(get_db)) -> dict:
    """Prueba manual explícita; incluye la consulta que consume cuota de The Odds API."""
    async with httpx.AsyncClient() as client:
        return {"sources": await verificar_fuentes(db, client, incluir_cuota_costosa=True)}


@router.patch("/usuarios/{device_id}/rol")
def cambiar_rol_admin(
    device_id: str, body: RolInput, admin: dict = Depends(requerir_admin), db: Session = Depends(get_db),
) -> dict:
    """Cambia `Usuario.rol` (usuario|admin|agente) — v1.1, primer punto de escritura real del
    dashboard (ver docstring del módulo). Envuelve `usuarios_repo.asignar_rol`, la misma función
    que ya usa `/gestionarusuario rol:<rol>` en Telegram (`bot/laplace_bot.py`), con
    `actor_admin_id` sacado del JWT ya validado por `requerir_admin` (claim `sub` = `device_id`
    del admin autenticado, ver `routers/auth.py::_emitir_token`) — la auditoría
    (`registrar_accion_admin`) queda con quién hizo el cambio, no un valor vacío."""
    resultado = usuarios_repo.asignar_rol(db, device_id, body.rol, actor_admin_id=admin.get("sub"))
    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])
    return resultado


@router.patch("/usuarios/{device_id}/plan")
def cambiar_plan_admin(
    device_id: str, body: PlanInput, admin: dict = Depends(requerir_admin), db: Session = Depends(get_db),
) -> dict:
    """Cambia `Usuario.plan` (free|pro|max — nunca `admin`, ese pseudo-valor ya no existe desde
    que `rol` se separó de `plan`, ver `admin_repo.PLANES_VALIDOS`). Envuelve
    `admin_repo.gestionar_usuario(db, "cambiar_plan", ...)`, misma función que ya usa
    `/gestionarusuario plan:<plan>` en Telegram, con `actor_admin_id` del JWT ya validado (ver
    `cambiar_rol_admin` arriba)."""
    resultado = admin_repo.gestionar_usuario(db, "cambiar_plan", device_id, body.plan, actor_admin_id=admin.get("sub"))
    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])
    return resultado
