"""models/ml_modelo.py — tablas del modelo propio de Laplace (prefijo `ml_`): datos, simulaciones, entrenamientos, modelos, predicciones y evaluaciones.

Plan: `ANALISIS_PLAN_GPT_Y_AJUSTES_AL_MODELO_PROPIO_2026-11-10.md` (docs/archive/planes), sección 5. Reglas de diseño:
- El modelo **pronostica**; no guarda nada sobre publicar (esa política es del agente).
- Toda muestra lleva `procedencia` (`real`, `sintetico`, `mixto`): una simulación nunca se confunde con un partido real.
- Los pesos NO se guardan aquí: solo ruta, SHA-256 y metadatos del artefacto.
- Fechas como texto ISO escritas desde Python (nunca `DEFAULT datetime('now')`); relaciones lógicas, sin claves foráneas (`auditar_integridad.py`).
"""
from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base

PROCEDENCIAS = ("real", "sintetico", "mixto")
ESTADOS_MODELO = ("sombra", "activo", "retirado")


class MlConjuntoDatos(Base):
    __tablename__ = "ml_conjuntos_datos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    hash_datos: Mapped[str | None] = mapped_column(String(64), nullable=True)
    procedencia: Mapped[str] = mapped_column(String(12), nullable=False)
    desde: Mapped[str | None] = mapped_column(String(10), nullable=True)
    hasta: Mapped[str | None] = mapped_column(String(10), nullable=True)
    filas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ruta: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class MlSimulacion(Base):
    __tablename__ = "ml_simulaciones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conjunto_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    grupo: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    semilla: Mapped[int] = mapped_column(Integer, nullable=False)
    parametros_json: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[str] = mapped_column(String(12), nullable=False)  # manual | automatico
    version_generador: Mapped[str] = mapped_column(String(40), nullable=False)
    generada_en: Mapped[str] = mapped_column(String(32), nullable=False)


class MlMuestra(Base):
    __tablename__ = "ml_muestras"
    __table_args__ = (Index("ix_ml_muestras_conjunto_fecha", "conjunto_id", "fecha_evento"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conjunto_id: Mapped[int] = mapped_column(Integer, nullable=False)
    simulacion_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    partido_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    procedencia: Mapped[str] = mapped_column(String(12), nullable=False)
    peso: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    fecha_evento: Mapped[str | None] = mapped_column(String(10), nullable=True)
    caracteristicas_json: Mapped[str] = mapped_column(Text, nullable=False)
    etiqueta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hash_muestra: Mapped[str] = mapped_column(String(64), nullable=False)
    creada_en: Mapped[str] = mapped_column(String(32), nullable=False)


class MlEntrenamiento(Base):
    __tablename__ = "ml_entrenamientos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conjunto_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    familia: Mapped[str] = mapped_column(String(40), nullable=False)
    semilla: Mapped[int] = mapped_column(Integer, nullable=False)
    parametros_json: Mapped[str] = mapped_column(Text, nullable=False)
    commit_codigo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    estado: Mapped[str] = mapped_column(String(12), nullable=False, index=True)  # pendiente | corriendo | ok | fallo
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    inicio: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fin: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MlModelo(Base):
    __tablename__ = "ml_modelos"
    __table_args__ = (Index("ux_ml_modelos_nombre_version", "nombre", "version", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(60), nullable=False)
    familia: Mapped[str] = mapped_column(String(40), nullable=False)
    tarea: Mapped[str] = mapped_column(String(40), nullable=False)  # 1x2, goles, btts, ...
    artefacto_ruta: Mapped[str | None] = mapped_column(Text, nullable=True)
    artefacto_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estado: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    metricas_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    entrenamiento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promovido_por: Mapped[str | None] = mapped_column(String(80), nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class MlPrediccion(Base):
    __tablename__ = "ml_predicciones"
    __table_args__ = (Index("ix_ml_predicciones_modelo_fecha", "modelo_id", "creada_en"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modelo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    partido_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entrada_json: Mapped[str] = mapped_column(Text, nullable=False)
    probabilidades_json: Mapped[str] = mapped_column(Text, nullable=False)
    goles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    latencia_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    canal: Mapped[str] = mapped_column(String(12), nullable=False)  # agente | http | cli | laboratorio
    creada_en: Mapped[str] = mapped_column(String(32), nullable=False)
    hash_previo: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sello encadenado (ml/laplace/auditoria.py, MP-5); NULL en las filas anteriores a la cadena
    hash_fila: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MlEvaluacion(Base):
    __tablename__ = "ml_evaluaciones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modelo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ventana_desde: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ventana_hasta: Mapped[str | None] = mapped_column(String(10), nullable=True)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    rps: Mapped[float | None] = mapped_column(Float, nullable=True)
    ece: Mapped[float | None] = mapped_column(Float, nullable=True)
    cobertura: Mapped[float | None] = mapped_column(Float, nullable=True)
    referencias_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # tasa base, mercado, apilador
    origen: Mapped[str] = mapped_column(String(12), nullable=False)  # historica | sombra | vivo
    creada_en: Mapped[str] = mapped_column(String(32), nullable=False)


class MlError(Base):
    """Memoria de errores (MP-1): por partido ya jugado, qué pronosticó el modelo y cuánto se equivocó. La llena `ml/laplace/auditoria.cerrar_bucle`."""

    __tablename__ = "ml_errores"
    __table_args__ = (UniqueConstraint("modelo_id", "partido_id", name="uq_ml_errores_modelo_partido"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modelo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    partido_id: Mapped[str] = mapped_column(String(64), nullable=False)
    liga: Mapped[str] = mapped_column(String(120), nullable=False)
    fecha: Mapped[str] = mapped_column(String(10), nullable=False)
    p_local: Mapped[float] = mapped_column(Float, nullable=False)
    p_empate: Mapped[float] = mapped_column(Float, nullable=False)
    p_visitante: Mapped[float] = mapped_column(Float, nullable=False)
    resultado: Mapped[str] = mapped_column(String(1), nullable=False)  # H | D | A
    rps: Mapped[float] = mapped_column(Float, nullable=False)
    log_loss: Mapped[float] = mapped_column(Float, nullable=False)
    tramo: Mapped[str] = mapped_column(String(8), nullable=False)  # tramo de probabilidad del favorito
    acierto: Mapped[int] = mapped_column(Integer, nullable=False)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class MlEstadoVivo(Base):
    """Memoria del modelo: el estado por equipo (Elo, tasas de gol, forma) de una liga, al día. Lo reconstruye `ml/laplace/estado_vivo.py`; los pesos NO se guardan aquí (siguen en el artefacto)."""

    __tablename__ = "ml_estado_vivo"
    __table_args__ = (UniqueConstraint("modelo_id", "liga", name="uq_ml_estado_vivo_modelo_liga"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modelo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    liga: Mapped[str] = mapped_column(String(40), nullable=False)
    estado_json: Mapped[str] = mapped_column(Text, nullable=False)
    hasta_dia: Mapped[int] = mapped_column(Integer, nullable=False)  # ordinal del último partido aplicado
    partidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[str] = mapped_column(String(32), nullable=False)
