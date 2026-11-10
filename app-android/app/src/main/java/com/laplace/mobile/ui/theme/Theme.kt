package com.laplace.mobile.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.graphics.Color
import com.laplace.mobile.data.local.PreferencesManager

private fun colorSchemeFor(palette: LaplacePalette, dark: Boolean) = if (dark) {
    darkColorScheme(
        primary = palette.accent, onPrimary = Color.White,
        primaryContainer = palette.accent.copy(alpha = 0.15f), onPrimaryContainer = palette.accent,
        secondary = palette.green, onSecondary = palette.text, tertiary = palette.cyan,
        background = palette.bg, onBackground = palette.text,
        surface = palette.surface, onSurface = palette.text,
        surfaceVariant = palette.surfaceLight, onSurfaceVariant = palette.textMuted,
        outline = palette.border, outlineVariant = palette.divider,
        error = palette.red, onError = palette.text,
    )
} else {
    lightColorScheme(
        primary = palette.accent, onPrimary = Color.White,
        primaryContainer = palette.accent.copy(alpha = 0.15f), onPrimaryContainer = palette.accent,
        secondary = palette.green, onSecondary = palette.text, tertiary = palette.cyan,
        background = palette.bg, onBackground = palette.text,
        surface = palette.surface, onSurface = palette.text,
        surfaceVariant = palette.surfaceLight, onSurfaceVariant = palette.textMuted,
        outline = palette.border, outlineVariant = palette.divider,
        error = palette.red, onError = palette.text,
    )
}

/** 3 temas reales — antes `ConfigThemeScreen` guardaba la preferencia pero ningún color la
 * seguía de verdad (todo era un solo `darkColorScheme` fijo). Ahora: se reasignan los `var` de
 * `Color.kt` (`aplicarPaleta`) ANTES de componer, y `key(mode)` fuerza que toda la app se vuelva
 * a componer desde cero cuando el tema cambia — así hasta los `Canvas`/helpers no-composable que
 * leen esos `var` directo (`ActivityGraph`, `Carousel`) quedan al día. */
@Composable
fun LaplaceTheme(content: @Composable () -> Unit) {
    val mode = PreferencesManager.themeMode
    val palette = when (mode) {
        "light" -> LightPalette
        "marino" -> MarinoPalette
        else -> DarkPalette
    }
    val isDark = palette !== LightPalette
    aplicarPaleta(palette)

    key(mode) {
        MaterialTheme(
            colorScheme = colorSchemeFor(palette, isDark),
            typography = LaplaceTypography,
            content = content,
        )
    }
}
