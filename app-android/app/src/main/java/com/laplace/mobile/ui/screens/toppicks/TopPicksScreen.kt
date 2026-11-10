package com.laplace.mobile.ui.screens.toppicks

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
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.ui.components.TeamCrest
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.orange
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted

@Composable
fun TopPicksScreen(navController: NavController) {
    var picks by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        try {
            val resp = LaplaceApi.callWebhook(action = "top")
            val raw = resp.data?.get("picks") as? List<*>
            picks = raw?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
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
                    "Error al cargar picks",
                    color = red,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            picks.isEmpty() -> {
                Text(
                    "Sin picks disponibles",
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
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Top Picks", style = MaterialTheme.typography.headlineLarge, color = text)
                    Spacer(Modifier.height(4.dp))
                    picks.forEach { pick ->
                        val local = pick["local"] as? String ?: ""
                        val visitante = pick["visitante"] as? String ?: ""
                        val prediction = pick["prediction"] as? String ?: ""
                        val confianza = pick["confianza"] as? String ?: ""
                        val confianzaInt = confianza.removeSuffix("%").toIntOrNull()
                        val badgeColor = when {
                            confianzaInt == null -> orange
                            confianzaInt >= 70 -> green
                            confianzaInt >= 40 -> orange
                            else -> red
                        }

                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .background(surface)
                                .padding(14.dp),
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.weight(1f)) {
                                    TeamCrest(teamName = local, size = 40.dp)
                                    Spacer(Modifier.height(4.dp))
                                    Text(
                                        local,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = text,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                Text("vs", color = textDim, modifier = Modifier.padding(horizontal = 12.dp))
                                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.weight(1f)) {
                                    TeamCrest(teamName = visitante, size = 40.dp)
                                    Spacer(Modifier.height(4.dp))
                                    Text(
                                        visitante,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = text,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                            }
                            Spacer(Modifier.height(10.dp))
                            Text(
                                prediction,
                                style = MaterialTheme.typography.titleMedium,
                                color = text,
                                fontWeight = FontWeight.SemiBold,
                            )
                            if (confianza.isNotEmpty()) {
                                Spacer(Modifier.height(6.dp))
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Box(
                                        modifier = Modifier
                                            .height(8.dp)
                                            .width(60.dp)
                                            .clip(RoundedCornerShape(4.dp))
                                            .background(badgeColor.copy(alpha = 0.3f)),
                                    )
                                    Spacer(Modifier.width(8.dp))
                                    Text(
                                        "$confianza confianza",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = badgeColor,
                                        fontWeight = FontWeight.Bold,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
