package com.laplace.mobile.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.orange
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class StatItem(val label: String, val value: String, val color: androidx.compose.ui.graphics.Color = accent)

@Composable
fun StatsScreen(navController: NavController) {
    var statsData by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        try {
            val resp = LaplaceApi.service.callWebhook(
                WebhookRequest(
                    action = "stats",
                    params = emptyMap(),
                    device_id = "laplace",
                    timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date()),
                )
            )
            statsData = resp.data
        } catch (_: Exception) {
            error = true
        } finally {
            loading = false
        }
    }

    Box(Modifier.fillMaxSize().background(bg)) {
        when {
            loading -> {
                CircularProgressIndicator(
                    color = accent,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            error -> {
                Text(
                    "Error al cargar estadísticas",
                    color = red,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            statsData == null -> {
                Text(
                    "Sin datos disponibles",
                    color = textMuted,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            else -> {
                val data = statsData ?: emptyMap()
                val winRate = data["win_rate"]?.toString() ?: "0"
                val totalPicks = data["total_picks"]?.toString() ?: "0"
                val streak = data["streak"]?.toString() ?: "0"
                val hits = data["hits"]?.toString() ?: "0"
                val misses = data["misses"]?.toString() ?: "0"
                val bestLeague = data["best_league"]?.toString() ?: "--"

                val winRateInt = winRate.removeSuffix("%").toIntOrNull() ?: 0
                val rateColor = when {
                    winRateInt >= 70 -> green
                    winRateInt >= 40 -> orange
                    else -> red
                }

                val statsList = listOf(
                    StatItem("Win Rate", "$winRate%", rateColor),
                    StatItem("Total Picks", totalPicks, accent),
                    StatItem("Aciertos", hits, green),
                    StatItem("Fallos", misses, red),
                    StatItem("Racha", streak, orange),
                    StatItem("Mejor Liga", bestLeague, text),
                )

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Estadísticas", style = MaterialTheme.typography.headlineLarge, color = text)
                    Spacer(Modifier.height(4.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        statsList.take(3).forEach { stat ->
                            StatCard(stat, Modifier.weight(1f))
                        }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        statsList.drop(3).forEach { stat ->
                            StatCard(stat, Modifier.weight(1f))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatCard(stat: StatItem, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            stat.value,
            style = MaterialTheme.typography.headlineMedium,
            color = stat.color,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            stat.label,
            style = MaterialTheme.typography.bodySmall,
            color = textMuted,
        )
    }
}
