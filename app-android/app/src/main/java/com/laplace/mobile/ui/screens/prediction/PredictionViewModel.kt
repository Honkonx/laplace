package com.laplace.mobile.ui.screens.prediction

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.laplace.mobile.data.local.AuthManager
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.data.remote.dto.PrediccionWebRequest
import com.laplace.mobile.domain.model.VistaPrediccion
import com.laplace.mobile.domain.model.construirVista
import com.laplace.mobile.navigation.Screen
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Resultado ya resuelto de un análisis (`data.content` de `action=check_job`: dict
 * `{pick, confianza, score, fuente, texto_completo}` de `analisis_completo.procesar_job`). */
data class ContenidoJob(
    val pick: String,
    val confianza: String,
    val analisis: String,
    val fuente: String?,
    val xgLocal: Double?,
    val xgVisit: Double?,
) {
    companion object {
        fun desdeMapa(mapa: Map<*, *>?): ContenidoJob? {
            val pick = mapa?.get("pick") as? String ?: return null
            return ContenidoJob(
                pick = pick,
                confianza = mapa["confianza"] as? String ?: "",
                analisis = mapa["texto_completo"] as? String ?: "",
                fuente = mapa["fuente"] as? String,
                xgLocal = (mapa["xg_local"] as? Number)?.toDouble(),
                xgVisit = (mapa["xg_visit"] as? Number)?.toDouble(),
            )
        }
    }
}

sealed interface Desglose {
    data object Inactivo : Desglose
    data object Cargando : Desglose
    data class Listo(val vista: VistaPrediccion) : Desglose
    /** No se pudo obtener (sin sesión, límite, endpoint caído): la pantalla sigue con lo del job. */
    data object NoDisponible : Desglose
}

enum class EstadoAnalisis { CARGANDO, LISTO, EN_PROCESO, FALLO_ANALISIS, FALLO_RED }

data class PredictionUiState(
    val estado: EstadoAnalisis = EstadoAnalisis.CARGANDO,
    val datos: Map<String, Any?>? = null,
    val desglose: Desglose = Desglose.Inactivo,
)

// Estados REALES del backend (`backend/api/db/jobs_repo.py`): pendiente | procesando | listo | error.
// La versión anterior de la app comparaba contra "processing"/"queued" y nunca esperaba el resultado.
private val ESTADOS_EN_CURSO = setOf("pendiente", "procesando")
private const val MAX_CONSULTAS = 10
private const val ESPERA_ENTRE_CONSULTAS_MS = 2000L

class PredictionViewModel : ViewModel() {
    private val _ui = MutableStateFlow(PredictionUiState())
    val ui: StateFlow<PredictionUiState> = _ui.asStateFlow()

    private var rutaCargada: Screen.Prediction? = null
    private var trabajo: Job? = null

    fun cargar(ruta: Screen.Prediction, forzar: Boolean = false) {
        if (!forzar && rutaCargada == ruta) return
        rutaCargada = ruta
        trabajo?.cancel()
        _ui.value = PredictionUiState()
        trabajo = viewModelScope.launch {
            val datos = try {
                resolverJob(ruta)
            } catch (cancelado: CancellationException) {
                throw cancelado
            } catch (_: Exception) {
                _ui.update { it.copy(estado = EstadoAnalisis.FALLO_RED) }
                return@launch
            }
            val estado = when (datos?.get("status") as? String) {
                "error" -> EstadoAnalisis.FALLO_ANALISIS
                in ESTADOS_EN_CURSO -> EstadoAnalisis.EN_PROCESO
                else -> EstadoAnalisis.LISTO
            }
            val desgloseEmbebido = if (estado == EstadoAnalisis.LISTO) extraerDesgloseDesdeJob(datos) else null
            _ui.update {
                it.copy(
                    estado = estado,
                    datos = datos,
                    desglose = desgloseEmbebido?.let { v -> Desglose.Listo(v) } ?: it.desglose,
                )
            }
            if (estado == EstadoAnalisis.LISTO && desgloseEmbebido == null) cargarDesglose(ruta)
        }
    }

    private fun extraerDesgloseDesdeJob(datos: Map<String, Any?>?): VistaPrediccion? {
        val content = datos?.get("content") as? Map<*, *> ?: return null
        val rawDesglose = content["desglose"] as? Map<*, *> ?: return null
        return try {
            val gson = com.google.gson.Gson()
            val dto = gson.fromJson(
                gson.toJsonTree(rawDesglose),
                com.laplace.mobile.data.remote.dto.PrediccionWebDto::class.java,
            )
            construirVista(dto)
        } catch (_: Exception) {
            null
        }
    }

    private fun marcaDeTiempo() = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())

    private suspend fun resolverJob(ruta: Screen.Prediction): Map<String, Any?>? {
        var respuesta = LaplaceApi.callWebhook(
            action = "prediccion",
            params = mapOf(
                "match_id" to ruta.matchId,
                "date" to ruta.date,
                "local" to ruta.local,
                "visitante" to ruta.visitante,
                "liga" to ruta.liga,
            ),
        )
        var datos = respuesta.data
        val jobId = datos?.get("job_id") as? String
        var consultas = 0
        while (jobId != null && jobId != "cache" && (datos?.get("status") as? String) in ESTADOS_EN_CURSO && consultas < MAX_CONSULTAS) {
            delay(ESPERA_ENTRE_CONSULTAS_MS)
            respuesta = LaplaceApi.callWebhook(
                action = "check_job",
                params = mapOf("job_id" to jobId),
            )
            datos = respuesta.data
            consultas++
        }
        return datos
    }

    private suspend fun cargarDesglose(ruta: Screen.Prediction) {
        if (!AuthManager.hasAccount || ruta.local.isBlank() || ruta.visitante.isBlank()) {
            _ui.update { it.copy(desglose = Desglose.NoDisponible) }
            return
        }
        _ui.update { it.copy(desglose = Desglose.Cargando) }
        val resultado = try {
            LaplaceApi.prediccionWeb(
                PrediccionWebRequest(ruta.matchId, ruta.local, ruta.visitante, ruta.liga, ruta.date.replace("-", "")),
            )
        } catch (cancelado: CancellationException) {
            throw cancelado
        } catch (_: Exception) {
            null
        }
        _ui.update { it.copy(desglose = resultado?.let { dto -> Desglose.Listo(construirVista(dto)) } ?: Desglose.NoDisponible) }
    }
}
