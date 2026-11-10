package com.laplace.mobile.data.repository

import com.laplace.mobile.data.local.dao.PredictionDao
import com.laplace.mobile.data.local.entity.PredictionEntity
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.domain.model.Prediction
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class PredictionRepository(private val predictionDao: PredictionDao) {

    suspend fun getPrediction(matchId: String, date: String, forceRefresh: Boolean = false): Prediction? {
        if (!forceRefresh) {
            predictionDao.getPrediction(matchId)?.let { return it.toDomain() }
        }

        return try {
            val resp = LaplaceApi.service.callWebhook(
                WebhookRequest(
                    action = "prediccion",
                    params = mapOf("match_id" to matchId, "date" to date),
                    device_id = "",
                    timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date()),
                )
            )
            val data = resp.data
            val status = data?.get("status") as? String
            // Estados reales del backend (jobs_repo): pendiente | procesando | listo | error.
            if (status == "pendiente" || status == "procesando") return null

            val entity = PredictionEntity(
                matchId = matchId,
                local = data?.get("local") as? String ?: "",
                visitante = data?.get("visitante") as? String ?: "",
                pick = data?.get("pick") as? String ?: "",
                confianza = data?.get("confianza") as? String,
                analisis = data?.get("analisis") as? String ?: "",
                source = data?.get("source") as? String,
                status = data?.get("status") as? String,
                golLocal = data?.get("gol_local") as? String,
                golVisitante = data?.get("gol_visitante") as? String,
                fecha = date,
            )
            predictionDao.insert(entity)
            entity.toDomain()
        } catch (_: Exception) {
            null
        }
    }

    suspend fun getHistory(): List<Prediction> {
        return predictionDao.getAllPredictions().map { it.toDomain() }
    }

    private fun PredictionEntity.toDomain() = Prediction(
        matchId = matchId, local = local, visitante = visitante,
        pick = pick, confianza = confianza, analisis = analisis,
        source = source, status = status, golLocal = golLocal,
        golVisitante = golVisitante, fecha = fecha,
    )
}
