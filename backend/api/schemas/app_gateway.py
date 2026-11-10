"""schemas/app_gateway.py — Contrato de entrada del gateway unificado de la app
(`POST /api/v1/deportivo`, ver `routers/app_gateway.py`).

Antes de esta ronda el endpoint recibía `await request.json()` crudo y despachaba por un string
`action` con un `params: dict` sin tipar (`params.get(...)` disperso, sin tipos ni longitudes
verificadas — un `params.get("partidos", [])` que no fuera lista de dicts, o un `limit` no
numérico, terminaban en un 500 sin control). `DeportivoRequest` valida el sobre exterior (mismo
contrato externo que WF-A2: `{action, params, device_id, timestamp}`) y cada `*Params` valida
los `params` reales de UNA `action` específica — mismos campos y misma tolerancia (`extra`,
`str(...).strip()`, fallback de claves) que el dispatcher viejo ya aplicaba a mano, ahora
declarados explícitos. Ver `routers/app_gateway.py::deportivo` para cómo un `action` desconocida
o un `params` que no valida contra su schema específico corta con un 4xx claro (nunca un 500 ni
un fallo silencioso).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.api.services.fechas_bd import FechaBdInvalida, normalizar_fecha_bd


def _str_o_vacio(v: object) -> str:
    """Mismo `str(...).strip()` que el dispatcher viejo aplicaba a mano a cada `params.get(...)`
    — tolera ids que la app mande como número (ej. `match_id` de api-football)."""
    return "" if v is None else str(v).strip()


def _fecha_calendario_o_vacia(v: str) -> str:
    """Vacío se tolera (el handler usa hoy por defecto); cualquier otra cosa debe ser un día real
    YYYY-MM-DD (o YYYYMMDD) — si no, 422 claro en vez de guardar una clave basura en `partidos_dia`
    (hallazgo 2026-10-06: 631 filas `2026--0-9-`). El valor se devuelve tal cual lo mandó el cliente
    (los handlers ya saben convertir ambos formatos)."""
    if not v:
        return v
    try:
        normalizar_fecha_bd(v)
    except FechaBdInvalida as exc:
        raise ValueError(str(exc)) from exc
    return v


class DeportivoRequest(BaseModel):
    """Sobre exterior — `extra=\"allow\"` tolera `timestamp` y cualquier campo de más que la app
    ya manda pero que el dispatcher nunca leyó (misma tolerancia que antes)."""

    model_config = ConfigDict(extra="allow")

    action: str = ""
    params: dict = Field(default_factory=dict)
    device_id: str = "unknown"

    @field_validator("action", "device_id", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return str(v)

    @field_validator("params", mode="before")
    @classmethod
    def _params_dict(cls, v: object) -> object:
        # mismo `body.get("params") or {}` del dispatcher viejo: cualquier valor "falsy"
        # (None, {}, "", [], 0, False) se normaliza a {} antes de validar el tipo dict —
        # un `params` verdaderamente inválido (ej. una lista con contenido, un string) sigue
        # rechazado por la validación de tipo de abajo, en vez de reventar un `.get()` más
        # adelante con un 500.
        return v or {}


class SinParams(BaseModel):
    """`params` de una acción que no lee ningún campo (`top`, `stats`, `profile`, `ping`) —
    declarada igual que las demás para que TODA acción real tenga un schema explícito, aunque
    esté vacío. Tolera params de más sin fallar (la acción los ignora igual que antes)."""

    model_config = ConfigDict(extra="allow")


class JuegosParams(BaseModel):
    """`params` de action=\"juegos\" — listado de partidos del día (o de una liga puntual)."""

    model_config = ConfigDict(extra="allow")

    date: str = Field(default="", max_length=32)
    league: str = Field(default="", max_length=100)

    @field_validator("date", "league", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)

    @field_validator("date")
    @classmethod
    def _fecha_valida(cls, v: str) -> str:
        return _fecha_calendario_o_vacia(v)


