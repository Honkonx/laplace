package com.laplace.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "predictions")
data class PredictionEntity(
    @PrimaryKey val matchId: String,
    val local: String,
    val visitante: String,
    val pick: String,
    val confianza: String?,
    val analisis: String,
    val source: String?,
    val status: String?,
    val golLocal: String?,
    val golVisitante: String?,
    val fecha: String,
    val cachedAt: Long = System.currentTimeMillis(),
)
