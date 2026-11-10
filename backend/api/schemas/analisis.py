"""
schemas/analisis.py — Contrato de entrada/salida del motor de análisis.

`AnalisisInput` es el mismo contrato que hoy reciben pronostico.py/h2h.py/odds.py/
tabla_pos.py/form_recent.py (mismos nombres de campo, compatibilidad total — así el resto
del sistema que arma este payload, ej. el reemplazo de datos.py, no cambia de formato).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalisisInput(BaseModel):
    model_config = ConfigDict(extra="allow")  # tolera campos de más, igual que los scripts viejos

    local: str = Field(default="", description="Nombre del equipo local, tal como lo devuelve la fuente de fixtures (LiveScore6/BSD/api-football) — no normalizado a un id interno.")
    visitante: str = Field(default="", description="Nombre del equipo visitante, mismo origen/formato que `local`.")
    liga: str = Field(default="", description="Nombre de la liga/competición del partido (ej. 'Premier League'), tal como viene de la fuente de fixtures — no el slug interno de `LIGA_SLUG_POR_ID`.")
    fecha: str = Field(default="", description="Fecha del partido en formato `yyyyMMdd` (mismo formato que usa `/api/v1/partidos` y el resto del pipeline).")
    partido_id: str = Field(default="", description="Identificador único del partido (fixture id de la fuente de datos que lo originó) — usado para deduplicar caché de análisis y para asociar el job de background si aplica.")
    job_id: str = Field(default="", description="Id del job de análisis en background (tabla `jobs`) que generó este request, si vino de un flujo asíncrono (bot/app) — vacío cuando el análisis corre síncrono (ej. `/api/v1/prediccion-web`).")

    # Goles
    goles_local_avg: float | None = Field(default=None, description="Promedio de goles anotados por el equipo local en sus partidos recientes (ventana de forma, no toda la temporada) — insumo directo del módulo Poisson/Dixon-Coles.")
    goles_visit_avg: float | None = Field(default=None, description="Promedio de goles anotados por el equipo visitante en sus partidos recientes, misma ventana que `goles_local_avg`.")
    goles_contra_local_avg: float | None = Field(default=None, description="Promedio de goles recibidos (en contra) por el equipo local en sus partidos recientes — usado para estimar la fuerza defensiva en el modelo Poisson.")
    goles_contra_visit_avg: float | None = Field(default=None, description="Promedio de goles recibidos (en contra) por el equipo visitante en sus partidos recientes.")
    liga_goles_avg: float | None = Field(default=None, description="Promedio de goles por partido de la liga completa en la temporada actual — usado como factor de ajuste (goles esperados de liga) en el modelo Poisson cuando el historial directo de un equipo es corto.")

    # Tabla / forma
    pos_local: int = Field(default=10, description="Posición actual del equipo local en la tabla de posiciones de su liga (1 = primero). Default 10 cuando no hay tabla disponible (liga sin standings o inicio de temporada) — valor neutro, no favorece a ningún equipo.")
    pos_visit: int = Field(default=10, description="Posición actual del equipo visitante en la tabla de posiciones, mismo default neutro que `pos_local` cuando no hay dato real.")
    forma_local_wins: int = Field(default=0, description="Cantidad de victorias del equipo local en sus últimos partidos (ventana de forma reciente, típicamente los últimos 5) — 0 si no hay historial suficiente.")
    forma_visit_wins: int = Field(default=0, description="Cantidad de victorias del equipo visitante en sus últimos partidos, misma ventana que `forma_local_wins`.")

    # H2H
    h2h_local_wins: int = Field(default=0, description="Cantidad de victorias históricas del equipo local frente a este mismo rival (enfrentamientos directos, head-to-head).")
    h2h_visit_wins: int = Field(default=0, description="Cantidad de victorias históricas del equipo visitante frente a este mismo rival.")
    h2h_empates: int = Field(default=0, description="Cantidad de empates históricos entre ambos equipos en sus enfrentamientos directos.")
    h2h_total: int = Field(default=0, description="Cantidad total de enfrentamientos directos históricos considerados (`h2h_local_wins + h2h_visit_wins + h2h_empates`) — usado para ponderar cuánto peso darle al módulo H2H (poco historial = menos confianza).")
    h2h_disponible: bool = Field(default=False, description="True si hubo datos reales de enfrentamientos directos para este partido (la fuente los tenía) — si es False, el módulo H2H se omite del consenso en vez de opinar con datos vacíos.")

    # Odds
    odds_local: float | None = Field(default=None, description="Cuota decimal (formato europeo, ej. 2.10) de que gane el equipo local, según The Odds API — insumo estadístico del módulo de value bet interno, nunca una oferta de apuesta al usuario final.")
    odds_empate: float | None = Field(default=None, description="Cuota decimal de empate, mismo origen que `odds_local`.")
    odds_visit: float | None = Field(default=None, description="Cuota decimal de que gane el equipo visitante, mismo origen que `odds_local`.")
    odds_disponibles: bool = Field(default=False, description="True si hubo cuotas reales disponibles para este partido — si es False, el módulo de odds se omite del consenso en vez de usar valores por defecto.")

    # xG (BSD, opcional)
    xg_local: float | None = Field(default=None, description="Expected Goals (xG) acumulado/promedio del equipo local, fuente BSD API — métrica avanzada opcional, no todas las ligas la tienen disponible.")
    xg_visit: float | None = Field(default=None, description="Expected Goals (xG) del equipo visitante, mismo origen que `xg_local`.")

    guardar_en_db: bool = Field(default=False, description="Si es True, persiste el resultado del análisis en la tabla `predicciones` (histórico auditable) además de devolverlo en la respuesta — False para análisis descartables (ej. simulaciones o pruebas).")


class ModuloResultado(BaseModel):
    """Resultado de un módulo individual (poisson/forma/h2h/odds/tabla) — mismo shape que
    hoy devuelven pronostico.py/h2h.py/odds.py/tabla_pos.py/form_recent.py por stdout."""

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True, description="False si el módulo no pudo calcular un resultado (ej. datos de entrada insuficientes) — en ese caso el resto de los campos numéricos puede no ser confiable y el consenso lo debería excluir.")
    fuente: str = Field(default="poisson", description="Nombre del módulo que generó este resultado (ej. 'poisson', 'forma', 'h2h', 'odds', 'tabla') — identifica de dónde sale el pick para trazabilidad, nunca un score opaco sin origen.")
    pick: str = Field(description="Resultado 1X2 que este módulo predice en solitario: '1' (gana local), 'X' (empate) o '2' (gana visitante).")
    prob_local: float = Field(description="Probabilidad estimada por este módulo de que gane el equipo local, en el rango 0.0-1.0.")
    prob_empate: float = Field(description="Probabilidad estimada por este módulo de empate, en el rango 0.0-1.0.")
    prob_visitante: float = Field(description="Probabilidad estimada por este módulo de que gane el equipo visitante, en el rango 0.0-1.0. `prob_local + prob_empate + prob_visitante` debería sumar ~1.0.")
    confianza_score: int = Field(description="Puntaje de confianza interno del módulo en su propio pick, 0-100 — no es la probabilidad del resultado, es qué tan robusto considera el módulo su propia estimación dada la calidad de los datos de entrada.")
    confianza: str = Field(description="Etiqueta legible de `confianza_score` (ej. 'alta', 'media', 'baja') — usada para mostrar al usuario sin exponer el número crudo.")
    score_para_claude: str = Field(description="Resumen en texto plano de este módulo, pensado como contexto de entrada para el worker de IA (Claude) que redacta la explicación final al usuario — no se muestra tal cual en la UI.")
    penalizaciones: list[str] = Field(default_factory=list, description="Lista de razones (texto corto) por las que este módulo bajó su `confianza_score` — ej. 'poco historial H2H', 'datos de forma incompletos'. Vacía si no hubo penalizaciones.")
    bonificaciones: list[str] = Field(default_factory=list, description="Lista de razones por las que este módulo subió su `confianza_score` — ej. 'racha consistente', 'enfrentamientos directos con patrón claro'. Vacía si no hubo bonificaciones.")


class ConsensoResultado(BaseModel):
    model_config = ConfigDict(extra="allow")

    pick_final: str = Field(description="Resultado 1X2 final del consenso ponderado entre todos los módulos: '1' (gana local), 'X' (empate) o '2' (gana visitante) — el pick que se le muestra al usuario.")
    nivel: str = Field(description="Nivel de acuerdo entre módulos (ej. 'unanime', 'mayoria', 'dividido') — a mayor acuerdo, mayor confianza real en `pick_final`, mostrado explícitamente al usuario en vez de escondido (ver filosofía de producto: honestidad sobre certeza real).")
    coinciden: int = Field(description="Cantidad de módulos cuyo pick individual coincide con `pick_final`.")
    total_modulos: int = Field(description="Cantidad total de módulos que participaron en este consenso (algunos pueden quedar fuera si `ok=False` o si el dato de entrada no estaba disponible — ver `modulos_skip` en `AnalisisCompletoOutput`).")
    detalle: str = Field(description="Explicación en texto plano de cómo se llegó a `pick_final` — qué módulos coincidieron, cuáles disintieron y por qué, para trazabilidad real del número (nunca un score opaco).")
    score_consenso: int = Field(description="Puntaje de confianza del consenso final, 0-100 — combina el acuerdo entre módulos (`coinciden`/`total_modulos`) y la confianza individual de cada uno.")
    confianza_final: str = Field(description="Etiqueta legible de `score_consenso` (ej. 'alta', 'media', 'baja') — es la que se muestra al usuario final junto al pick.")
    votos: dict[str, int] = Field(description="Conteo de votos por resultado posible, ej. `{'1': 3, 'X': 1, '2': 0}` — cuántos módulos votaron por cada uno de '1'/'X'/'2'.")
    prob_ponderada: dict[str, float] = Field(description="Probabilidad final ponderada por resultado tras combinar todos los módulos según `peso_efectivo`, ej. `{'1': 0.52, 'X': 0.28, '2': 0.20}` — suma ~1.0, es la probabilidad real que respalda `pick_final`.")
    modulos_en_consenso: list[str] = Field(description="Nombres de los módulos (`ModuloResultado.fuente`) cuyo pick coincidió con `pick_final`.")
    modulos_disidentes: list[str] = Field(description="Nombres de los módulos cuyo pick individual NO coincidió con `pick_final` — se muestran igual, nunca se ocultan solo porque disienten.")
    peso_efectivo: dict[str, float] = Field(description="Peso relativo (0.0-1.0) que cada módulo tuvo realmente en el cálculo de `prob_ponderada` — puede diferir del peso base configurado si un módulo fue penalizado por baja confianza o datos faltantes.")


class AnalisisCompletoOutput(BaseModel):
    """Salida del endpoint POST /api/v1/analisis — todos los módulos + consenso."""

    partido_id: str = Field(description="Identificador del partido analizado, igual a `AnalisisInput.partido_id`.")
    local: str = Field(description="Nombre del equipo local, igual a `AnalisisInput.local`.")
    visitante: str = Field(description="Nombre del equipo visitante, igual a `AnalisisInput.visitante`.")
    liga: str = Field(description="Nombre de la liga del partido, igual a `AnalisisInput.liga`.")
    modulos: dict[str, ModuloResultado | None] = Field(description="Resultado de cada módulo estadístico ejecutado, indexado por nombre de módulo (ej. 'poisson', 'forma', 'h2h', 'odds', 'tabla'). `None` cuando el módulo estaba habilitado pero no devolvió un resultado válido (distinto de omitido — ver `modulos_skip`).")
    modulos_skip: dict[str, str] = Field(description="Módulos que se omitieron directamente (nunca se ejecutaron) indexados por nombre, con el motivo en texto (ej. 'h2h_disponible=False', 'odds_disponibles=False') — transparencia real sobre qué insumos faltaron para este análisis.")
    consenso: ConsensoResultado = Field(description="Resultado final combinado de todos los módulos disponibles — es el pick y la confianza que se le muestra al usuario.")
