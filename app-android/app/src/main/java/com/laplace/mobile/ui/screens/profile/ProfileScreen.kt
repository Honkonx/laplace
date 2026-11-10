package com.laplace.mobile.ui.screens.profile

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.local.AuthManager
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.theme.*

private data class MenuItem(val label: String, val screen: Screen)

@Composable
fun ProfileScreen(navController: NavController) {
    val nickname = PreferencesManager.nickname.ifEmpty { "Invitado" }
    // `rol` — 2026-09-10: viene del JWT de `/api/v1/auth/registro`/`login` (guardado en
    // `AuthManager` al registrarse), no de `action: "profile"` — ese gateway por device_id
    // (`usuarios_repo.obtener_usuario_app`) todavía no expone `rol` en su respuesta. Se muestra
    // solo cuando es distinto de "usuario" (el caso común) para no agregar ruido visual a la
    // mayoría de las cuentas — mismo criterio de "mostrar de dónde sale el dato, sin ocultarlo,
    // pero sin ruido innecesario" que ya usa el resto de la UI (`product-philosophy.md`).
    val rol = AuthManager.rol?.takeIf { it.isNotBlank() && it != "usuario" }
    var plan by remember { mutableStateOf("FREE") }
    var picksTotal by remember { mutableStateOf(0) }
    var racha by remember { mutableStateOf(0) }
    var rachaTipo by remember { mutableStateOf("sin_datos") }
    var restantesHoy by remember { mutableStateOf<Int?>(null) }

    LaunchedEffect(Unit) {
        try {
            // `action: "profile"` — antes esta pantalla llamaba a "stats" (estadística GLOBAL
            // del bot, no del usuario), por eso plan/picks/racha siempre mostraban el default.
            val resp = LaplaceApi.callWebhook(action = "profile")
            val data = resp.data ?: emptyMap()
            plan = (data["plan"] as? String ?: "free").uppercase()
            picksTotal = (data["picks_total"] as? Number)?.toInt() ?: 0
            restantesHoy = (data["restantes_hoy"] as? Number)?.toInt()
            @Suppress("UNCHECKED_CAST")
            val rachaData = data["racha_user"] as? Map<String, Any?>
            racha = (rachaData?.get("racha") as? Number)?.toInt() ?: 0
            rachaTipo = rachaData?.get("tipo") as? String ?: "sin_datos"
        } catch (_: Exception) {}
    }

    val planColor = when (plan) {
        "PRO" -> accent
        "MAX" -> green
        else -> orange
    }
    val rachaColor = when (rachaTipo) {
        "acierto" -> green
        "fallo" -> red
        else -> textMuted
    }

    val menuItems = listOf(
        MenuItem("Historial", Screen.History),
        MenuItem("Codigo Activacion", Screen.CodigoActivacion),
        MenuItem("Mejorar Plan", Screen.Upgrade),
        MenuItem("Config Tema", Screen.ConfigTheme),
        MenuItem("Log", Screen.Log),
        MenuItem("Acerca de", Screen.About),
    )

    Box(Modifier.fillMaxSize().background(bg)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Spacer(Modifier.height(16.dp))

            Box(
                modifier = Modifier
                    .size(80.dp)
                    .clip(CircleShape)
                    .background(accent.copy(alpha = 0.2f))
                    .align(Alignment.CenterHorizontally),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    nickname.take(2).uppercase(),
                    style = MaterialTheme.typography.headlineMedium,
                    color = accent,
                    fontWeight = FontWeight.Bold,
                )
            }

            Spacer(Modifier.height(12.dp))
            Text(
                nickname,
                style = MaterialTheme.typography.headlineMedium,
                color = text,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.align(Alignment.CenterHorizontally),
            )
            Spacer(Modifier.height(8.dp))

            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(20.dp))
                    .background(planColor.copy(alpha = 0.15f))
                    .padding(horizontal = 16.dp, vertical = 6.dp)
                    .align(Alignment.CenterHorizontally),
            ) {
                Text(plan, color = planColor, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
            }

            rol?.let { valor ->
                Spacer(Modifier.height(6.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .background(cyan.copy(alpha = 0.15f))
                        .padding(horizontal = 16.dp, vertical = 4.dp)
                        .align(Alignment.CenterHorizontally),
                ) {
                    Text(
                        valor.uppercase(),
                        color = cyan,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }

            Spacer(Modifier.height(24.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                StatBox("Picks totales", "$picksTotal", accent, Modifier.weight(1f))
                StatBox("Racha", "$racha", rachaColor, Modifier.weight(1f))
                if (restantesHoy != null) {
                    StatBox("Restan hoy", "$restantesHoy", cyan, Modifier.weight(1f))
                }
            }

            Spacer(Modifier.height(24.dp))
            Text("Menu", style = MaterialTheme.typography.titleLarge, color = text)
            Spacer(Modifier.height(12.dp))

            menuItems.forEach { item ->
                MenuRow(item.label) {
                    navController.navigate(item.screen)
                }
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
private fun StatBox(label: String, value: String, color: androidx.compose.ui.graphics.Color, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(value, style = MaterialTheme.typography.headlineMedium, color = color, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text(label, style = MaterialTheme.typography.bodySmall, color = textMuted)
    }
}

@Composable
private fun MenuRow(label: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.titleMedium, color = text, modifier = Modifier.weight(1f))
        Text("›", style = MaterialTheme.typography.titleLarge, color = textDim)
    }
}
