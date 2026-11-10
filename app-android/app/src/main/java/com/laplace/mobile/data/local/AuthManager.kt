package com.laplace.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.edit
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Guarda el JWT emitido por `POST /api/v1/auth/registro` (backend FastAPI real, no el webhook
 * viejo) — cifrado con `EncryptedSharedPreferences`, mismo mecanismo que ya usa
 * `ProfileRepository` para el device_id. 2026-09-08.
 *
 * La contraseña en sí NUNCA se guarda acá ni en ningún lado — solo el token de sesión. Por
 * diseño, el registro (usuario+clave) solo se pide UNA vez por instalación: una vez que
 * `token` no es null, `AppNavHost` salta directo a Home. La clave solo volvería a hacer falta
 * si el usuario reinstala, cambia de dispositivo, o usa la web (`frontend/`) — ahí sí inicia
 * sesión con `POST /api/v1/auth/login` usando la misma cuenta. */
object AuthManager {
    private const val NAME = "laplace_auth"
    private var prefs: SharedPreferences? = null

    var planState by mutableStateOf("free")
        private set

    fun init(context: Context) {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        prefs = EncryptedSharedPreferences.create(
            context, NAME, masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
        planState = prefs?.getString("plan", "free") ?: "free"
    }

    var token: String?
        get() = prefs?.getString("jwt_token", null)
        set(value) { prefs?.edit { putString("jwt_token", value) } }

    var username: String?
        get() = prefs?.getString("username", null)
        set(value) { prefs?.edit { putString("username", value) } }

    // `rol` — 2026-09-10, mismo claim que ya trae el JWT (`usuario`/`admin`/`agente`, ver
    // `backend/api/routers/auth.py::_emitir_token`). Se guarda por separado del token porque
    // decodificar el JWT en el cliente para leer un claim no es necesario acá — el backend ya
    // lo manda plano en la respuesta de registro/login.
    var rol: String?
        get() = prefs?.getString("rol", null)
        set(value) { prefs?.edit { putString("rol", value) } }

    var plan: String
        get() = prefs?.getString("plan", planState) ?: planState
        set(value) {
            val norm = value.lowercase().ifBlank { "free" }
            planState = norm
            prefs?.edit { putString("plan", norm) }
        }

    var deviceId: String?
        get() = prefs?.getString("device_id", null)
        set(value) { prefs?.edit { putString("device_id", value) } }

    /** Resuelve el `device_id` canónico del usuario:
     * 1) `deviceId` persistido tras `/api/v1/auth/registro`,
     * 2) claim `sub` del JWT si existe un token pero aún no se guardó `device_id`,
     * 3) un identificador único por instalación generado una sola vez.
     * Nunca devuelve `""` ni `"laplace"`. */
    fun resolveDeviceId(): String {
        val current = deviceId
        if (!current.isNullOrBlank() && current != "laplace") {
            return current
        }
        val jwt = token
        if (!jwt.isNullOrBlank()) {
            val sub = extraerSubDeJwt(jwt)
            if (!sub.isNullOrBlank() && sub != "laplace") {
                deviceId = sub
                return sub
            }
        }
        val generated = "app_${System.currentTimeMillis().toString(36)}_${(10000000..99999999).random()}"
        deviceId = generated
        return generated
    }

    private fun extraerSubDeJwt(jwt: String): String? {
        return try {
            val parts = jwt.split(".")
            if (parts.size < 2) return null
            val payloadBytes = android.util.Base64.decode(
                parts[1],
                android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
            )
            val json = org.json.JSONObject(String(payloadBytes, Charsets.UTF_8))
            json.optString("sub", "").takeIf { it.isNotBlank() }
        } catch (_: Exception) {
            null
        }
    }

    val hasAccount: Boolean get() = token != null
}
