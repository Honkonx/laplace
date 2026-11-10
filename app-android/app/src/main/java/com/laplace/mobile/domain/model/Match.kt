package com.laplace.mobile.domain.model

data class Match(
    val id: String = "",
    val local: String = "",
    val visitante: String = "",
    val liga: String = "",
    val hora: String = "",
    val status: String = "",
    val golLocal: String? = null,
    val golVisitante: String? = null,
    val date: String = "",
)
