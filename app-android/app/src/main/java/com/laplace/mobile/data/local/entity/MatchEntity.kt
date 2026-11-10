package com.laplace.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "matches")
data class MatchEntity(
    @PrimaryKey val id: String,
    val local: String,
    val visitante: String,
    val liga: String,
    val hora: String,
    val status: String,
    val golLocal: String?,
    val golVisitante: String?,
    val date: String,
    val cachedAt: Long = System.currentTimeMillis(),
)
