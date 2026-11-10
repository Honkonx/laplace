package com.laplace.mobile.ui.screens.leagues

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun LeaguesScreen(navController: NavController, route: Screen.Leagues) {
    var leagues by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(route.date) {
        try {
            val resp = LaplaceApi.service.callWebhook(
                WebhookRequest(
                    action = "juegos",
                    params = mapOf("date" to route.date),
                    device_id = "laplace",
                    timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date()),
                )
            )
            val raw = resp.data?.get("partidos") as? List<*>
            val allMatches = raw?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
            val grouped = allMatches.groupBy { it["liga"] as? String ?: "Otras" }
            leagues = grouped.map { (name, matches) ->
                val hasAnalysis = matches.any { it["prediction"] != null }
                mapOf(
                    "name" to name,
                    "matches" to matches.size,
                    "has_analysis" to hasAnalysis,
                )
            }
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
                    "Error al cargar ligas",
                    color = red,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            leagues.isEmpty() -> {
                Text(
                    "Sin ligas disponibles",
                    color = textMuted,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            else -> {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(20.dp),
                ) {
                    Text("Ligas", style = MaterialTheme.typography.headlineLarge, color = text)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Selecciona una liga para ver sus partidos",
                        style = MaterialTheme.typography.bodyMedium,
                        color = textMuted,
                    )
                    Spacer(Modifier.height(20.dp))
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        leagues.forEach { league ->
                            val name = league["name"] as? String ?: ""
                            val matchCount = (league["matches"] as? Int) ?: 0
                            val hasAnalysis = league["has_analysis"] as? Boolean ?: false

                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(12.dp))
                                    .background(surface)
                                    .clickable {
                                        navController.navigate(Screen.Matches(route.date, name))
                                    }
                                    .padding(16.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(44.dp)
                                        .clip(CircleShape)
                                        .background(surfaceLight),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Text(
                                        name.take(2).uppercase(),
                                        color = accent,
                                        fontWeight = FontWeight.Bold,
                                        style = MaterialTheme.typography.titleMedium,
                                    )
                                }
                                Spacer(Modifier.width(14.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        name,
                                        style = MaterialTheme.typography.titleMedium,
                                        color = text,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        "$matchCount partidos",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = textMuted,
                                    )
                                }
                                if (hasAnalysis) {
                                    Text(
                                        "IA",
                                        color = green,
                                        fontWeight = FontWeight.Bold,
                                        style = MaterialTheme.typography.labelSmall,
                                        modifier = Modifier
                                            .clip(RoundedCornerShape(6.dp))
                                            .background(green.copy(alpha = 0.15f))
                                            .padding(horizontal = 8.dp, vertical = 4.dp),
                                    )
                                }
                                Text("›", color = textDim, style = MaterialTheme.typography.titleLarge)
                            }
                        }
                    }
                }
            }
        }
    }
}
