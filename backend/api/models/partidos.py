"""models/partidos.py — partidos_dia, resultados_partidos, recomendaciones_dia,
fixture_id_cache, stats_cache."""
from __future__ import annotations

from sqlalchemy import Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class PartidoDia(Base):
    """Caché lazy de fixtures del día — PK compuesta (fecha, match_id). Poblada por el
    reemplazo de WF-D y consultada por el reemplazo de WF-A2 acción 'juegos'."""

    __tablename__ = "partidos_dia"
    __table_args__ = (PrimaryKeyConstraint("fecha", "match_id"),)

    fecha: Mapped[str] = mapped_column(String)
    match_id: Mapped[str] = mapped_column(String)
    liga_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga_nombre: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga_codigo: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga_logo: Mapped[str | None] = mapped_column(Text, nullable=True)
    local: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    hora_chile: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_local: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_visitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="scheduled")
    goles_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goles_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    kick_off_utc: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_invalidado: Mapped[int] = mapped_column(Integer, default=0)
    apifootball_fixture_id: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResultadoPartido(Base):
    __tablename__ = "resultados_partidos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fixture_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    local: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga: Mapped[str | None] = mapped_column(Text, nullable=True)
    goles_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goles_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ganador: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_api: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_partido: Mapped[str | None] = mapped_column(Text, nullable=True)
    hora_kickoff: Mapped[str | None] = mapped_column(Text, nullable=True)
    actualizado_en: Mapped[str] = mapped_column(Text, nullable=False)


class RecomendacionDia(Base):
    __tablename__ = "recomendaciones_dia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fixture_id: Mapped[str] = mapped_column(String, nullable=False)
    local: Mapped[str] = mapped_column(Text, nullable=False)
    visitante: Mapped[str] = mapped_column(Text, nullable=False)
    liga: Mapped[str] = mapped_column(Text, nullable=False)
    hora_chile: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha: Mapped[str] = mapped_column(String, nullable=False)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class FixtureIdCache(Base):
    """Caché de mapeo match_id (LiveScore6) -> apifootball_fixture_id — TTL 24h."""

    __tablename__ = "fixture_id_cache"

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    fecha: Mapped[str] = mapped_column(String, nullable=False)
    apifootball_fixture_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    league_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_home_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_away_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class StatsCache(Base):
    """Caché genérico con TTL diferenciado por tipo (team_stats 48h, h2h 168h,
    standings 24h, predictions 12h, odds 2h — ver db/cache.py::TTL_HORAS_POR_TIPO).

    `veces_confirmado`/`ultima_confirmacion_en` (2026-09-09): triangulación orgánica de datos
    entre requests reales de usuarios distintos a lo largo del tiempo — NO son 3 llamadas HTTP
    seguidas en el primer fetch (eso triplicaría el costo de API, ver `db/cache.py::
    guardar_stats_cache`). Cada vez que un fetch REAL (cache miss/expirado, nunca un hit)
    devuelve el mismo valor ya cacheado, el contador sube; si el valor cambió, se resetea a 1.
    Un dato con `veces_confirmado >= 3` es de "alta confianza" — uso de auditoría, no cambia
    el TTL ya calibrado por tipo."""

    __tablename__ = "stats_cache"

    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    datos_json: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    expira_en: Mapped[str] = mapped_column(Text, nullable=False)
    veces_confirmado: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ultima_confirmacion_en: Mapped[str | None] = mapped_column(Text, nullable=True)
