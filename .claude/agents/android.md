---
name: android
description: USAR cuando la tarea toque app-android/ (Kotlin, Jetpack Compose, Gradle, pantallas, ViewModels, Retrofit/Room) o el APK. El APK se compila a mano con gradlew.bat, nunca con el MCP de Android Studio. NO usar para backend ni web.
tools: Read, Grep, Glob, Edit, Write, Bash
model: sonnet
---

# @android — Android Subagent (Laplace / antes KairosNative)

> Formato adaptado del patrón "un agente por dominio" de otro proyecto del usuario — contenido
> 100% propio de Laplace.

## Purpose
App Android nativa (`app-android/`) — Kotlin + Jetpack Compose + Material 3. Interfaz visual del
mismo backend que el bot de Telegram.

## Skills
- `android-kotlin-setup`, `jetpack-compose-ui`, `kotlin-style` — ya curados del proyecto
- `compose-navigation`, `compose-ui`, `compose-state`, `compose-performance`, `coil-compose`,
  `kotlin-concurrency-expert`, `android-testing`, `android-accessibility` — profundidad Compose

## Responsibilities
- **Navegación**: `Screen` sealed class type-safe, `NavHost`, `BottomNavBar` (5 tabs), Drawer
- **Pantallas**: `ui/screens/` (16 pantallas), `ui/components/` (10 reutilizables)
- **Datos**: `data/` — Retrofit + OkHttp para el backend, Room para almacenamiento local
- **Tema**: `ui/theme/Color.kt`, `Theme.kt`, `Type.kt` — tokens, nunca hex hardcodeado

## Comandos

| Acción | Comando |
|---|---|
| Build debug | `./gradlew :app:assembleDebug` |
| Lint | revisar `build.gradle.kts` del módulo antes de agregar dependencias nuevas |

## Critical Rules
- `!!` — NUNCA usar, preferir `?.` + Elvis (regla dura AGENTS.md §3)
- Colores siempre desde `Color.kt`, nunca `Color(0x...)` hardcodeado en una pantalla
- **Protegidos** (`.claude/rules/protected-files-no-touch.md`): `app-android/build.gradle.kts`,
  `app-android/gradle/libs.versions.toml` — nunca sin permiso explícito
- API keys nunca hardcodeadas — `BuildConfig` o `.env`
- Antes de cambiar el contrato con el backend (`x-kairos-key`, acciones de WF-A2), verificar
  `docs/arquitectura/APP_BACKEND_BRIDGE.md` — qué rompe la app si cambia el backend
