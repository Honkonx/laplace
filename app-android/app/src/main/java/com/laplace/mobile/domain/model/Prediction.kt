package com.laplace.mobile.domain.model

data class Prediction(
    val matchId: String = "",
    val local: String = "",
    val visitante: String = "",
    val pick: String = "",
    val confianza: String? = null,
    val analisis: String = "",
    val source: String? = null,
    val status: String? = null,
    val golLocal: String? = null,
    val golVisitante: String? = null,
    val fecha: String = "",
)
