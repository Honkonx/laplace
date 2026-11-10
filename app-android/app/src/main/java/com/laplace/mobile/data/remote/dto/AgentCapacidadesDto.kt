package com.laplace.mobile.data.remote.dto

// Contrato real de `GET /api/v1/agent/capabilities` y `GET /api/v1/agent/usage`
// (backend/api/schemas/agent_capacidades.py). Todo con default: Gson usa el constructor sin
// argumentos que genera Kotlin, así un campo ausente nunca deja un null donde se espera un valor.

data class ModoAgenteDto(
    val id: String = "",
    val disponible: Boolean = false,
    val descripcion: String = "",
    val proveedores_configurados: Int? = null,
)

data class HerramientaAgenteDto(
    val name: String = "",
    val description: String = "",
    val category: String = "",
    val read_only: Boolean = true,
    val requires_confirmation: Boolean = false,
    val admin_only: Boolean = false,
)

data class LimitesAgenteDto(
    val ia_por_minuto: Int = 0,
    val ia_por_dia: Int = 0,
    val tareas_activas_max: Int = 0,
    val mensaje_max_caracteres: Int = 12000,
)

data class ConocimientoAgenteDto(
    val version: String = "",
    val archivos: Int = 0,
    val equipos_con_perfil: Int = 0,
    val ligas_cubiertas: Int = 0,
    val copas_con_tasas: Int = 0,
    val datos_hasta: String? = null,
    val conocimiento_actualizado: String? = null,
)

data class CapacidadesAgenteDto(
    val rol: String = "usuario",
    val modos: List<ModoAgenteDto> = emptyList(),
    val herramientas: List<HerramientaAgenteDto> = emptyList(),
    val limites: LimitesAgenteDto = LimitesAgenteDto(),
    val conocimiento: ConocimientoAgenteDto = ConocimientoAgenteDto(),
)

data class CupoVentanaDto(
    val limite: Int = 0,
    val usadas: Int = 0,
    val restantes: Int = 0,
    val reinicia_en_segundos: Int? = null,
)

data class UsoAgenteDto(
    val fecha: String = "",
    val rol: String = "usuario",
    val ia_activa: Boolean = true,
    val por_minuto: CupoVentanaDto = CupoVentanaDto(),
    val por_dia: CupoVentanaDto = CupoVentanaDto(),
    val tareas_activas: Int = 0,
    val tareas_activas_max: Int = 0,
)

/** Cuerpo de `POST /api/v1/agent/feedback` (`FeedbackInput`: rating 1-5). */
data class AgentFeedbackRequest(
    val run_id: String?,
    val rating: Int,
    val label: String? = null,
    val comment: String? = null,
)

data class AgentFeedbackResponse(val id: Int? = null, val saved: Boolean = false)
