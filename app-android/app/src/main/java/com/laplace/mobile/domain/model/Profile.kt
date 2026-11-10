package com.laplace.mobile.domain.model

data class Profile(
    val nickname: String = "Invitado",
    val deviceId: String = "",
    val plan: String = "FREE",
    val totalPicks: Int = 0,
    val winRate: Int = 0,
    val streak: Int = 0,
    val hits: Int = 0,
    val misses: Int = 0,
)
