package com.laplace.mobile.domain.model

data class LogEntry(
    val id: Long = 0,
    val action: String = "",
    val status: Int = 0,
    val elapsed: Long = 0,
    val timestamp: String = "",
    val response: String = "",
)
