"""Esquemas de `GET /api/v1/agent/capabilities` y `GET /api/v1/agent/usage`.

Contrato para que web, PWA, app y Telegram sepan qué ofrece el agente a ESTE usuario sin probar a ciegas.
Nunca incluyen credenciales: de los proveedores de IA solo se informa si hay alguno configurado (y su
nombre, únicamente para el administrador).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ModoAgente(BaseModel):
    id: str = Field(description="reglas | ia")
    disponible: bool
    descripcion: str
    proveedores_configurados: int | None = Field(default=None, description="Solo para el modo ia")
    proveedores: list[str] = Field(default_factory=list, description="Nombres de proveedor; solo se llenan para administradores")


class HerramientaAgente(BaseModel):
    name: str
    description: str
    category: str = Field(description="conocimiento | deportiva")
    read_only: bool
    requires_confirmation: bool
    admin_only: bool


class LimitesAgente(BaseModel):
    ia_por_minuto: int
    ia_por_dia: int
    tareas_activas_max: int
    mensaje_max_caracteres: int
    timeout_tarea_max_segundos: int
    aprobacion_vigencia_segundos: int


class ConocimientoAgente(BaseModel):
    version: str
    archivos: int
    equipos_con_perfil: int
    ligas_cubiertas: int
    copas_con_tasas: int
    datos_hasta: str | None = None
    conocimiento_actualizado: str | None = None


class CapacidadesAgente(BaseModel):
    rol: str = Field(description="usuario | admin")
    modos: list[ModoAgente]
    herramientas: list[HerramientaAgente]
    limites: LimitesAgente
    conocimiento: ConocimientoAgente


class CupoVentana(BaseModel):
    limite: int
    usadas: int
    restantes: int
    reinicia_en_segundos: int | None = None


class UsoAgente(BaseModel):
    fecha: str
    rol: str
    ia_activa: bool = Field(description="False si el administrador desactivó la IA del agente")
    por_minuto: CupoVentana
    por_dia: CupoVentana
    tareas_activas: int
    tareas_activas_max: int
