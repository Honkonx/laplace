package com.laplace.mobile.data.remote.dto

import com.google.gson.annotations.SerializedName

data class WebhookResponseDto(
    val type: String?,
    val title: String?,
    val data: Map<String, Any?>?,
    val buttons: List<Map<String, Any?>>?,
)
