package com.laplace.mobile.navigation

import kotlinx.serialization.Serializable

@Serializable sealed class Screen {
    @Serializable data object Home : Screen()
    @Serializable data object Calendar : Screen()
    @Serializable data object TopPicks : Screen()
    @Serializable data object Stats : Screen()
    @Serializable data object Profile : Screen()
    @Serializable data object Agent : Screen()
    @Serializable data class Leagues(val date: String) : Screen()
    @Serializable data class Matches(val date: String, val league: String) : Screen()
    // local/visitante/liga son opcionales: con ellos la pantalla pide el desglose del consenso
    // (`POST /api/v1/prediccion-web`); sin ellos muestra solo el resultado del job.
    @Serializable data class Prediction(
        val matchId: String,
        val date: String,
        val local: String = "",
        val visitante: String = "",
        val liga: String = "",
    ) : Screen()
    @Serializable data object History : Screen()
    @Serializable data object CodigoActivacion : Screen()
    @Serializable data object Upgrade : Screen()
    @Serializable data object ConfigTheme : Screen()
    @Serializable data object Log : Screen()
    @Serializable data object About : Screen()
    @Serializable data object Onboarding : Screen()
    @Serializable data object Registro : Screen()
    @Serializable data object NotificationPermission : Screen()
    @Serializable data object SportsMenu : Screen()
}
