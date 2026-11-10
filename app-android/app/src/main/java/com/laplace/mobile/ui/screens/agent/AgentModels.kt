package com.laplace.mobile.ui.screens.agent

import org.json.JSONObject
import retrofit2.HttpException
import java.io.IOException

enum class RolMensaje { USUARIO, AGENTE }

enum class EstadoValoracion { SIN_VALORAR, ENVIANDO, UTIL, NO_UTIL, ERROR }

/** Un mensaje del hilo. `herramienta`, `modo` y `runId` solo existen en respuestas del agente de esta sesión. */
data class MensajeChat(
    val id: Long,
    val rol: RolMensaje,
    val contenido: String,
    val creadoEn: Long,
    val modo: String? = null,
    val herramienta: String? = null,
    val runId: String? = null,
    val valoracion: EstadoValoracion = EstadoValoracion.SIN_VALORAR,
)

enum class TipoError { LIMITE_DIARIO, LIMITE_MINUTO, PERMISO, SESION, RED, SERVIDOR, OTRO }

/** Error ya traducido a algo que diga qué pasó y qué hacer. `esperaSeg` solo aplica a límites. */
data class ErrorAmigable(
    val tipo: TipoError,
    val titulo: String,
    val detalle: String,
    val esperaSeg: Int? = null,
    val reintentable: Boolean = true,
)

private val REGEX_LIMITE_DIARIO = Regex("hoy|diari", RegexOption.IGNORE_CASE)

private fun detalleDelServidor(e: HttpException): String? = try {
    e.response()?.errorBody()?.string()?.let { JSONObject(it).optString("detail").takeIf { d -> d.isNotBlank() } }
} catch (_: Exception) {
    null
}

fun describirError(e: Throwable): ErrorAmigable = when {
    e is HttpException && e.code() == 429 -> {
        val detalle = detalleDelServidor(e).orEmpty()
        val diario = REGEX_LIMITE_DIARIO.containsMatchIn(detalle)
        val espera = e.response()?.headers()?.get("Retry-After")?.toIntOrNull()
        if (diario) {
            ErrorAmigable(
                TipoError.LIMITE_DIARIO,
                "Llegaste al límite de hoy",
                "El cupo diario de IA se agotó. Puedes seguir con respuestas por reglas, sin IA, o volver mañana.",
                esperaSeg = null,
                reintentable = false,
            )
        } else {
            ErrorAmigable(
                TipoError.LIMITE_MINUTO,
                "Demasiadas consultas seguidas",
                "El límite de IA por minuto se alcanzó. Espera un momento o sigue sin IA.",
                esperaSeg = espera ?: 60,
            )
        }
    }
    e is HttpException && e.code() == 401 ->
        ErrorAmigable(TipoError.SESION, "Tu sesión venció", "Vuelve a iniciar sesión para seguir hablando con Laplace.", reintentable = false)
    e is HttpException && e.code() == 403 ->
        ErrorAmigable(TipoError.PERMISO, "No tienes permiso para esto", detalleDelServidor(e) ?: "Tu cuenta no puede usar esta función.", reintentable = false)
    e is HttpException && e.code() >= 500 ->
        ErrorAmigable(TipoError.SERVIDOR, "El servidor tuvo un problema", "Prueba de nuevo en unos segundos.")
    e is HttpException ->
        ErrorAmigable(TipoError.OTRO, "No se pudo completar", detalleDelServidor(e) ?: "El servidor rechazó la consulta (${e.code()}).")
    e is IOException ->
        ErrorAmigable(TipoError.RED, "Sin conexión con Laplace", "Revisa tu conexión o que el servicio esté encendido, y reintenta.")
    else ->
        ErrorAmigable(TipoError.OTRO, "Algo salió mal", e.message ?: "Error desconocido.")
}

val ERROR_SIN_SESION = ErrorAmigable(
    TipoError.SESION,
    "Necesitas una cuenta",
    "Inicia sesión o regístrate para usar el agente.",
    reintentable = false,
)

/** Cómo se produjo una respuesta: lo que el usuario debe saber para confiar (o no) en ella. */
data class FuenteRespuesta(val esIa: Boolean, val etiqueta: String, val detalle: String? = null)

/** Traduce el `modo` que emite el backend ("reglas", "ia · proveedor/modelo", "reglas_fallback"…) a una etiqueta honesta. */
fun fuenteDeModo(modo: String?): FuenteRespuesta? = when {
    modo.isNullOrBlank() || modo == "entrada" -> null
    modo == "politica" -> FuenteRespuesta(false, "Política de uso")
    modo == "reglas_fallback" -> FuenteRespuesta(false, "Respuesta por reglas", "La IA no estaba disponible; respondió el motor de reglas.")
    modo.startsWith("ia_experimental") -> FuenteRespuesta(true, "Respuesta con IA (experimental)", modo.substringAfter("·", "").trim().ifBlank { null })
    modo.startsWith("ia") -> FuenteRespuesta(true, "Respuesta con IA", modo.substringAfter("·", "").trim().ifBlank { null })
    modo.contains("ia_descartada") -> FuenteRespuesta(false, "Respuesta por reglas", "La redacción con IA se descartó por citar cifras ajenas al motor.")
    else -> FuenteRespuesta(false, "Respuesta por reglas")
}

private val HERRAMIENTAS = mapOf(
    "sports.predict" to "Análisis de partido",
    "sports.get_odds" to "Cuotas del partido",
    "sports.list_fixtures" to "Partidos",
    "sports.list_playing_leagues" to "Ligas con actividad",
    "sports.list_leagues" to "Ligas",
    "sports.list_top_picks" to "Top Picks publicados",
    "sports.get_match" to "Datos del partido",
    "sports.results" to "Verificar resultados",
    "sports.top_picks" to "Generar Top Picks",
    "sports.publish" to "Publicar en Telegram",
    "agent.ai_prediction" to "Hipótesis solo IA",
    "agent.prediction_choice" to "Elegir vía de análisis",
    "agent.policy_block" to "Política de uso",
    "sports.match_not_found" to "Búsqueda de partido",
    "sports.match_required" to "Búsqueda de partido",
    "llm.respond" to "Respuesta de IA",
    "knowledge.team_profile" to "Perfil de equipo",
    "knowledge.league_profile" to "Perfil de liga",
    "knowledge.glossary" to "Glosario",
)

fun etiquetaHerramienta(nombre: String): String = HERRAMIENTAS[nombre] ?: nombre

/** Respuestas rápidas cuando el agente hace una pregunta cerrada (misma convención que la web). */
fun respuestasRapidas(herramienta: String?): List<Pair<String, String>> =
    if (herramienta == "agent.prediction_choice") listOf("bot" to "Análisis del bot", "IA" to "Hipótesis con IA") else emptyList()

val SUGERENCIAS = listOf(
    "¿Qué partidos hay hoy?",
    "Predice River vs Boca",
    "Explícame qué es la confianza media",
)
