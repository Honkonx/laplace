package com.laplace.mobile.ui.screens.upgrade

import com.laplace.mobile.BuildConfig
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.orange
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted

data class PlanFeature(val label: String, val included: Boolean)

@Composable
fun UpgradeScreen(navController: NavController) {
    val uriHandler = LocalUriHandler.current

    val freeFeatures = listOf(
        PlanFeature("1 predicción diaria", true),
        PlanFeature("Estadísticas básicas", true),
        PlanFeature("Acceso a calendario", true),
        PlanFeature("Historial de 7 días", true),
        PlanFeature("Análisis avanzado IA", false),
        PlanFeature("Top 3 Picks diarios", false),
        PlanFeature("Alertas en vivo", false),
        PlanFeature("Soporte prioritario", false),
    )

    val proFeatures = listOf(
        PlanFeature("Predicciones ilimitadas", true),
        PlanFeature("Estadísticas avanzadas", true),
        PlanFeature("Acceso a calendario", true),
        PlanFeature("Historial completo", true),
        PlanFeature("Análisis avanzado IA", true),
        PlanFeature("Top 3 Picks diarios", true),
        PlanFeature("Alertas en vivo", true),
        PlanFeature("Soporte prioritario", true),
    )

    Box(Modifier.fillMaxSize().background(bg)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Text("Mejorar Plan", style = MaterialTheme.typography.headlineLarge, color = text)
            Spacer(Modifier.height(4.dp))
            Text(
                "Elige el plan que mejor se adapte a ti",
                style = MaterialTheme.typography.bodyMedium,
                color = textMuted,
            )

            Spacer(Modifier.height(24.dp))

            PlanCard(
                title = "FREE",
                price = "Gratis",
                isCurrent = true,
                features = freeFeatures,
                badgeColor = orange,
                buttonLabel = "Plan Actual",
                onClick = {},
            )

            Spacer(Modifier.height(16.dp))

            PlanCard(
                title = "PRO",
                price = "Premium",
                isCurrent = false,
                features = proFeatures,
                badgeColor = accent,
                buttonLabel = "Contactar para Upgrade",
                onClick = { if (BuildConfig.LAPLACE_COMMUNITY_URL.isNotBlank()) uriHandler.openUri(BuildConfig.LAPLACE_COMMUNITY_URL) },  // el enlace se configura al compilar (laplaceCommunityUrl); vacío = no hace nada
            )

            Spacer(Modifier.height(16.dp))

            PlanCard(
                title = "MAX",
                price = "VIP",
                isCurrent = false,
                features = proFeatures,
                badgeColor = green,
                buttonLabel = "Contactar para Upgrade",
                onClick = { if (BuildConfig.LAPLACE_COMMUNITY_URL.isNotBlank()) uriHandler.openUri(BuildConfig.LAPLACE_COMMUNITY_URL) },  // el enlace se configura al compilar (laplaceCommunityUrl); vacío = no hace nada
            )
        }
    }
}

@Composable
private fun PlanCard(
    title: String,
    price: String,
    isCurrent: Boolean,
    features: List<PlanFeature>,
    badgeColor: androidx.compose.ui.graphics.Color,
    buttonLabel: String,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .padding(20.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineMedium, color = text, fontWeight = FontWeight.Bold)
            Spacer(Modifier.width(10.dp))
            if (isCurrent) {
                Text(
                    "ACTUAL",
                    style = MaterialTheme.typography.labelSmall,
                    color = orange,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(orange.copy(alpha = 0.15f))
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
        }
        Text(price, style = MaterialTheme.typography.bodyMedium, color = textMuted)
        Spacer(Modifier.height(16.dp))

        features.forEach { feature ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(vertical = 4.dp),
            ) {
                val checkColor = if (feature.included) green else textDim
                Text(
                    if (feature.included) "✓" else "○",
                    color = checkColor,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    feature.label,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (feature.included) text else textDim,
                )
            }
        }

        Spacer(Modifier.height(20.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(badgeColor)
                .padding(vertical = 14.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                buttonLabel,
                color = text,
                fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
            )
        }
    }
}
