---
name: android-kotlin-setup
description: "Configuración y desarrollo de apps Android nativas con Kotlin + Gradle KTS. Activar cuando se trabaje en app-android/, Gradle, build.gradle.kts, version catalog, Room, Retrofit, WorkManager, o migración RN→Kotlin."
allowed-tools: [Read, Write, Edit, Bash]
---

# Android Kotlin Setup — Laplace Native

> Reglas para el proyecto nativo `app-android/`. La app (Laplace) es una rewrite 100% Kotlin de KairosApp (antes React Native/Expo; carpeta histórica `KairosNative/`, ya no existe — el código vive en `app-android/`).

---

## 1. Stack

| Capa | Tecnología | Versión |
|---|---|---|
| Lenguaje | Kotlin | 2.0.21 |
| Build | Gradle KTS + AGP | 8.7.3 |
| UI | Jetpack Compose + Material 3 | BOM 2024.12.01 |
| Navigation | Navigation Compose | 2.8.5 |
| HTTP | Retrofit 2 + OkHttp 4 | 2.11.0 / 4.12.0 |
| DB local | Room | 2.6.1 |
| Imágenes | Coil | 3.0.4 |
| Push | Firebase Cloud Messaging | 24.1.0 |
| Background | WorkManager | 2.9.1 |
| Markdown | Markwon | 4.6.2 |
| Coroutines | kotlinx-coroutines | 1.9.0 |
| DI | Manual (singletons) | — |

## 2. Estructura de proyecto

```
app-android/
├── app/
│   ├── src/main/
│   │   ├── java/com/laplace/mobile/
│   │   │   ├── LaplaceApp.kt          # Application()
│   │   │   ├── MainActivity.kt         # ComponentActivity()
│   │   │   ├── navigation/            # NavHost, Screen sealed class
│   │   │   ├── ui/theme/             # Color.kt, Theme.kt, Type.kt
│   │   │   ├── ui/screens/           # Screens por feature
│   │   │   ├── ui/components/        # Componentes reutilizables
│   │   │   ├── data/remote/          # Retrofit + DTOs
│   │   │   ├── data/local/           # Room DB + DAOs + entities
│   │   │   ├── data/repository/      # Repositorios
│   │   │   ├── domain/model/         # Modelos de dominio
│   │   │   ├── service/              # Services (notif, sync, preload)
│   │   │   └── util/                 # DateUtils, etc.
│   │   └── res/                      # drawable/, mipmap/, values/
│   └── build.gradle.kts
├── build.gradle.kts                  # Root
├── settings.gradle.kts               # Module includes
├── gradle.properties                 # AndroidX, Kotlin
├── gradle/libs.versions.toml         # Version catalog
└── gradle/wrapper/                   # Gradle wrapper
```

## 3. Reglas de Código

```kotlin
// ✅ Naming: camelCase sin prefijos
val deviceId: String = "..."

// ✅ Null safety: String? solo cuando es realmente nullable
fun getProfile(): Profile? { ... }

// ✅ State en Compose
@Composable
fun MyScreen() {
    var data by remember { mutableStateOf<List<Match>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    
    LaunchedEffect(Unit) {
        data = repository.getMatches()
        loading = false
    }
}

// ✅ ViewModel no obligatorio. Para screens simples usar state local.
// Para screens con lógica compartida: usar repository directamente (inyectado manual).
```

## 4. Equivalencias RN → Kotlin

| Concepto RN | Kotlin |
|---|---|
| `useState` | `remember { mutableStateOf(...) }` |
| `useEffect` | `LaunchedEffect` / `DisposableEffect` |
| `useCallback` | Llamar función directamente en callback |
| `useMemo` | `remember { ... }` |
| `useFocusEffect` | `DisposableEffect` + Lifecycle observer |
| `useRef` | `remember { mutableRefOf(...) }` |
| `useNavigation` | `val navController = LocalNavController.current` |
| `useRoute` | `val args: Screen.Args = backStackEntry.toRoute()` |
| `useTheme` | `LaplaceTheme { ... }` |
| `callN8n()` | `LaplaceApi.callWebhook(...)` via Retrofit |
| AsyncStorage | Room DAO / SharedPreferences |
| `setInterval` polling | WorkManager PeriodicWork |
| `AppState` listener | ProcessLifecycleOwner |

## 5. Configuración Gradle

```kotlin
// build.gradle.kts (app)
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.compose.compiler)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.laplace.mobile"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.laplace.mobile"
        minSdk = 24
        targetSdk = 36
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }
}
```

## 6. CI/CD (GitHub Actions)

```yaml
# .github/workflows/build-native.yml
# Gatillado en push a main con cambios en app-android/
# Build con Gradle, upload APK como artifact
```

## 7. Reglas para la IA (SIEMPRE)

- Usar `libs.versions.toml` para versiones — NUNCA hardcodear versiones en `build.gradle.kts`
- Room KSP (no KAPT) para generación de código
- Coil para todas las imágenes (AsyncImage), nunca ImageView manual
- Markwon para renderizado Markdown
- Navigation Compose type-safe (con `@Serializable` data class routes)
- Drawer + BottomNav + Stack en un solo NavHost
- Manual DI via companion object + Application class (sin Hilt/Dagger/Koin)
- `kebab-case` para recursos drawable (team-crest-arsenal.png)
- `camelCase` para todo el código Kotlin
- No usar `!!` — siempre usar `?.` + Elvis o `?:` o early return
- No hardcodear colors hex — usar tokens de `Color.kt`
