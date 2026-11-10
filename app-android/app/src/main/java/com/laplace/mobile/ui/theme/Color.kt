package com.laplace.mobile.ui.theme

import androidx.compose.ui.graphics.Color

/** Paleta completa de un tema — oscuro/claro/marino comparten esta misma forma, ver
 * `Theme.kt::LaplaceTheme` para cómo se elige cuál está activa. */
data class LaplacePalette(
    val bg: Color,
    val surface: Color,
    val surfaceLight: Color,
    val surfaceHover: Color,
    val accent: Color,
    val accentGlow: Color,
    val green: Color,
    val orange: Color,
    val red: Color,
    val cyan: Color,
    val text: Color,
    val textMuted: Color,
    val textDim: Color,
    val border: Color,
    val divider: Color,
)

// Tokens exactos desde LaplaceApp/src/theme/colors.js — tema original, sin cambios.
val DarkPalette = LaplacePalette(
    bg = Color(0xFF0D0D14), surface = Color(0xFF111827), surfaceLight = Color(0xFF1A2236),
    surfaceHover = Color(0xFF1E2A42), accent = Color(0xFF6366F1), accentGlow = Color(0x406366F1),
    green = Color(0xFF10B981), orange = Color(0xFFF59E0B), red = Color(0xFFEF4444),
    cyan = Color(0xFF06B6D4), text = Color(0xFFF1F5F9), textMuted = Color(0xFF94A3B8),
    textDim = Color(0xFF64748B), border = Color(0xFF1E293B), divider = Color(0x0AFFFFFF),
)

// Tema claro nuevo — 2026-09-08, mismo acento de marca (índigo), neutros invertidos.
val LightPalette = LaplacePalette(
    bg = Color(0xFFF2F3F8), surface = Color(0xFFFFFFFF), surfaceLight = Color(0xFFE9EBF5),
    surfaceHover = Color(0xFFDDE0F0), accent = Color(0xFF5457E5), accentGlow = Color(0x265457E5),
    green = Color(0xFF059669), orange = Color(0xFFD97706), red = Color(0xFFDC2626),
    cyan = Color(0xFF0D9488), text = Color(0xFF15161F), textMuted = Color(0xFF6B6E80),
    textDim = Color(0xFF9EA1B0), border = Color(0xFFE3E4EF), divider = Color(0x0F000000),
)

// Tema marino nuevo — 2026-09-08, estética de transmisión nocturna de fútbol (mismo espíritu
// que el mockup "Nuevos Bocetos Kairos" — bocetos-kairos-v2.html).
val MarinoPalette = LaplacePalette(
    bg = Color(0xFF081A33), surface = Color(0xFF0F2647), surfaceLight = Color(0xFF163360),
    surfaceHover = Color(0xFF1C3D73), accent = Color(0xFF7C93FF), accentGlow = Color(0x407C93FF),
    green = Color(0xFF34D399), orange = Color(0xFFFBBF24), red = Color(0xFFFB7185),
    cyan = Color(0xFF3FE0CE), text = Color(0xFFEAF2FF), textMuted = Color(0xFF93ABD1),
    textDim = Color(0xFF5C79A6), border = Color(0x1FFFFFFF), divider = Color(0x0AFFFFFF),
)

/** Tokens globales — quedan como `var` de nivel de archivo (mismo nombre que siempre, así los
 * ~25 archivos que ya hacen `import com.laplace.mobile.ui.theme.*` y usan `bg`, `surface`, etc.
 * directo no necesitan tocarse). `LaplaceTheme` reasigna estos valores al elegir tema y fuerza
 * una recomposición completa (`key(themeMode)`) para que se vean reflejados.
 *
 * Se decidió esto en vez de `@Composable get()` sobre un `CompositionLocal` (que sería más
 * "correcto" en teoría) porque varios usos reales ya existentes rompían con eso: `Canvas { ... }`
 * en `ActivityGraph`/`Carousel` no es un contexto `@Composable`, y `LaplaceTypography` (Type.kt)
 * es un `val` de nivel de archivo evaluado una sola vez, no dentro de una función `@Composable`.
 * Limitación conocida y aceptada: los `TextStyle.color` de `LaplaceTypography` quedan fijos al
 * tema activo quando se carga la app — solo afecta a los `Text(...)` que NO pasan `color=`
 * explícito (la gran mayoría de las pantallas sí lo hace). */
var bg: Color = DarkPalette.bg
var surface: Color = DarkPalette.surface
var surfaceLight: Color = DarkPalette.surfaceLight
var surfaceHover: Color = DarkPalette.surfaceHover
var accent: Color = DarkPalette.accent
var accentGlow: Color = DarkPalette.accentGlow
var green: Color = DarkPalette.green
var orange: Color = DarkPalette.orange
var red: Color = DarkPalette.red
var cyan: Color = DarkPalette.cyan
var text: Color = DarkPalette.text
var textMuted: Color = DarkPalette.textMuted
var textDim: Color = DarkPalette.textDim
var border: Color = DarkPalette.border
var divider: Color = DarkPalette.divider

fun aplicarPaleta(p: LaplacePalette) {
    bg = p.bg; surface = p.surface; surfaceLight = p.surfaceLight; surfaceHover = p.surfaceHover
    accent = p.accent; accentGlow = p.accentGlow; green = p.green; orange = p.orange; red = p.red
    cyan = p.cyan; text = p.text; textMuted = p.textMuted; textDim = p.textDim
    border = p.border; divider = p.divider
}
