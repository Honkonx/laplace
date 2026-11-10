package com.laplace.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "profile")
data class ProfileEntity(
    @PrimaryKey val key: String = "main",
    val nickname: String = "Invitado",
    val plan: String = "FREE",
    val totalPicks: Int = 0,
    val winRate: Int = 0,
    val streak: Int = 0,
    val hits: Int = 0,
    val misses: Int = 0,
    val updatedAt: Long = System.currentTimeMillis(),
)
