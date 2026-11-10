package com.laplace.mobile.data.remote

import com.laplace.mobile.data.remote.dto.AgentFeedbackRequest
import com.laplace.mobile.data.remote.dto.AgentFeedbackResponse
import com.laplace.mobile.data.remote.dto.CapacidadesAgenteDto
import com.laplace.mobile.data.remote.dto.PrediccionWebDto
import com.laplace.mobile.data.remote.dto.PrediccionWebRequest
import com.laplace.mobile.data.remote.dto.UsoAgenteDto
import okhttp3.Interceptor
import com.laplace.mobile.BuildConfig
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import okhttp3.internal.closeQuietly
import org.json.JSONObject
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

data class WebhookRequest(
    val action: String,
    val params: Map<String, Any?>,
    val device_id: String,
    val timestamp: String,
)

data class WebhookResponse(
    val type: String?,
    val title: String?,
    val data: Map<String, Any?>?,
    val buttons: List<Map<String, Any?>>?,
)

// Contrato real de POST /api/v1/auth/registro (backend FastAPI, JWT — distinto del webhook
// viejo de arriba). `origen` siempre "app" para requests desde acá. 2026-09-08.
// Onboarding bloquea el registro hasta que el usuario acepta los términos. El backend registra
// esa aceptación versionada igual que la web.
data class RegistroRequest(val username: String, val password: String, val origen: String = "app", val terms_accepted: Boolean = true, val terms_version: String = "2026-09-25")
data class LoginRequest(val username: String, val password: String)
// `rol` — 2026-09-10: el backend (`routers/auth.py::registro/login`) ya lo devuelve en el mismo
// JSON desde el 2026-09-10, esta clase simplemente no lo capturaba (Gson ignoraba el campo
// silenciosamente). Default "usuario" para tokens/respuestas viejas sin este campo.
data class AuthResponse(
    val token: String,
    val username: String,
    val plan: String,
    val rol: String = "usuario",
    val device_id: String? = null,
)
data class AgentChatRequest(val message: String, val session_id: String? = null, val channel: String = "android", val usar_ia: Boolean = false)
data class AgentChatResponse(val session_id: String, val run_id: String, val respuesta: String, val modo: String, val herramienta: String? = null)
data class AgentTaskItem(val id: String, val kind: String, val status: String, val error: String? = null)
data class AgentTasksResponse(val tasks: List<AgentTaskItem> = emptyList())
data class AgentMemoryItem(val scope: String, val kind: String, val topic_key: String, val content: String, val confidence: Double = 0.0, val source: String = "")
data class AgentMemoryResponse(val memory: List<AgentMemoryItem> = emptyList())
data class AgentSubagentItem(val id: String, val name: String, val kind: String, val capabilities: List<String> = emptyList(), val enabled: Boolean = true)
data class AgentSubagentsResponse(val subagents: List<AgentSubagentItem> = emptyList())

interface LaplaceApiService {
    @POST("webhook/kairos-app")
    suspend fun callWebhook(@Body request: WebhookRequest): WebhookResponse

    @POST("api/v1/auth/registro")
    suspend fun registrarCuenta(@Body request: RegistroRequest): AuthResponse

    @POST("api/v1/auth/login")
    suspend fun iniciarSesion(@Body request: LoginRequest): AuthResponse

    @retrofit2.http.POST("api/v1/agent/chat")
    suspend fun agentChat(
        @retrofit2.http.Header("Authorization") authorization: String,
        @Body request: AgentChatRequest,
    ): AgentChatResponse

    @GET("api/v1/agent/capabilities")
    suspend fun agentCapabilities(@retrofit2.http.Header("Authorization") authorization: String): CapacidadesAgenteDto

    @GET("api/v1/agent/usage")
    suspend fun agentUsage(@retrofit2.http.Header("Authorization") authorization: String): UsoAgenteDto

    @retrofit2.http.POST("api/v1/agent/feedback")
    suspend fun agentFeedback(
        @retrofit2.http.Header("Authorization") authorization: String,
        @Body request: AgentFeedbackRequest,
    ): AgentFeedbackResponse

    @POST("api/v1/prediccion-web")
    suspend fun prediccionWeb(
        @retrofit2.http.Header("Authorization") authorization: String,
        @Body request: PrediccionWebRequest,
    ): PrediccionWebDto

    @GET("api/v1/agent/tasks")
    suspend fun agentTasks(@retrofit2.http.Header("Authorization") authorization: String): AgentTasksResponse

    @GET("api/v1/agent/memory")
    suspend fun agentMemory(@retrofit2.http.Header("Authorization") authorization: String): AgentMemoryResponse

    @GET("api/v1/agent/subagents")
    suspend fun agentSubagents(@retrofit2.http.Header("Authorization") authorization: String): AgentSubagentsResponse
}

object HttpLogger {
    data class LogEntry(
        val action: String,
        val status: Int,
        val elapsed: Long,
        val timestamp: String,
        val response: String = "",
    )

    private val logs = mutableListOf<LogEntry>()
    private const val MAX = 100

    @Synchronized
    fun add(entry: LogEntry) {
        if (logs.size >= MAX) logs.removeAt(0)
        logs.add(entry)
    }

    @Synchronized
    fun getLogs(): List<LogEntry> = logs.toList()

