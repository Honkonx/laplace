package com.laplace.mobile.data.remote.dto

// Contrato real de `POST /api/v1/prediccion-web` (JWT, sin IA): el resultado del motor con el
// consenso ponderado. Solo se declaran los campos que la app muestra; Gson ignora el resto.
// Las probabilidades son fracciones 0-1 (backend/api/services/consenso.py::prob_ponderada).

data class PrediccionWebRequest(
    val match_id: String,
    val local: String,
    val visitante: String,
    val liga: String,
    val fecha: String,
)

data class ProbabilidadesDto(
    val local: Double = 0.0,
    val empate: Double = 0.0,
    val visitante: Double = 0.0,
)

data class ConsensoDto(
    val pick_final: String? = null,
    val confianza_final: String? = null,
    val detalle: String? = null,
    val total_modulos: Int = 0,
    val coinciden: Int = 0,
    val prob_ponderada: ProbabilidadesDto? = null,
    val peso_efectivo: Map<String, Double>? = null,
    val modulos_en_consenso: List<String>? = null,
    val modulos_disidentes: List<String>? = null,
)

/** Solo lo común a todos los módulos que la app necesita: `historico` trae el aviso de modelo viejo. */
data class ModuloMotorDto(
    val ok: Boolean? = null,
    val modelo_desactualizado: Boolean? = null,
    val edad_modelo_dias: Double? = null,
)

data class TasaBaseLigaDto(
    /** "liga" o "general" (promedio de todas las ligas cuando la liga no está cubierta). */
    val nivel: String? = null,
    val pct_local: Double? = null,
    val pct_empate: Double? = null,
    val pct_visitante: Double? = null,
    val partidos: Int? = null,
)

data class CalidadDatosDto(
    val eligible: Boolean? = null,
    val reason: String? = null,
)

data class PrediccionWebDto(
    val partido_id: String? = null,
    val local: String? = null,
    val visitante: String? = null,
    val liga: String? = null,
    val modulos: Map<String, ModuloMotorDto?>? = null,
    val consenso: ConsensoDto? = null,
    val odds_info: String? = null,
    val tasa_base_liga: TasaBaseLigaDto? = null,
    /** Con "Sin pronóstico": por qué no hay estimación propia y la frecuencia histórica como referencia. */
    val motivos_sin_pronostico: List<String>? = null,
    val referencia_tasa_base: TasaBaseLigaDto? = null,
    val calidad_datos: CalidadDatosDto? = null,
)
