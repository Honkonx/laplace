package com.laplace.mobile.ui.screens.matches

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.components.MatchCard
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textMuted
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun MatchesScreen(navController: NavController, route: Screen.Matches) {
    var matches by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(route.date, route.league) {
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
            matches = allMatches.filter { (it["liga"] as? String ?: "") == route.league }
        } catch (_: Exception) {
            error = true
        } finally {
            loading = false
        }
    }

    Box(Modifier.fillMaxSize().background(bg)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Text(route.league, style = MaterialTheme.typography.headlineLarge, color = text)
            Spacer(Modifier.height(4.dp))
            Text(route.date, style = MaterialTheme.typography.bodyMedium, color = textMuted)
            Spacer(Modifier.height(20.dp))

            when {
                loading -> {
                    Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = accent)
                    }
                }
                error -> {
                    Text(
                        "Error al cargar partidos",
                        color = red,
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.align(Alignment.CenterHorizontally),
                    )
                }
                matches.isEmpty() -> {
                    Text(
                        "Sin partidos disponibles",
                        color = textMuted,
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.align(Alignment.CenterHorizontally),
                    )
                }
                else -> {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        matches.forEach { match ->
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
                                            date = route.date,
                                            local = match["local"] as? String ?: "",
                                            visitante = match["visitante"] as? String ?: "",
                                            liga = route.league,
                                        ),
                                    )
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}
