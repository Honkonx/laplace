package com.laplace.mobile.ui.screens.onboarding

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.Functions
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.theme.*
import kotlinx.coroutines.delay

/** Una "feature card" de la presentación: ícono en badge circular + título + descripción corta.
 * Patrón adaptado (no copiado) de `WelcomeScreen.kt` de Droidspaces-OSS
 * (proyecto de referencia Droidspaces-OSS, carpeta Android/...) —
 * ese proyecto es un fork de Termux sin ninguna relación con fútbol, pero el patrón visual
 * (badge de ícono + título + descripción, entrada animada en cascada) se reimplementa acá con
 * los componentes/tema propios de Laplace. 2026-09-08. */
private data class LaplaceFeature(val icon: ImageVector, val titulo: String, val descripcion: String)

private val FEATURES = listOf(
    LaplaceFeature(
        icon = Icons.Default.Functions,
        titulo = "Cálculo real, no promesas",
        descripcion = "Poisson, Dixon-Coles y un consenso ponderado entre fuentes reales.",
    ),
    LaplaceFeature(
        icon = Icons.Default.Psychology,
        titulo = "De dónde viene el nombre",
        descripcion = "El Demonio de Laplace: con los datos suficientes, el futuro se puede calcular.",
    ),
    LaplaceFeature(
        icon = Icons.Default.Block,
        titulo = "Nunca una casa de apuestas",
        descripcion = "Pronóstico y análisis deportivo — sin apuestas, sin \"picks seguros\" sin respaldo.",
    ),
)

/** Pantalla de presentación de Laplace — primera pantalla que ve un usuario nuevo. Antes esta
 * pantalla (`OnboardingScreen`) pedía directo un nickname; ahora presenta la marca, exige
 * aceptar los Términos y Condiciones (ventana con el texto completo, ver `TerminosDialog`), y
 * recién ahí deja continuar a `Screen.Registro` (usuario + clave real). 2026-09-08.
 *
 * Rediseño 2026-09-08: entrada animada en cascada (logo → título → tarjetas de feature) en vez
 * de aparecer todo de golpe, y el párrafo plano de "de dónde viene el nombre" se reemplaza por
 * 3 tarjetas de feature — mismo contenido, mejor jerarquía visual. Checkbox de Términos y botón
 * "Continuar" quedan con exactamente la misma lógica de antes (`PreferencesManager.termsAccepted`,
 * navegación a `Screen.Registro`). */
@Composable
fun OnboardingScreen(navController: NavController) {
    var showTerms by remember { mutableStateOf(false) }
    var accepted by remember { mutableStateOf(PreferencesManager.termsAccepted) }

    var iconVisible by remember { mutableStateOf(false) }
    var titleVisible by remember { mutableStateOf(false) }
    var cardsVisible by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        delay(60); iconVisible = true
        delay(120); titleVisible = true
        delay(150); cardsVisible = true
    }

    val fadeSpec = tween<Float>(durationMillis = 400, easing = FastOutSlowInEasing)
    val iconAlpha by animateFloatAsState(if (iconVisible) 1f else 0f, fadeSpec, label = "onboarding_icon")
    val titleAlpha by animateFloatAsState(if (titleVisible) 1f else 0f, fadeSpec, label = "onboarding_title")
    val cardsAlpha by animateFloatAsState(if (cardsVisible) 1f else 0f, fadeSpec, label = "onboarding_cards")

    if (showTerms) {
        TerminosDialog(onDismiss = { showTerms = false })
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(bg),
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(48.dp))

            Box(
                modifier = Modifier
                    .alpha(iconAlpha)
                    .size(88.dp)
                    .clip(RoundedCornerShape(24.dp))
                    .background(accentGlow),
                contentAlignment = Alignment.Center,
            ) {
                Text("L", style = MaterialTheme.typography.displayMedium, color = accent, fontWeight = FontWeight.Bold)
            }

            Spacer(Modifier.height(24.dp))

            Column(
                modifier = Modifier.alpha(titleAlpha),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Laplace",
                    style = MaterialTheme.typography.displayMedium,
                    color = text,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Pronóstico deportivo con cálculo real",
                    style = MaterialTheme.typography.bodyLarge,
                    color = textMuted,
                    textAlign = TextAlign.Center,
                )
            }

            Spacer(Modifier.height(32.dp))

            Column(
                modifier = Modifier.fillMaxWidth().alpha(cardsAlpha),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                FEATURES.forEach { feature -> FeatureCard(feature) }
            }

            Spacer(Modifier.height(24.dp))
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 32.dp, vertical = 20.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .clickable { accepted = !accepted }
                    .padding(vertical = 8.dp),
            ) {
                Checkbox(
                    checked = accepted,
                    onCheckedChange = { accepted = it },
                    colors = CheckboxDefaults.colors(checkedColor = accent, uncheckedColor = textMuted),
                )
                Spacer(Modifier.width(4.dp))
                Text(
                    "Acepto los ",
                    style = MaterialTheme.typography.bodyMedium,
                    color = textMuted,
                )
                Text(
                    "Términos y Condiciones",
                    style = MaterialTheme.typography.bodyMedium,
                    color = accent,
                    fontWeight = FontWeight.SemiBold,
                    textDecoration = TextDecoration.Underline,
                    modifier = Modifier.clickable { showTerms = true },
                )
            }

            Spacer(Modifier.height(16.dp))

            Button(
                onClick = {
                    PreferencesManager.termsAccepted = true
                    navController.navigate(Screen.Registro)
                },
                enabled = accepted,
                colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = text, disabledContainerColor = surface),
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = RoundedCornerShape(12.dp),
            ) {
                Text("Continuar", fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun FeatureCard(feature: LaplaceFeature) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = surface,
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(12.dp))
                    .background(accentGlow)
                    .padding(10.dp),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = feature.icon,
                    contentDescription = null,
                    modifier = Modifier.size(20.dp),
                    tint = accent,
                )
            }
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    feature.titulo,
                    style = MaterialTheme.typography.titleSmall,
                    color = text,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    feature.descripcion,
                    style = MaterialTheme.typography.bodySmall,
                    color = textMuted,
                )
            }
        }
    }
}