class PrediccionParams(BaseModel):
    """`params` de action=\"prediccion\" — dispara (o consulta el estado de) un análisis
    completo de un partido. `match_id` es el único campo realmente requerido — mismo único
    chequeo duro que hacía `_accion_prediccion` antes."""

    model_config = ConfigDict(extra="allow")

    match_id: str = Field(min_length=1, max_length=64)
    date: str = Field(default="", max_length=32)
    force_new: bool = False
    local: str = Field(default="", max_length=200)
    visitante: str = Field(default="", max_length=200)
    league: str = Field(default="", max_length=100)
    liga: str = Field(default="", max_length=100)

    @field_validator("match_id", "date", "local", "visitante", "league", "liga", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)

    @field_validator("date")
    @classmethod
    def _fecha_valida(cls, v: str) -> str:
        return _fecha_calendario_o_vacia(v)

    @model_validator(mode="before")
    @classmethod
    def _fallback_liga(cls, data: object) -> object:
        # Mismo `params.get("league", params.get("liga", ""))` del dispatcher viejo: si la app
        # manda "liga" en vez de "league", se usa igual — pero solo cuando "league" está
        # AUSENTE (no cuando viene vacío a propósito), igual que el `.get(key, default)`
        # original (no es un `or`).
        if isinstance(data, dict) and "league" not in data:
            data = {**data, "league": data.get("liga", "")}
        return data


class CheckJobParams(BaseModel):
    """`params` de action=\"check_job\" — estado de un job de análisis ya disparado."""

    model_config = ConfigDict(extra="allow")

    job_id: str = Field(min_length=1, max_length=64)

    @field_validator("job_id", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)


class ActivarCodigoParams(BaseModel):
    """`params` de action=\"activar_codigo\" — canje de un código de acceso (formato
    `KS-PLAN-XXXXXXX`, ver `db/codigos_repo.py`)."""

    model_config = ConfigDict(extra="allow")

    codigo: str = Field(min_length=1, max_length=64)

    @field_validator("codigo", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)


class RegistrarUsuarioParams(BaseModel):
    """`params` de action=\"registrar_usuario\" — mismo límite de 3-20 caracteres que ya
    validaba `_accion_registrar_usuario` a mano."""

    model_config = ConfigDict(extra="allow")

    nickname: str = Field(min_length=3, max_length=20)

    @field_validator("nickname", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)


class VerificarPartidoParams(BaseModel):
    """`params` de action=\"verificar_partido\" — `match_id` no era requerido a nivel de
    dispatcher antes (se lo pasaba tal cual, incluso vacío, al repo); se mantiene igual."""

    model_config = ConfigDict(extra="allow")

    match_id: str = Field(default="", max_length=64)
    date: str = Field(default="", max_length=32)
    fecha: str = Field(default="", max_length=32)

    @field_validator("match_id", "date", "fecha", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)

    @field_validator("date", "fecha")
    @classmethod
    def _fecha_valida(cls, v: str) -> str:
        return _fecha_calendario_o_vacia(v)

    @model_validator(mode="before")
    @classmethod
    def _fallback_fecha(cls, data: object) -> object:
        # Mismo `params.get("date", params.get("fecha", ""))` del dispatcher viejo.
        if isinstance(data, dict) and "date" not in data:
            data = {**data, "date": data.get("fecha", "")}
        return data


class HistorialParams(BaseModel):
    """`params` de action=\"historial\". Antes `int(params.get("limit", 50))` sin ningún límite
    — un `limit` no numérico tiraba `ValueError` sin capturar (500). El tope de 500 es el mismo
    valor máximo que ya usa `_accion_profile` internamente para su propio historial."""

    model_config = ConfigDict(extra="allow")

    limit: int = Field(default=50, ge=1, le=500)


class GuardarPartidosParams(BaseModel):
    """`params` de action=\"guardar_partidos\" — antes `params.get("partidos", [])` sin
    verificar que fuera una lista de dicts; `partidos_repo.guardar_partidos_dia` ya declara
    `partidos: list[dict]`, este schema solo hace explícito ese contrato ya existente."""

    model_config = ConfigDict(extra="allow")

    fecha: str = Field(default="", max_length=32)
    partidos: list[dict] = Field(default_factory=list)

    @field_validator("fecha", mode="before")
    @classmethod
    def _coaccionar_str(cls, v: object) -> str:
        return _str_o_vacio(v)

    @field_validator("fecha")
    @classmethod
    def _fecha_valida(cls, v: str) -> str:
        return _fecha_calendario_o_vacia(v)


ACCIONES_CON_PARAMS: dict[str, type[BaseModel]] = {
    "juegos": JuegosParams,
    "prediccion": PrediccionParams,
    "check_job": CheckJobParams,
    "top": SinParams,
    "stats": SinParams,
    "profile": SinParams,
    "activar_codigo": ActivarCodigoParams,
    "registrar_usuario": RegistrarUsuarioParams,
    "verificar_partido": VerificarPartidoParams,
    "historial": HistorialParams,
    "guardar_partidos": GuardarPartidosParams,
    "ping": SinParams,
}
