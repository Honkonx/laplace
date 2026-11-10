package com.laplace.mobile.ui.screens.sports

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.ui.theme.*

private class Sport(val icon: String, val name: String, val subtitle: String)

@Composable
fun SportsMenuScreen(navController: NavController) {
    val sports = listOf(
        Sport("⚽", "Fútbol", "Ligas, predicciones y estadísticas"),
        Sport("🏀", "Basketball", "NBA, Euroliga y más"),
        Sport("⚾", "Béisbol", "MLB, LVBP"),
        Sport("🎾", "Tenis", "ATP, WTA, Grand Slams"),
    )

    Column(
        modifier = Modifier.fillMaxSize().background(bg).padding(20.dp),
    ) {
        Spacer(Modifier.height(48.dp))
        Text("Deportes", style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text("Selecciona un deporte para ver análisis", style = MaterialTheme.typography.bodyMedium, color = textMuted)
        Spacer(Modifier.height(24.dp))

        sports.forEach { sport ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 6.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(surface)
                    .clickable { }
                    .padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier.size(48.dp).clip(CircleShape).background(surfaceLight),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(sport.icon, style = MaterialTheme.typography.titleLarge)
                }
                Spacer(Modifier.width(14.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(sport.name, style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
                    Text(sport.subtitle, style = MaterialTheme.typography.bodySmall, color = textMuted)
                }
                Text("›", style = MaterialTheme.typography.titleLarge, color = textDim)
            }
        }
    }
}
