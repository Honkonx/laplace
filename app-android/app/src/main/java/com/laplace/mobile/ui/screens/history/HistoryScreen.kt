package com.laplace.mobile.ui.screens.history

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.ui.components.TeamCrest
import com.laplace.mobile.ui.theme.*

@Composable
fun HistoryScreen(navController: NavController) {
    var history by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        try {
            val resp = LaplaceApi.callWebhook(action = "historial")
            val raw = resp.data?.get("historial") as? List<*>
            history = raw?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
        } catch (_: Exception) {
            error = true
        } finally {
            loading = false
        }
    }

    Box(Modifier.fillMaxSize().background(bg)) {
        when {
            loading -> {
                CircularProgressIndicator(color = accent, modifier = Modifier.align(Alignment.Center))
            }
            error -> {
                Text("Error al cargar historial", color = red, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.align(Alignment.Center))
            }
            history.isEmpty() -> {
                Text("Sin historial disponible", color = textMuted, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.align(Alignment.Center))
            }
            else -> {
                Column(Modifier.fillMaxSize().padding(20.dp)) {
                    Spacer(Modifier.height(16.dp))
                    Text("Historial", style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(4.dp))
                    Text("${history.size} predicciones", style = MaterialTheme.typography.bodySmall, color = textDim)
                    Spacer(Modifier.height(16.dp))
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(history) { entry ->
                            val local = entry["local"] as? String ?: ""
                            val visitante = entry["visitante"] as? String ?: ""
                            val pick = entry["pick"] as? String ?: ""
                            val confianza = entry["confianza"] as? String ?: ""
                            val resultado = entry["resultado"] as? String ?: ""
                            val acerto = entry["acerto"] as? Boolean ?: false

                            val confianzaInt = confianza.removeSuffix("%").toIntOrNull()
                            val badgeColor = when {
                                confianzaInt == null -> orange
                                confianzaInt >= 70 -> green
                                confianzaInt >= 40 -> orange
                                else -> red
                            }

                            Row(
                                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(surface).padding(14.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.weight(1f)) {
                                    TeamCrest(teamName = local, size = 32.dp)
                                    Text(local, style = MaterialTheme.typography.labelSmall, color = text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text(pick, style = MaterialTheme.typography.bodySmall, color = text, fontWeight = FontWeight.Medium)
                                    if (confianza.isNotEmpty()) {
                                        Text(confianza, style = MaterialTheme.typography.labelSmall, color = badgeColor)
                                    }
                                    if (resultado.isNotEmpty()) {
                                        Text(resultado, style = MaterialTheme.typography.labelSmall, color = textMuted)
                                    }
                                }
                                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.weight(1f)) {
                                    TeamCrest(teamName = visitante, size = 32.dp)
                                    Text(visitante, style = MaterialTheme.typography.labelSmall, color = text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Text(
                                    if (acerto) "\u2713" else "\u2717",
                                    color = if (acerto) green else red,
                                    fontWeight = FontWeight.Bold,
                                    style = MaterialTheme.typography.titleMedium,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
