package com.laplace.mobile.ui.screens.about

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.BuildConfig
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun AboutScreen(navController: NavController) {
    val uriHandler = LocalUriHandler.current
    var pingLatency by remember { mutableStateOf<Long?>(null) }
    var pingLoading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(40.dp))
        Text("Laplace", style = MaterialTheme.typography.headlineLarge, color = accent, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text("Predicciones deportivas con IA", style = MaterialTheme.typography.bodyMedium, color = textMuted)
        Spacer(Modifier.height(4.dp))
        Text("v2.0.0", style = MaterialTheme.typography.bodySmall, color = textDim)
        Spacer(Modifier.height(32.dp))
        HorizontalDivider(color = border)
        Spacer(Modifier.height(24.dp))

        InfoRow("Licencia", "AGPL-3.0")
        InfoRow("Backend", "Python (FastAPI)")
        InfoRow("App", "Kotlin Jetpack Compose")
        InfoRow("Backend URL", BuildConfig.LAPLACE_BASE_URL.removePrefix("https://").removePrefix("http://").trimEnd('/'))
        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {
                if (BuildConfig.LAPLACE_COMMUNITY_URL.isNotBlank()) uriHandler.openUri(BuildConfig.LAPLACE_COMMUNITY_URL)
            },
            enabled = BuildConfig.LAPLACE_COMMUNITY_URL.isNotBlank(),
            colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = text),
            modifier = Modifier.fillMaxWidth().height(44.dp),
            shape = RoundedCornerShape(12.dp),
        ) {
            Text("Canal Telegram", fontWeight = FontWeight.SemiBold)
        }

        Spacer(Modifier.height(12.dp))

        Button(
            onClick = {
                scope.launch {
                    pingLoading = true
                    pingLatency = LaplaceApi.ping()
                    pingLoading = false
                }
            },
            colors = ButtonDefaults.buttonColors(containerColor = surface, contentColor = text),
            modifier = Modifier.fillMaxWidth().height(44.dp),
            shape = RoundedCornerShape(12.dp),
        ) {
            val latency = pingLatency
            val pingText = when {
                pingLoading -> "Ping..."
                latency == null -> "Probar conexion (Ping)"
                latency < 0 -> "Sin conexion"
                else -> "${latency}ms"
            }
            Text(pingText, fontWeight = FontWeight.SemiBold)
        }

        Spacer(Modifier.height(32.dp))
        HorizontalDivider(color = border)
        Spacer(Modifier.height(24.dp))

        Text(
            "Laplace es un sistema de predicciones deportivas que utiliza inteligencia artificial para analizar partidos de futbol, generando pronosticos precisos en mercados 1X2, Over/Under y BTTS.",
            style = MaterialTheme.typography.bodyMedium,
            color = textMuted,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(40.dp))

        Button(
            onClick = { navController.popBackStack() },
            colors = ButtonDefaults.buttonColors(containerColor = surface, contentColor = text),
            modifier = Modifier.fillMaxWidth().height(50.dp),
            shape = RoundedCornerShape(12.dp),
        ) {
            Text("Volver", fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(20.dp))
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = textMuted)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = text, fontWeight = FontWeight.Medium)
    }
}
