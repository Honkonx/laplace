package com.laplace.mobile.ui.screens.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.ShowChart
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.theme.*
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.ui.components.BannerCarousel
import com.laplace.mobile.ui.components.MatchCard
import com.laplace.mobile.ui.components.TeamCrest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun HomeScreen(navController: NavController) {
    val nickname = PreferencesManager.nickname.ifEmpty { "Invitado" }
    var racha by remember { mutableStateOf(0) }
    var prediccionesHoy by remember { mutableStateOf(0) }
    var plan by remember { mutableStateOf("FREE") }
    var pingOk by remember { mutableStateOf(true) }

    var leagues by remember { mutableStateOf<Map<String, List<Map<String, Any?>>>>(emptyMap()) }
    var loadingMatches by remember { mutableStateOf(true) }

    val todayStr = remember { SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date()) }

    LaunchedEffect(Unit) {
        pingOk = LaplaceApi.ping() >= 0
        try {
            // `action: "profile"` es la data POR USUARIO (plan, racha, uso hoy) — `"stats"` es
            // estadística GLOBAL del bot, no del usuario. Antes esta pantalla llamaba "stats" y
            // por eso plan/racha/picks nunca mostraban un valor real, siempre el default.
            val res = LaplaceApi.callWebhook(action = "profile")
            val data = res.data ?: emptyMap()
            plan = (data["plan"] as? String ?: "free").uppercase()
            prediccionesHoy = (data["predicciones_hoy"] as? Number)?.toInt() ?: 0
            @Suppress("UNCHECKED_CAST")
            val rachaData = data["racha_user"] as? Map<String, Any?>
            racha = (rachaData?.get("racha") as? Number)?.toInt() ?: 0
        } catch (_: Exception) {}

        try {
            val res = LaplaceApi.callWebhook(action = "juegos", params = mapOf("date" to todayStr))
            val data = res.data ?: emptyMap()
            @Suppress("UNCHECKED_CAST")
            val ligasRaw = data["ligas"] as? Map<String, Any?>
            leagues = if (ligasRaw != null) {
                ligasRaw.entries.mapNotNull { (slug, v) ->
                    val liga = v as? Map<*, *> ?: return@mapNotNull null
                    val nombre = liga["nombre"] as? String ?: slug
                    val partidos = (liga["partidos"] as? List<*>)?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
                    if (partidos.isEmpty()) null else nombre to partidos
                }.toMap()
            } else {
                val partidos = (data["partidos"] as? List<*>)?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
                partidos.groupBy { it["liga"] as? String ?: "Otras" }
            }
        } catch (_: Exception) {
        } finally {
            loadingMatches = false
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp),
    ) {
        Spacer(Modifier.height(56.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("Hola,", style = MaterialTheme.typography.bodyMedium, color = textMuted)
                Text(nickname, style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.height(24.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            StatTile("Racha", "$racha", Icons.Default.Star, accent)
            StatTile("Picks hoy", "$prediccionesHoy", Icons.Default.ShowChart, green)
            StatTile("Plan", plan, Icons.Default.CalendarMonth, cyan)
        }
        Spacer(Modifier.height(20.dp))

        // Se mantiene tal cual — ya tiene las imágenes reales del banner y el botón de Telegram.
        BannerCarousel()
        Spacer(Modifier.height(20.dp))

        if (!pingOk) {
            Text(
                "Sin conexion al servidor",
                color = orange,
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Medium,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(orange.copy(alpha = 0.1f))
                    .padding(12.dp),
            )
            Spacer(Modifier.height(12.dp))
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Partidos de hoy", style = MaterialTheme.typography.titleLarge, color = text, fontWeight = FontWeight.Bold)
            Text(
                "Ver todo ›",
                style = MaterialTheme.typography.labelLarge,
                color = accent,
                modifier = Modifier.clickable { navController.navigate(Screen.Calendar) },
            )
        }
        Spacer(Modifier.height(12.dp))

        when {
            loadingMatches -> {
                Box(Modifier.fillMaxWidth().padding(vertical = 24.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = accent)
                }
            }
            leagues.isEmpty() -> {
                Text("Sin partidos para hoy", color = textMuted, style = MaterialTheme.typography.bodyMedium)
            }
            else -> {
                leagues.entries.take(3).forEach { (liga, partidos) ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 6.dp)) {
                        TeamCrest(teamName = liga, size = 22.dp, league = true)
                        Spacer(Modifier.width(8.dp))
                        Text(liga, style = MaterialTheme.typography.titleSmall, color = text, fontWeight = FontWeight.SemiBold)
                    }
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        partidos.take(3).forEach { match ->
                            MatchCard(
                                localName = match["local"] as? String ?: "",
                                visitanteName = match["visitante"] as? String ?: "",
                                hora = match["hora"] as? String ?: "",
                                scoreLocal = match["gol_local"] as? String,
                                scoreVisitante = match["gol_visitante"] as? String,
                                status = match["status"] as? String,
                                pronosticable = match["pronosticable"] as? Boolean ?: false,
                                onClick = {
                                    val id = match["id"]?.toString() ?: ""
                                    navController.navigate(
                                        Screen.Prediction(
                                            matchId = id,
                                            date = todayStr,
                                            local = match["local"] as? String ?: "",
                                            visitante = match["visitante"] as? String ?: "",
                                        ),
                                    )
                                },
                            )
                        }
                    }
                    Spacer(Modifier.height(14.dp))
                }
            }
        }

        Spacer(Modifier.height(10.dp))
        QuickNavCard("Top Picks", "Mejores predicciones del dia", Icons.Default.Star) {
            navController.navigate(Screen.TopPicks)
        }
        Spacer(Modifier.height(10.dp))
        QuickNavCard("Estadisticas", "Rendimiento y metricas", Icons.Default.ShowChart) {
            navController.navigate(Screen.Stats)
        }
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun RowScope.StatTile(label: String, value: String, icon: androidx.compose.ui.graphics.vector.ImageVector, color: androidx.compose.ui.graphics.Color) {
    Column(
        modifier = Modifier
            .weight(1f)
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(value, style = MaterialTheme.typography.headlineMedium, color = color, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = textMuted, textAlign = TextAlign.Center)
    }
}

@Composable
private fun QuickNavCard(label: String, sublabel: String, icon: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .clickable(onClick = onClick)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        androidx.compose.material3.Icon(icon, contentDescription = label, tint = accent, modifier = Modifier.size(28.dp))
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
            Text(sublabel, style = MaterialTheme.typography.bodySmall, color = textMuted)
        }
        Text("›", style = MaterialTheme.typography.titleLarge, color = textDim)
    }
}
