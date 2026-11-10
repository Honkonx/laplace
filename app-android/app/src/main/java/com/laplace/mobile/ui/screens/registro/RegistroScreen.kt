package com.laplace.mobile.ui.screens.registro

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.local.AuthManager
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.LoginRequest
import com.laplace.mobile.data.remote.RegistroRequest
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.theme.*
import kotlinx.coroutines.launch
import retrofit2.HttpException

/** Registro o inicio de sesión real con usuario + clave contra el backend FastAPI
 * (`POST /api/v1/auth/registro` o `POST /api/v1/auth/login`, JWT) — se pide exactamente una vez
 * por instalación (ver `AuthManager` para el porqué). Permite recuperar cuenta al reinstalar
 * o usar la misma cuenta creada en la Web/PWA. */
@Composable
fun RegistroScreen(navController: NavController) {
    var esLogin by remember { mutableStateOf(false) }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    val usernameValid = username.matches(Regex("^[a-zA-Z0-9_]{3,20}$"))
    val passwordValid = password.length >= 8
    val canSubmit = usernameValid && passwordValid && !loading

    fun continuarDespuesDeRegistro() {
        val needsNotificationPrompt = Build.VERSION.SDK_INT >= 33 && !PreferencesManager.notificationsAsked
        val destino = if (needsNotificationPrompt) Screen.NotificationPermission else Screen.Home
        navController.navigate(destino) {
            popUpTo(Screen.Onboarding) { inclusive = true }
        }
    }

    suspend fun submit() {
        errorMsg = null
        loading = true
        try {
            val resp = if (esLogin) {
                LaplaceApi.service.iniciarSesion(LoginRequest(username, password))
            } else {
                LaplaceApi.service.registrarCuenta(RegistroRequest(username, password, "app"))
            }
            AuthManager.token = resp.token
            AuthManager.username = resp.username
            AuthManager.rol = resp.rol
            AuthManager.plan = resp.plan
            if (!resp.device_id.isNullOrBlank()) {
                AuthManager.deviceId = resp.device_id
            } else {
                AuthManager.resolveDeviceId()
            }
            PreferencesManager.nickname = resp.username
            PreferencesManager.onboardingDone = true
            continuarDespuesDeRegistro()
        } catch (e: HttpException) {
            errorMsg = when (e.code()) {
                401 -> "Usuario o clave incorrectos."
                409 -> "Ese nombre de usuario ya está en uso. Elegí otro o iniciá sesión."
                429 -> "Demasiados intentos. Esperá un minuto y volvé a intentar."
                400, 422 -> "Usuario o clave inválidos — revisá los requisitos abajo."
                else -> null
            }
            if (errorMsg == null) snackbarHostState.showSnackbar("Error del servidor (${e.code()}). Reintentá.")
        } catch (_: Exception) {
            snackbarHostState.showSnackbar("Error de conexión. Reintentá.")
        } finally {
            loading = false
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        containerColor = bg,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(bg)
                .padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                if (esLogin) "Iniciá sesión" else "Creá tu cuenta",
                style = MaterialTheme.typography.headlineMedium,
                color = text,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                if (esLogin) "Ingresá con tu cuenta existente de Laplace" else "Usuario y clave — se piden solo esta vez",
                style = MaterialTheme.typography.bodyMedium,
                color = textMuted,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(20.dp))

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(surface, RoundedCornerShape(10.dp))
                    .padding(4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Button(
                    onClick = { esLogin = false; errorMsg = null },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (!esLogin) surfaceLight else surface,
                        contentColor = if (!esLogin) text else textMuted,
                    ),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f).height(40.dp),
                    contentPadding = PaddingValues(0.dp),
                ) {
                    Text("Crear cuenta", style = MaterialTheme.typography.labelLarge)
                }
                Button(
                    onClick = { esLogin = true; errorMsg = null },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (esLogin) surfaceLight else surface,
                        contentColor = if (esLogin) text else textMuted,
                    ),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f).height(40.dp),
                    contentPadding = PaddingValues(0.dp),
                ) {
                    Text("Ya tengo cuenta", style = MaterialTheme.typography.labelLarge)
                }
            }

            Spacer(Modifier.height(20.dp))

            OutlinedTextField(
                value = username,
                onValueChange = { v -> if (v.length <= 20 && v.all { it.isLetterOrDigit() || it == '_' }) username = v },
                label = { Text("Usuario") },
                placeholder = { Text("3-20 caracteres") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                colors = laplaceFieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(14.dp))

            OutlinedTextField(
                value = password,
                onValueChange = { v -> if (v.length <= 64) password = v },
                label = { Text("Clave") },
                placeholder = { Text("Mínimo 8 caracteres") },
                singleLine = true,
                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { if (canSubmit) scope.launch { submit() } }),
                trailingIcon = {
                    IconButton(onClick = { showPassword = !showPassword }) {
                        Icon(
                            if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                            contentDescription = if (showPassword) "Ocultar clave" else "Mostrar clave",
                            tint = textMuted,
                        )
                    }
                },
                colors = laplaceFieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(6.dp))
            Text(
                "3-20 caracteres el usuario (letras, números, guion bajo) · 8+ la clave",
                style = MaterialTheme.typography.labelSmall,
                color = textDim,
            )

            errorMsg?.let { mensaje ->
                Spacer(Modifier.height(10.dp))
                Text(mensaje, color = red, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
            }

            Spacer(Modifier.height(24.dp))

            Button(
                onClick = { scope.launch { submit() } },
                enabled = canSubmit,
                colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = text, disabledContainerColor = surface),
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = RoundedCornerShape(12.dp),
            ) {
                if (loading) {
                    CircularProgressIndicator(color = text, modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                } else {
                    Text(if (esLogin) "Entrar" else "Crear cuenta", fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun laplaceFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = text, unfocusedTextColor = text, cursorColor = accent,
    focusedBorderColor = accent, unfocusedBorderColor = border,
    focusedLabelColor = accent, unfocusedLabelColor = textMuted,
    errorBorderColor = red, errorLabelColor = red, errorTextColor = text,
)
