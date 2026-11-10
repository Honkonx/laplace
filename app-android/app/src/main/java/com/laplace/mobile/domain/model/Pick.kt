package com.laplace.mobile.domain.model

data class Pick(
    val id: String = "",
    val local: String = "",
    val visitante: String = "",
    val prediction: String = "",
    val confianza: String? = null,
    val date: String = "",
    val league: String = "",
)
