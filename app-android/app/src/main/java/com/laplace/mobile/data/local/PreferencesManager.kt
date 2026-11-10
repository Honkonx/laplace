package com.laplace.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.edit

/** Respaldado por `SharedPreferences` (persistencia) + `mutableStateOf` (reactividad Compose) —
 * antes solo lo primero, así que cambiar `themeMode` desde `ConfigThemeScreen` guardaba la
 * preferencia pero ninguna pantalla ya abierta se recomponía para reflejarla. 2026-09-08. */
object PreferencesManager {
    private const val NAME = "laplace_prefs"
    private var prefs: SharedPreferences? = null

    private var _onboardingDone by mutableStateOf(false)
    private var _notificationsAsked by mutableStateOf(false)
    private var _themeMode by mutableStateOf("dark")
    private var _nickname by mutableStateOf("")
    private var _termsAccepted by mutableStateOf(false)

    fun init(context: Context) {
        prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
        _onboardingDone = prefs?.getBoolean("onboarding_done", false) ?: false
        _notificationsAsked = prefs?.getBoolean("notifications_asked", false) ?: false
        _themeMode = prefs?.getString("theme_mode", "dark") ?: "dark"
        _nickname = prefs?.getString("nickname", "") ?: ""
        _termsAccepted = prefs?.getBoolean("terms_accepted", false) ?: false
    }

    var onboardingDone: Boolean
        get() = _onboardingDone
        set(value) { _onboardingDone = value; prefs?.edit { putBoolean("onboarding_done", value) } }

    var notificationsAsked: Boolean
        get() = _notificationsAsked
        set(value) { _notificationsAsked = value; prefs?.edit { putBoolean("notifications_asked", value) } }

    /** "dark" | "light" | "marino" */
    var themeMode: String
        get() = _themeMode
        set(value) { _themeMode = value; prefs?.edit { putString("theme_mode", value) } }

    var nickname: String
        get() = _nickname
        set(value) { _nickname = value; prefs?.edit { putString("nickname", value) } }

    /** Aceptación de Términos y Condiciones — 2026-09-08, requerida antes de poder registrarse
     * (ver ui/screens/onboarding/OnboardingScreen.kt, la pantalla de presentación de Laplace). */
    var termsAccepted: Boolean
        get() = _termsAccepted
        set(value) { _termsAccepted = value; prefs?.edit { putBoolean("terms_accepted", value) } }
}
