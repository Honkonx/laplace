"""
models/predicciones.py — predicciones, cache_predicciones, analisis_comparativo,
analisis_individuales, cache_consenso, analisis_modulos.

`analisis_comparativo` es la tabla más rica del schema (picks/scores por módulo, resultado
real, pick_correcto) — columnas idénticas a las de db_query.py:init_db()
(base + ~35 columnas agregadas por migraciones ALTER TABLE a lo largo de v3-v9).
"""
from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class Prediccion(Base):
    __tablename__ = "predicciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partido_id: Mapped[str] = mapped_column(String, nullable=False)
    fuente: Mapped[str] = mapped_column(String, nullable=False)
    pick: Mapped[str | None] = mapped_column(Text, nullable=True)
    confianza: Mapped[str | None] = mapped_column(Text, nullable=True)
    confianza_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    razonamiento: Mapped[str | None] = mapped_column(Text, nullable=True)
    texto_completo: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    pick_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CachePrediccion(Base):
    """Caché de respuesta completa por hash de input — TTL fijo (horas_ttl, default 6h)."""

    __tablename__ = "cache_predicciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    respuesta_json: Mapped[str] = mapped_column(Text, nullable=False)
    partido_id: Mapped[str] = mapped_column(String, nullable=False)
    expira_en: Mapped[str] = mapped_column(Text, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


# Corte de calidad del motor (2026-09-29, auditoría de la BD real): 78 de los 95 análisis
# guardados hasta el 2026-09-26 eran "Empate", y 6 partidos distintos del 24 al 26 de septiembre
# tenían exactamente las mismas probabilidades (0.3594/0.4362/0.2044) — Poisson recibía el
# promedio genérico de la liga en vez de datos de los equipos. Los commits del 2026-09-27
# (`62df919` y `7c154a5`) cerraron ese camino (`motor.py` ya no deja votar a Poisson con
# `fuente_goles == "liga_generico"`, y `analisis_completo.py` exige 2 fuentes reales para
# publicar). Todo lo analizado ANTES de esa fecha se conserva en la BD (nada se borra) pero no
# entra en calibración, Brier, RPS ni winrate: medir un motor con datos de otro motor no es una
# medida del motor actual. Se compara contra `creado_en` (texto ISO, orden lexicográfico = orden
# temporal), así que no hace falta una migración ni escribir nada en la BD.
#
# Corte movido a 2026-10-07 (el 10-06 y antes eran los anteriores): el motor volvió a cambiar después del 27-sep, así que lo medido entre
# esa fecha y hoy tampoco es del motor vigente. Cambios: 2026-09-29 (pesos del consenso por la
# evaluación histórica, módulo `historico`, el pick sale de la probabilidad ponderada), 2026-10-05
# (topes de confianza por módulo único / probabilidad < 48%, niveles SOLO_<modulo>) y 2026-10-06
# (causa raíz del sesgo a Empate: los lambdas de `pronostico.calcular_lambdas` salían a la mitad por
# usar la media de goles TOTALES de la liga con promedios POR EQUIPO; puerta de calidad unificada
# con `historico` y odds+BSD como un solo canal de mercado) y 2026-10-07 (pesos del consenso orientados
# al mercado tras evaluar el consenso real completo: poisson/h2h/bsd_ml en 0, confianza calibrada por
# probabilidad ponderada, módulo odds con margen de Shin, H2H orientado al local actual) y 2026-10-19 (un ancla —cuotas
# reales o histórico con ambos equipos— basta para publicar; histórico con un equipo sin historial; etiquetas por ancla;
# sin pronóstico explicado en vez de un pick vacío). Mover este corte cada vez que un
# cambio altere las salidas del motor (`.claude/rules/evidencia-historica-antes-de-promover.md`).
CORTE_MOTOR_CON_PUERTA_CALIDAD = "2026-10-19"


class AnalisisComparativo(Base):
    __tablename__ = "analisis_comparativo"
    # Índices agregados 2026-09-09 (auditoría real — confirmado leyendo db/analisis_repo.py y
    # db/usuarios_repo.py): partido_id se usa en WHERE/JOIN en guardar_analisis_multimodelo,
    # leer_top_picks_app, verificar_partido_completo, usuarios_repo.leer_racha (join con Job);
    # fecha se usa en WHERE (leer_stats_aciertos: `fecha >= desde`) y en combinación con
    # partido_id (leer_top_picks_app, verificar_partido_completo).

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partido_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    fecha: Mapped[str] = mapped_column(String, nullable=False, index=True)
    local: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_python: Mapped[str | None] = mapped_column(Text, nullable=True)
    prob_local_py: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_empate_py: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_visit_py: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_py: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_claude: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_externo: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    fuentes_disp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consenso: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confianza: Mapped[str | None] = mapped_column(Text, nullable=True)
    peso_python: Mapped[float | None] = mapped_column(Float, nullable=True)
    peso_ia: Mapped[float | None] = mapped_column(Float, nullable=True)
    resultado_real: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    # migraciones v3-v4
    hora_kickoff: Mapped[str | None] = mapped_column(Text, nullable=True)
    goles_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goles_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_partido: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_form: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_python_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_claude_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_form_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # migraciones v5 — motor multi-modelo
    pick_h2h: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_odds: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_tabla: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_poisson: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_forma: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_h2h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_odds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_tabla: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consenso_nivel: Mapped[str | None] = mapped_column(Text, nullable=True)
    coinciden_modulos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_modulos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bloque_claude_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_externo_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuente_externo: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_externo_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_h2h_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_odds_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_tabla_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_externo_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # migraciones v6.2 — mercados Over/Under y BTTS
    over25_pred: Mapped[float | None] = mapped_column(Float, nullable=True)
    over25_real: Mapped[int | None] = mapped_column(Integer, nullable=True)
    over25_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    btts_pred: Mapped[float | None] = mapped_column(Float, nullable=True)
    btts_real: Mapped[int | None] = mapped_column(Integer, nullable=True)
    btts_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AnalisisIndividual(Base):
    """Análisis individuales para el sistema de caché de consenso (v4)."""

    __tablename__ = "analisis_individuales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partido_id: Mapped[str] = mapped_column(String, nullable=False)
    pick_final: Mapped[str] = mapped_column(Text, nullable=False)
    confianza: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    texto_completo: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    fuente: Mapped[str] = mapped_column(String, nullable=False, default="python")


class CacheConsenso(Base):
    """Caché de consenso por partido — TTL + max_usos (lo que primero se cumpla)."""

    __tablename__ = "cache_consenso"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partido_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    pick_consenso: Mapped[str] = mapped_column(Text, nullable=False)
    texto_consenso: Mapped[str] = mapped_column(Text, nullable=False)
    total_analisis: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_usos: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    expira_en: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    tipo_consenso: Mapped[str] = mapped_column(String, nullable=False, default="python")


class ConsensoIaValidacion(Base):
    """Consenso 'N usuarios validan el mismo pick de IA' (2026-09-09) — mecanismo NUEVO,
    distinto de `CacheConsenso` (esa es TTL+max_usos sobre `AnalisisIndividual`, sin
    distinguir si dos análisis vinieron del mismo usuario o de dos distintos).

    Regla: cuando 2 usuarios DISTINTOS piden análisis del mismo partido y la IA da el mismo
    pick, el resultado queda `validado=1` y se sirve desde acá sin volver a llamar al
    proveedor de IA — hasta `expira_en` (TTL 12h, ver `db/consenso_ia_repo.py`). Una fila por
    `partido_id`: mientras no está validada, guarda el candidato más reciente (el primer
    usuario que pidió IA para este partido); si un segundo usuario distinto coincide, se
    valida; si diverge, el candidato se reemplaza (evidencia más reciente, no se acumulan
    picks divergentes — diseño deliberadamente simple sobre una tabla de detalle separada)."""

    __tablename__ = "consenso_ia_validacion"

    partido_id: Mapped[str] = mapped_column(String, primary_key=True)
    pick_ia: Mapped[str] = mapped_column(Text, nullable=False)
    confianza_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_ia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    texto_ia: Mapped[str] = mapped_column(Text, nullable=False)
    primer_usuario_id: Mapped[str] = mapped_column(Text, nullable=False)
    segundo_usuario_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    usuarios_confirmaron: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    validado: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    actualizado_en: Mapped[str] = mapped_column(Text, nullable=False)
    expira_en: Mapped[str] = mapped_column(Text, nullable=False)


class PrediccionUsuario(Base):
    """Voto real de un usuario sobre quién gana un partido (2026-09-10) — primer paso de la
    visión "Laplace-Agents pregunta a los usuarios, tipo encuestas" (ver el registro de decisiones del proyecto
    y el pedido original del usuario). Esta ronda SOLO captura y permite leer el agregado —
    "auto-alimentarse y aprender" de estos votos es una decisión de diseño más grande, fuera de
    esta ronda (no hay ningún consumidor todavía, ni en `laplace-agents/` ni en el motor).

    Un usuario puede cambiar su voto para el mismo partido (upsert por `match_id` +
    `telegram_user_id` — constraint única abajo) en vez de acumular votos duplicados del mismo
    usuario, que inflarían el agregado sin aportar señal nueva."""

    __tablename__ = "predicciones_usuario"
    __table_args__ = (
        UniqueConstraint("match_id", "telegram_user_id", name="uq_prediccion_usuario_match_telegram"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    telegram_user_id: Mapped[str] = mapped_column(String, nullable=False)
    pick: Mapped[str] = mapped_column(String, nullable=False)
    razon: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class HistorialPrediccionWeb(Base):
    """Solicitud web atribuida a su dueño; no reutiliza una fila global de análisis."""
    __tablename__ = "historial_predicciones_web"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    partido_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    fecha: Mapped[str] = mapped_column(String, nullable=False)
    liga: Mapped[str | None] = mapped_column(Text, nullable=True)
    local: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick: Mapped[str | None] = mapped_column(Text, nullable=True)
    confianza: Mapped[str | None] = mapped_column(Text, nullable=True)
    resultado_json: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class PrediccionVarianteAgente(Base):
    """Predicción solicitada desde el agente, separada del consenso estadístico público."""
    __tablename__ = "predicciones_variantes_agente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    partido_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    fecha: Mapped[str] = mapped_column(String, nullable=False)
    liga: Mapped[str | None] = mapped_column(Text, nullable=True)
    local: Mapped[str] = mapped_column(Text, nullable=False)
    visitante: Mapped[str] = mapped_column(Text, nullable=False)
    via: Mapped[str] = mapped_column(String(32), nullable=False)  # ai_scout | bot
    pick: Mapped[str | None] = mapped_column(Text, nullable=True)
    marcador_probable: Mapped[str | None] = mapped_column(Text, nullable=True)
    confianza: Mapped[str | None] = mapped_column(Text, nullable=True)
    proveedor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    modelo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    respuesta_cruda: Mapped[str] = mapped_column(Text, nullable=False)
    resultado_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    resultado_real: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class AnalisisModulo(Base):
    """Una fila por módulo (poisson/forma/h2h/odds/tabla/externo) por partido — v5.

    Permite trackear winrate de cada módulo independientemente (futuro laplace_auditor.py).
    """

    __tablename__ = "analisis_modulos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partido_id: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    modulo: Mapped[str] = mapped_column(String, nullable=False)
    pick: Mapped[str | None] = mapped_column(Text, nullable=True)
    prob_local: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_empate: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_visitante: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confianza: Mapped[str | None] = mapped_column(Text, nullable=True)
    datos_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class ExperimentoPronostico(Base):
    """Catálogo versionado de variantes evaluadas en sombra.

    Ninguna fila de este catálogo autoriza a influir el consenso público. La promoción de una
    variante es una decisión administrativa posterior a evidencia reproducible.
    """

    __tablename__ = "experimentos_pronostico"
    __table_args__ = (UniqueConstraint("codigo", name="uq_experimento_pronostico_codigo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[str] = mapped_column(String(32), nullable=False)  # propio | ia | api | web_referencia
    estado: Mapped[str] = mapped_column(String(32), nullable=False, default="sombra")
    version: Mapped[str] = mapped_column(String(96), nullable=False)
    permite_consenso: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    actualizado_en: Mapped[str] = mapped_column(Text, nullable=False)


class PronosticoExperimental(Base):
    """Observación inmutable de una predicción prepartido para evaluación comparativa.

    Guarda la hora de corte y las versiones de datos/modelo/prompt para impedir que un resultado
    posterior se presente como pronóstico histórico. Las fuentes externas se registran aquí como
    referencias y no se leen desde el consenso del bot.
    """

    __tablename__ = "pronosticos_experimentales"
    __table_args__ = (
        UniqueConstraint("partido_id", "variante", "corte_datos_en", name="uq_pronostico_experimental_corte"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experimento_codigo: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    partido_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    fecha_partido: Mapped[str] = mapped_column(String, nullable=False, index=True)
    hora_kickoff: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    local: Mapped[str] = mapped_column(Text, nullable=False)
    visitante: Mapped[str] = mapped_column(Text, nullable=False)
    fuente: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    variante: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    modelo_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(96), nullable=True)
    corte_datos_en: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    input_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    datos_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    respuesta_cruda: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick: Mapped[str | None] = mapped_column(Text, nullable=True)
    prob_local: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_empate: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_visitante: Mapped[float | None] = mapped_column(Float, nullable=True)
    marcador_probable: Mapped[str | None] = mapped_column(Text, nullable=True)
    goles_local_esperados: Mapped[float | None] = mapped_column(Float, nullable=True)
    goles_visitante_esperados: Mapped[float | None] = mapped_column(Float, nullable=True)
    rango_goles_total: Mapped[str | None] = mapped_column(Text, nullable=True)
    prob_empate_90: Mapped[float | None] = mapped_column(Float, nullable=True)
    resultado_real: Mapped[str | None] = mapped_column(Text, nullable=True)
    goles_local_real: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goles_visitante_real: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_correcto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    rps: Mapped[float | None] = mapped_column(Float, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
