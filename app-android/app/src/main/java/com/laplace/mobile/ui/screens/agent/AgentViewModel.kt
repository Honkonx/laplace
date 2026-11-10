package com.laplace.mobile.ui.screens.agent

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.laplace.mobile.data.local.AuthManager
import com.laplace.mobile.data.remote.AgentMemoryItem
import com.laplace.mobile.data.remote.AgentSubagentItem
import com.laplace.mobile.data.remote.AgentTaskItem
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.dto.CapacidadesAgenteDto
import com.laplace.mobile.data.remote.dto.HerramientaAgenteDto
import com.laplace.mobile.data.remote.dto.UsoAgenteDto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Error del último envío más lo necesario para reintentarlo; `esperaRestante` baja cada segundo en límites por minuto. */
data class ErrorDeEnvio(
    val error: ErrorAmigable,
    val textoOriginal: String,
    val esperaRestante: Int? = null,
)

/** Datos de la hoja de opciones. `null` = el backend no los dio (404/sin red): la UI no inventa cifras. */
data class OpcionesAgente(
    val capacidades: CapacidadesAgenteDto? = null,
    val uso: UsoAgenteDto? = null,
    val memoria: List<AgentMemoryItem>? = null,
    val tareas: List<AgentTaskItem>? = null,
    val subagentes: List<AgentSubagentItem>? = null,
    val cargando: Boolean = false,
) {
    val esAdmin: Boolean get() = capacidades?.rol == "admin" || AuthManager.rol == "admin"

    /** Herramientas que ve ESTE usuario: nunca las de administrador salvo que lo sea. */
    val herramientasVisibles: List<HerramientaAgenteDto>
        get() = capacidades?.herramientas.orEmpty().filter { esAdmin || !it.admin_only }

    private val modoIa get() = capacidades?.modos?.firstOrNull { it.id == "ia" }

    /** `true` / `false` si el backend lo informó; `null` si no se pudo saber (se deja decidir al servidor). */
    val iaDisponible: Boolean?
        get() {
            val servidor = modoIa?.disponible
            val activa = uso?.ia_activa
            val cupoDia = uso?.por_dia?.let { it.limite > 0 && it.restantes <= 0 }
            return when {
                servidor == false || activa == false || cupoDia == true -> false
                servidor == null && activa == null && cupoDia == null -> null
                else -> true
            }
        }
}

data class AgentUiState(
    val mensajes: List<MensajeChat> = emptyList(),
    val enviando: Boolean = false,
    val errorEnvio: ErrorDeEnvio? = null,
    val usarIa: Boolean = false,
    val opciones: OpcionesAgente = OpcionesAgente(),
    val copiadoId: Long? = null,
) {
    val mensajeMaxCaracteres: Int
        get() = opciones.capacidades?.limites?.mensaje_max_caracteres?.takeIf { it > 0 } ?: 12000
}

class AgentViewModel : ViewModel() {
    private val _ui = MutableStateFlow(AgentUiState())
    val ui: StateFlow<AgentUiState> = _ui.asStateFlow()

    private var sesionId: String? = null
    private var siguienteId = 1L
    private var cuentaAtras: Job? = null

    init {
        cargarOpciones()
    }

    fun cargarOpciones() {
        if (!AuthManager.hasAccount) return
        _ui.update { it.copy(opciones = it.opciones.copy(cargando = true)) }
        viewModelScope.launch {
            // Cada consulta degrada sola: un 404 de capabilities/usage no debe tumbar memoria ni tareas.
            val capacidades = intentar { LaplaceApi.agentCapabilities() }
            val uso = intentar { LaplaceApi.agentUsage() }
            val memoria = intentar { LaplaceApi.listAgentMemory()?.memory }
            val tareas = intentar { LaplaceApi.listAgentTasks()?.tasks }
            val subagentes = intentar { LaplaceApi.listAgentSubagents()?.subagents }
            _ui.update {
                val opciones = OpcionesAgente(capacidades, uso, memoria, tareas, subagentes, cargando = false)
                // Si la IA dejó de estar disponible mientras estaba activada, vuelve a reglas sin sorpresas.
                it.copy(opciones = opciones, usarIa = it.usarIa && opciones.iaDisponible != false)
            }
        }
    }

    private suspend fun <T> intentar(bloque: suspend () -> T?): T? = try {
        bloque()
    } catch (cancelado: CancellationException) {
        throw cancelado
    } catch (_: Exception) {
        null
    }

    fun cambiarModo(usarIa: Boolean) {
        _ui.update { it.copy(usarIa = usarIa && it.opciones.iaDisponible != false) }
    }

    fun enviar(texto: String) {
        val limpio = texto.trim()
        if (limpio.isEmpty() || _ui.value.enviando) return
        agregar(RolMensaje.USUARIO, limpio)
        despachar(limpio)
    }

