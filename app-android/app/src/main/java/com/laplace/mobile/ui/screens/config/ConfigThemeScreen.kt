package com.laplace.mobile.ui.screens.config

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.ui.theme.*

private data class ThemeOption(val label: String, val preview: Color, val key: String)

private val themeOptions = listOf(
    ThemeOption("Oscuro", Color(0xFF0D0D14), "dark"),
    ThemeOption("Claro", Color(0xFFF2F3F8), "light"),
    ThemeOption("Marino", Color(0xFF081A33), "marino"),
)

@Composable
fun ConfigThemeScreen(navController: NavController) {
    // Leer directo de PreferencesManager (ahora reactivo, ver PreferencesManager.kt) — el
    // cambio se aplica al instante en toda la app vía LaplaceTheme, no hace falta reiniciar.
    val selected = PreferencesManager.themeMode

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .padding(20.dp),
    ) {
        Spacer(Modifier.height(48.dp))
        Text("Configurar Tema", style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(24.dp))
        Text("Selecciona un tema:", style = MaterialTheme.typography.bodyMedium, color = textMuted)
        Spacer(Modifier.height(16.dp))

        themeOptions.forEach { option ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .clickable {
                        PreferencesManager.themeMode = option.key
                    }
                    .padding(vertical = 14.dp, horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(24.dp)
                        .clip(CircleShape)
                        .background(option.preview),
                )
                Spacer(Modifier.width(14.dp))
                Text(
                    option.label,
                    style = MaterialTheme.typography.bodyLarge,
                    color = text,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.weight(1f),
                )
                if (selected == option.key) {
                    Box(
                        modifier = Modifier
                            .size(22.dp)
                            .clip(CircleShape)
                            .background(accent),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("\u2713", color = text, fontSize = MaterialTheme.typography.labelSmall.fontSize)
                    }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
        Text("Tema actual: ${themeOptions.find { it.key == selected }?.label ?: selected}", style = MaterialTheme.typography.bodySmall, color = textDim)
    }
}
