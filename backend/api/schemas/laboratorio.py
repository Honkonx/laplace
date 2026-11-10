"""Contratos de ingreso de comparadores al laboratorio interno."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PronosticoExperimentalInput(BaseModel):
    experimento_codigo: str = Field(min_length=2, max_length=96)
    partido_id: str = Field(min_length=1, max_length=255)
    fecha_partido: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    local: str = Field(min_length=1, max_length=255)
    visitante: str = Field(min_length=1, max_length=255)
    fuente: str = Field(min_length=2, max_length=96)
    variante: str = Field(min_length=2, max_length=96)
    corte_datos_en: str = Field(min_length=10, max_length=64)
    hora_kickoff: str | None = Field(default=None, max_length=64)
    liga: str | None = Field(default=None, max_length=255)
    modelo_version: str | None = Field(default=None, max_length=255)
    prompt_version: str | None = Field(default=None, max_length=96)
    datos: dict = Field(default_factory=dict)
    respuesta_cruda: str | None = Field(default=None, max_length=20000)
    pick: str | None = Field(default=None, max_length=255)
    prob_local: float | None = Field(default=None, ge=0, le=1)
    prob_empate: float | None = Field(default=None, ge=0, le=1)
    prob_visitante: float | None = Field(default=None, ge=0, le=1)
    marcador_probable: str | None = Field(default=None, max_length=32)
    goles_local_esperados: float | None = Field(default=None, ge=0, le=10)
    goles_visitante_esperados: float | None = Field(default=None, ge=0, le=10)
    rango_goles_total: str | None = Field(default=None, max_length=32)
    prob_empate_90: float | None = Field(default=None, ge=0, le=1)

    @field_validator("prob_visitante")
    @classmethod
    def probabilidades_completas(cls, value: float | None, info):
        values = info.data
        trio = (values.get("prob_local"), values.get("prob_empate"), value)
        if any(item is not None for item in trio) and any(item is None for item in trio):
            raise ValueError("prob_local, prob_empate y prob_visitante deben enviarse juntas")
        return value


class PronosticoHumanoAdminInput(BaseModel):
    partido_id: str = Field(min_length=1, max_length=255)
    fecha_partido: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    local: str = Field(min_length=1, max_length=255)
    visitante: str = Field(min_length=1, max_length=255)
    pick: str = Field(pattern=r"^(local|empate|visitante)$")
    alias: str = Field(min_length=1, max_length=48)
    liga: str | None = Field(default=None, max_length=255)
    hora_kickoff: str | None = Field(default=None, max_length=64)
    razon: str | None = Field(default=None, max_length=2000)
    marcador_probable: str | None = Field(default=None, max_length=32)