    fun reintentar() {
        val pendiente = _ui.value.errorEnvio ?: return
        if (_ui.value.enviando || (pendiente.esperaRestante ?: 0) > 0) return
        despachar(pendiente.textoOriginal)
    }

    /** Tras un límite de IA: apaga la IA y reenvía la misma pregunta al motor de reglas. */
    fun seguirSinIa() {
        val pendiente = _ui.value.errorEnvio ?: return
        _ui.update { it.copy(usarIa = false) }
        despachar(pendiente.textoOriginal)
    }

    private fun despachar(texto: String) {
        cuentaAtras?.cancel()
        _ui.update { it.copy(enviando = true, errorEnvio = null) }
        viewModelScope.launch {
            try {
                val respuesta = LaplaceApi.chatWithAgent(texto, sesionId, _ui.value.usarIa)
                if (respuesta == null) {
                    _ui.update { it.copy(enviando = false, errorEnvio = ErrorDeEnvio(ERROR_SIN_SESION, texto)) }
                    return@launch
                }
                sesionId = respuesta.session_id
                agregar(
                    RolMensaje.AGENTE,
                    respuesta.respuesta,
                    modo = respuesta.modo,
                    herramienta = respuesta.herramienta,
                    runId = respuesta.run_id,
                )
                _ui.update { it.copy(enviando = false) }
                refrescarUso()
            } catch (cancelado: CancellationException) {
                throw cancelado
            } catch (e: Exception) {
                val error = describirError(e)
                _ui.update { it.copy(enviando = false, errorEnvio = ErrorDeEnvio(error, texto, error.esperaSeg)) }
                error.esperaSeg?.let(::iniciarCuentaAtras)
                if (error.tipo == TipoError.LIMITE_DIARIO || error.tipo == TipoError.LIMITE_MINUTO) refrescarUso()
            }
        }
    }

    private fun iniciarCuentaAtras(segundos: Int) {
        cuentaAtras?.cancel()
        cuentaAtras = viewModelScope.launch {
            var restante = segundos
            while (restante > 0) {
                delay(1000)
                restante--
                _ui.update { estado -> estado.copy(errorEnvio = estado.errorEnvio?.copy(esperaRestante = restante)) }
            }
        }
    }

    private fun refrescarUso() {
        viewModelScope.launch {
            val uso = intentar { LaplaceApi.agentUsage() } ?: return@launch
            _ui.update {
                val opciones = it.opciones.copy(uso = uso)
                it.copy(opciones = opciones, usarIa = it.usarIa && opciones.iaDisponible != false)
            }
        }
    }

    fun valorar(mensajeId: Long, util: Boolean) {
        val mensaje = _ui.value.mensajes.firstOrNull { it.id == mensajeId } ?: return
        val runId = mensaje.runId ?: return
        if (mensaje.valoracion == EstadoValoracion.ENVIANDO || mensaje.valoracion == EstadoValoracion.UTIL || mensaje.valoracion == EstadoValoracion.NO_UTIL) return
        actualizarMensaje(mensajeId) { it.copy(valoracion = EstadoValoracion.ENVIANDO) }
        viewModelScope.launch {
            val guardada = try {
                LaplaceApi.sendAgentFeedback(runId, rating = if (util) 5 else 1, label = if (util) "util" else "no_util")?.saved == true
            } catch (cancelado: CancellationException) {
                throw cancelado
            } catch (_: Exception) {
                false
            }
            val resultado = when {
                !guardada -> EstadoValoracion.ERROR
                util -> EstadoValoracion.UTIL
                else -> EstadoValoracion.NO_UTIL
            }
            actualizarMensaje(mensajeId) { it.copy(valoracion = resultado) }
        }
    }

    fun marcarCopiado(mensajeId: Long) {
        _ui.update { it.copy(copiadoId = mensajeId) }
        viewModelScope.launch {
            delay(1800)
            _ui.update { if (it.copiadoId == mensajeId) it.copy(copiadoId = null) else it }
        }
    }

    fun nuevaConversacion() {
        cuentaAtras?.cancel()
        sesionId = null
        _ui.update { it.copy(mensajes = emptyList(), enviando = false, errorEnvio = null, copiadoId = null) }
    }

    private fun agregar(rol: RolMensaje, contenido: String, modo: String? = null, herramienta: String? = null, runId: String? = null) {
        val mensaje = MensajeChat(siguienteId++, rol, contenido, System.currentTimeMillis(), modo, herramienta, runId)
        _ui.update { it.copy(mensajes = it.mensajes + mensaje) }
    }

    private fun actualizarMensaje(id: Long, cambio: (MensajeChat) -> MensajeChat) {
        _ui.update { estado -> estado.copy(mensajes = estado.mensajes.map { if (it.id == id) cambio(it) else it }) }
    }
}
