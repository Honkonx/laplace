package com.laplace.mobile.ui.screens.prediction

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.components.LEYENDA_ESTIMACION
import com.laplace.mobile.ui.components.PredictionCard
import com.laplace.mobile.ui.components.PrediccionDetalle
import com.laplace.mobile.ui.components.TeamCrest
import com.laplace.mobile.ui.components.TextoFormateado
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted
import java.util.Locale

@Composable
fun PredictionScreen(navController: NavController, route: Screen.Prediction) {
    val viewModel: PredictionViewModel = viewModel()
    val ui by viewModel.ui.collectAsState()
    LaunchedEffect(route) { viewModel.cargar(route) }

    Box(Modifier.fillMaxSize().background(bg)) {
        when (ui.estado) {
            EstadoAnalisis.CARGANDO -> Estado(
                titulo = "Analizando...",
                detalle = "Laplace reúne datos verificados de ambos equipos. Puede tardar unos segundos.",
                cargando = true,
            )
            EstadoAnalisis.FALLO_RED -> Estado(
                titulo = "No pudimos conectar con Laplace",
                detalle = "Revisa tu conexión e inténtalo de nuevo.",
                alReintentar = { viewModel.cargar(route, forzar = true) },
            )
            EstadoAnalisis.FALLO_ANALISIS -> Estado(
                titulo = "El análisis no se pudo completar",
                detalle = "Ocurrió un error al analizar este partido. Puedes reintentarlo.",
                alReintentar = { viewModel.cargar(route, forzar = true) },
            )
            EstadoAnalisis.EN_PROCESO -> Estado(
                titulo = "El análisis sigue en proceso",
                detalle = "Está tardando más de lo normal. Vuelve a consultar en un momento.",
                alReintentar = { viewModel.cargar(route, forzar = true) },
            )
            EstadoAnalisis.LISTO -> Resultado(ui, route)
        }
    }
}

@Composable
private fun Estado(
    titulo: String,
    detalle: String,
    cargando: Boolean = false,
    alReintentar: (() -> Unit)? = null,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (cargando) {
            CircularProgressIndicator(color = accent)
            Spacer(Modifier.height(16.dp))
        }
        Text(titulo, style = MaterialTheme.typography.titleMedium, color = text, textAlign = TextAlign.Center)
        Spacer(Modifier.height(6.dp))
        Text(detalle, style = MaterialTheme.typography.bodyMedium, color = textMuted, textAlign = TextAlign.Center)
        if (alReintentar != null) {
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = alReintentar,
                modifier = Modifier.heightIn(min = 48.dp),
                colors = ButtonDefaults.buttonColors(containerColor = accent),
            ) { Text("Reintentar") }
        }
    }
}

@Composable
private fun Resultado(ui: PredictionUiState, route: Screen.Prediction) {
    val datos = ui.datos.orEmpty()
    val local = (datos["local"] as? String).takeUnless { it.isNullOrBlank() } ?: route.local
    val visitante = (datos["visitante"] as? String).takeUnless { it.isNullOrBlank() } ?: route.visitante

    // `content` es un dict {pick, confianza, texto_completo, ...} (check_job) o, con caché de
    // consenso (job_id="cache"), directamente el texto ya armado.
    val contenido = datos["content"]
    val job = ContenidoJob.desdeMapa(contenido as? Map<*, *>)
    val analisis = job?.analisis ?: (contenido as? String).orEmpty()
    val marcadorLocal = datos["gol_local"] as? String
    val marcadorVisitante = datos["gol_visitante"] as? String
    val estadoPartido = datos["status"] as? String

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Encabezado(local, visitante, marcadorLocal, marcadorVisitante, estadoPartido)
        Spacer(Modifier.height(4.dp))

        when (val desglose = ui.desglose) {
            is Desglose.Listo -> PrediccionDetalle(desglose.vista, local, visitante)
            else -> {
                if (job != null && job.pick.isNotEmpty()) {
                    PredictionCard(pick = job.pick, confianza = job.confianza, source = job.fuente, local = local, visitante = visitante)
                } else if (desglose !is Desglose.Cargando) {
                    Aviso("Este análisis no trae un pick estructurado. Se muestra solo el texto del análisis.")
                }
                if (desglose is Desglose.Cargando) IndicadorDesglose()
            }
        }

        if (analisis.isNotEmpty()) {
            Seccion("Análisis") { TextoFormateado(analisis, textMuted) }
        }
        val xgLocal = job?.xgLocal
        val xgVisit = job?.xgVisit
        if (xgLocal != null && xgVisit != null) {
            Seccion("xG esperado") {
                Text("Goles esperados por equipo (fuente BSD API).", style = MaterialTheme.typography.labelSmall, color = textDim)
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                    Xg(local, xgLocal)
                    Xg(visitante, xgVisit)
                }
            }
        }
        if (ui.desglose !is Desglose.Listo && job != null) {
            Text(LEYENDA_ESTIMACION, style = MaterialTheme.typography.labelSmall, color = textDim)
        }
    }
}

@Composable
private fun Encabezado(local: String, visitante: String, golLocal: String?, golVisitante: String?, estado: String?) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
        Equipo(local)
        Spacer(Modifier.width(20.dp))
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (golLocal != null && golVisitante != null) {
                Text("$golLocal - $golVisitante", style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
            } else {
                Text("vs", style = MaterialTheme.typography.titleLarge, color = textDim)
            }
            estado?.let {
                Text(
                    it.uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = when (it) {
                        "live", "en_vivo" -> green
                        "final", "finished" -> red
                        else -> textMuted
                    },
                    fontWeight = FontWeight.Bold,
                )
            }
        }
        Spacer(Modifier.width(20.dp))
        Equipo(visitante)
    }
}

@Composable
private fun Equipo(nombre: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(100.dp)) {
        TeamCrest(teamName = nombre, size = 56.dp)
        Spacer(Modifier.height(6.dp))
        Text(nombre, style = MaterialTheme.typography.titleMedium, color = text, maxLines = 2, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center)
    }
}

@Composable
private fun IndicadorDesglose() {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = accent)
        Text("Calculando el desglose de probabilidades…", style = MaterialTheme.typography.bodySmall, color = textMuted)
    }
}

@Composable
private fun Aviso(mensaje: String) {
    Text(mensaje, style = MaterialTheme.typography.bodyMedium, color = textMuted)
}

@Composable
private fun Seccion(titulo: String, contenido: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(surface).padding(14.dp)) {
        Text(titulo, style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        contenido()
    }
}

@Composable
private fun Xg(nombre: String, valor: Double) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(String.format(Locale.US, "%.2f", valor), style = MaterialTheme.typography.headlineSmall, color = text, fontWeight = FontWeight.Bold)
        Text(nombre, style = MaterialTheme.typography.labelSmall, color = textMuted)
    }
}
