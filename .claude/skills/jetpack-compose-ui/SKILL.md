---
name: jetpack-compose-ui
description: "UI con Jetpack Compose + Material 3 para Laplace Native. Activar cuando se creen o modifiquen screens, componentes, animaciones, temas, o navegación Compose en app-android/."
allowed-tools: [Read, Write, Edit]
---

# Jetpack Compose UI — Laplace Native

> Reglas de UI para Laplace Native (`app-android/`, antes `KairosNative/`). El diseño debe replicar fielmente la app React Native existente (antes KairosApp; dark theme, colores, layout, animaciones).

---

## 1. Tokens de Color (desde `Color.kt`)

```kotlin
// Mapeo directo desde colors.js
val bg              = Color(0xFF0D0D14)  // Fondo pantallas
val surface         = Color(0xFF111827)  // Cards, botones
val surfaceLight    = Color(0xFF1A2236)  // MenuButton bg
val surfaceHover    = Color(0xFF1E2A42)  // Hover/pressed
val accent          = Color(0xFF6366F1)  // Indigo primario
val accentGlow      = Color(0x406366F1)  // Glow activos (rgba)
val green           = Color(0xFF10B981)  // Confianza ALTA
val orange          = Color(0xFFF59E0B)  // Confianza MEDIA
val red             = Color(0xFFEF4444)  // Confianza BAJA
val cyan            = Color(0xFF06B6D4)  // CustomMenu
val text            = Color(0xFFF1F5F9)  // Texto principal
val textMuted       = Color(0xFF94A3B8)  // Subtítulos
val textDim         = Color(0xFF64748B)  // Chevrons
val border          = Color(0xFF1E293B)  // Bordes
val divider         = Color(0x0AFFFFFF)  // Separadores (rgba)
```

## 2. Tema

```kotlin
@Composable
fun LaplaceTheme(content: @Composable () -> Unit) {
    val darkColorScheme = darkColorScheme(
        primary = accent,
        onPrimary = text,
        surface = surface,
        background = bg,
        error = red,
    )
    MaterialTheme(
        colorScheme = darkColorScheme,
        typography = LaplaceTypography,
        content = content,
    )
}
```

## 3. Layout — equivalencias RN

| RN | Compose |
|---|---|
| `<View>` | `Column` / `Row` / `Box` |
| `<ScrollView>` | `Column(verticalScroll(...))` |
| `<FlatList>` | `LazyColumn` |
| `<SectionList>` | `LazyColumn` + stickyHeader |
| `<Pressable>` | `Modifier.clickable` |
| `<TouchableOpacity>` | `Modifier.clickable { }` |
| `<Image>` | `AsyncImage(...)` (Coil) |
| `<Text>` | `Text(...)` |
| `<TextInput>` | `OutlinedTextField(...)` / `BasicTextField` |
| `<Modal>` | `ModalBottomSheet` |
| `<RefreshControl>` | `pullToRefresh` modifier |
| `<StatusBar>` | `SideEffect { ... }` |
| `<ActivityIndicator>` | `CircularProgressIndicator()` |

## 4. Animaciones — equivalencias RN

| RN Animated API | Compose Animation API |
|---|---|
| `new Animated.Value(0)` | `remember { Animatable(0f) }` |
| `Animated.timing(dest, 300)` | `animateTo(dest, animationSpec = tween(300))` |
| `Animated.spring(...)` | `animationSpec = spring(...)` |
| `Animated.loop({})` | `rememberInfiniteTransition { ... }` |
| `useNativeDriver: true` | Automático (Compose corre en GPU) |
| `Animated.View { opacity }` | `Modifier.graphicsLayer { alpha = value }` |
| `interpolate(input, output)` | `lerp(start, end, fraction)` |
| `useRef(new Animated.Value)` | `remember { Animatable(0f) }` |

```kotlin
// Ejemplo: fade + slide entrada (como HomeScreen)
@Composable
fun AnimatedEntry(
    delayMs: Int = 0,
    content: @Composable () -> Unit
) {
    val alpha = remember { Animatable(0f) }
    val offsetY = remember { Animatable(30f) }
    LaunchedEffect(Unit) {
        delay(delayMs.toLong())
        launch { alpha.animateTo(1f, tween(400)) }
        launch { offsetY.animateTo(0f, tween(400, easing = FastOutSlowInEasing)) }
    }
    Box(
        modifier = Modifier
            .graphicsLayer { alpha = alpha.value; translationY = offsetY.value }
    ) { content() }
}

// Ejemplo: pulse loop (como LoadingOverlay)
@Composable
fun PulseLoop() {
    val infiniteTransition = rememberInfiniteTransition()
    val scale by infiniteTransition.animateFloat(
        initialValue = 1f, targetValue = 1.1f,
        animationSpec = infiniteRepeatable(tween(750), RepeatMode.Reverse)
    )
    Box(Modifier.graphicsLayer { scaleX = scale; scaleY = scale })
}
```

## 5. Componentes compartidos

| Componente RN | Componente Compose | Notas |
|---|---|---|
| `TeamCrest` | `TeamCrest` | Coil AsyncImage + fallback initials |
| `MatchCard` | `MatchCard` | Row con equipos + hora + badge |
| `PredictionCard` | `PredictionCard` | Column con badge + pick + análisis |
| `LoadingOverlay` | `LoadingOverlay` | Box con pulse + bar slide |
| `BigButton` | `BigButton` | Surface clickable con icon + label |
| `DynamicButton` | `DynamicButton` | Row con icon + label + chevron |
| Carousel (Home) | `HorizontalPager` | Carrusel con auto-play |
| StatsTile (Home) | `StatsTile` | Card con label + valor |
| ActivityGraph (Profile) | `ActivityGraph` | Canvas columnas 30 días |
| PillBadge (Código/Plan) | `PillBadge` | Surface con color por plan |

## 6. Navegación

```kotlin
// Screen.kt — rutas type-safe
@Serializable sealed class Screen {
    @Serializable data object Home : Screen()
    @Serializable data class Prediction(val matchId: String, val date: String) : Screen()
    @Serializable data object Calendar : Screen()
    @Serializable data object TopPicks : Screen()
    @Serializable data object Stats : Screen()
    @Serializable data object Profile : Screen()
    // ...
}

// AppNavHost.kt
@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    ModalNavigationDrawer(drawerContent = { DrawerContent(navController) }) {
        Scaffold(bottomBar = { BottomNavBar(navController) }) { padding ->
            NavHost(navController, startDestination = Screen.Home, Modifier.padding(padding)) {
                composable<Screen.Home> { HomeScreen(navController) }
                composable<Screen.Prediction> { PredictionScreen(it.toRoute(), navController) }
                // ...
            }
        }
    }
}
```

## 7. Reglas para la IA (SIEMPRE)

- Replicar fielmente el layout de la app RN — medir espaciados, colores, tipografía
- Usar tokens de `Color.kt` — NUNCA hardcodear colores hex
- Animaciones con `AnimatedVisibility` + `animate*AsState` para casos simples
- `Animatable` + `animateTo` para control fino
- `rememberInfiniteTransition` para loops continuos
- `LazyColumn` para listas largas, `Column(verticalScroll)` para cortas
- Coil `AsyncImage` con placeholder + error fallback para escudos
- `pullToRefresh` para refresco manual
- `Modifier.clickable` (no Button component) para consistencia RN
- No usar `AnimatedVisibility` para animaciones secuenciales — usar `LaunchedEffect` + `Animatable`
