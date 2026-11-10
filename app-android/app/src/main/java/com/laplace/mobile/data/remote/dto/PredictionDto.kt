package com.laplace.mobile.data.remote.dto

data class PredictionDto(
    val matchId: String?,
    val local: String?,
    val visitante: String?,
    val pick: String?,
    val confianza: String?,
    val analisis: String?,
    val source: String?,
    val status: String?,
    val golLocal: String?,
    val golVisitante: String?,
    val fecha: String?,
)
