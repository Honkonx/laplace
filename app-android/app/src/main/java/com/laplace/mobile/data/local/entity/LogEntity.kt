package com.laplace.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "logs")
data class LogEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val action: String,
    val status: Int,
    val elapsed: Long,
    val timestamp: String,
    val response: String = "",
)