    @Synchronized
    fun clear() = logs.clear()
}

class RetryInterceptor(private val maxRetries: Int = 2) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        var attempt = 0
        while (true) {
            try {
                return chain.proceed(chain.request())
            } catch (e: Exception) {
                if (e !is ConnectException && e !is SocketTimeoutException && e !is java.io.IOException) {
                    throw e
                }
                attempt++
                if (attempt >= maxRetries) throw e
                Thread.sleep(1000)
            }
        }
    }
}

class WebhookLogInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val original = chain.request()
        val body = original.body ?: return chain.proceed(original)

        val buffer = okio.Buffer()
        body.writeTo(buffer)
        val bodyStr = buffer.readUtf8()

        val action = try {
            JSONObject(bodyStr).optString("action", "unknown")
        } catch (_: Exception) { "unknown" }

        val newBody = bodyStr.toRequestBody(body.contentType())
        val newRequest = original.newBuilder()
            .method(original.method, newBody)
            .build()

        val start = System.nanoTime()
        val timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())

        return try {
            val response = chain.proceed(newRequest)
            val elapsed = (System.nanoTime() - start) / 1_000_000
            HttpLogger.add(HttpLogger.LogEntry(action, response.code, elapsed, timestamp))
            response
        } catch (e: Exception) {
            val elapsed = (System.nanoTime() - start) / 1_000_000
            val status = when (e) {
                is ConnectException, is SocketTimeoutException -> 0
                else -> -1
            }
            HttpLogger.add(HttpLogger.LogEntry(action, status, elapsed, timestamp, e.message ?: ""))
            throw e
        }
    }
}

object LaplaceApi {
    // La URL del backend sale de la propiedad de Gradle `laplaceBaseUrl` (o LAPLACE_BASE_URL): el repo no trae ningún dominio propio.
    private val BASE_URL: String = BuildConfig.LAPLACE_BASE_URL.ensureTrailingSlash()

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .addInterceptor(RetryInterceptor())
        .addInterceptor { chain ->
            val original = chain.request()
            val builder = original.newBuilder()
            if (BuildConfig.LAPLACE_AUTH_KEY.isNotBlank()) builder.addHeader("x-kairos-key", BuildConfig.LAPLACE_AUTH_KEY)
            val jwt = com.laplace.mobile.data.local.AuthManager.token
            if (!jwt.isNullOrBlank() && original.header("Authorization") == null) {
                builder.addHeader("Authorization", "Bearer $jwt")
            }
            chain.proceed(builder.build())
        }
        .addInterceptor(WebhookLogInterceptor())
        .addInterceptor(HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        })
        .build()

    val service: LaplaceApiService = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(LaplaceApiService::class.java)

    private val agentService: LaplaceApiService = Retrofit.Builder()
        .baseUrl(BuildConfig.LAPLACE_AGENT_URL.ifBlank { BASE_URL }.ensureTrailingSlash())
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(LaplaceApiService::class.java)

    suspend fun chatWithAgent(message: String, sessionId: String? = null, usarIa: Boolean = false): AgentChatResponse? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentChat("Bearer $token", AgentChatRequest(message, sessionId, usar_ia = usarIa))
    }

    suspend fun listAgentTasks(): AgentTasksResponse? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentTasks("Bearer $token")
    }

    suspend fun listAgentMemory(): AgentMemoryResponse? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentMemory("Bearer $token")
    }

    suspend fun listAgentSubagents(): AgentSubagentsResponse? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentSubagents("Bearer $token")
    }

    /** `null` si no hay sesión; 404 (HttpException) si el backend todavía no expone el endpoint. */
    suspend fun agentCapabilities(): CapacidadesAgenteDto? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentCapabilities("Bearer $token")
    }

    suspend fun agentUsage(): UsoAgenteDto? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentUsage("Bearer $token")
    }

    suspend fun sendAgentFeedback(runId: String, rating: Int, label: String): AgentFeedbackResponse? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return agentService.agentFeedback("Bearer $token", AgentFeedbackRequest(runId, rating, label))
    }

    /** Desglose estructurado del consenso (probabilidades, pesos por módulo, tasa base). Requiere JWT. */
    suspend fun prediccionWeb(request: PrediccionWebRequest): PrediccionWebDto? {
        val token = com.laplace.mobile.data.local.AuthManager.token ?: return null
        return service.prediccionWeb("Bearer $token", request)
    }

    private fun String.ensureTrailingSlash(): String = if (endsWith('/')) this else "$this/"

    suspend fun callWebhook(
        action: String,
        params: Map<String, Any?> = emptyMap(),
        deviceId: String = "",
    ): WebhookResponse {
        val resolvedDeviceId = if (deviceId.isBlank() || deviceId == "laplace") {
            com.laplace.mobile.data.local.AuthManager.resolveDeviceId()
        } else {
            deviceId
        }
        val timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())
        return service.callWebhook(WebhookRequest(action, params, resolvedDeviceId, timestamp))
    }

    suspend fun ping(): Long {
        val start = System.nanoTime()
        try {
            service.callWebhook(WebhookRequest("ping", emptyMap(), "", ""))
        } catch (_: Exception) {
            return -1
        }
        return (System.nanoTime() - start) / 1_000_000
    }
}
