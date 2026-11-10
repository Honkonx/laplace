package com.laplace.mobile.data.repository

import com.laplace.mobile.data.local.dao.MatchDao
import com.laplace.mobile.data.local.entity.MatchEntity
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.domain.model.Match
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MatchRepository(private val matchDao: MatchDao) {

    suspend fun getMatches(date: String): List<Match> {
        val cached = matchDao.getMatchesByDate(date)
        if (cached.isNotEmpty()) {
            return cached.map { it.toDomain() }
        }

        return try {
            val resp = LaplaceApi.service.callWebhook(
                WebhookRequest(
                    action = "juegos",
                    params = mapOf("date" to date),
                    device_id = "",
                    timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date()),
                )
            )
            val raw = resp.data?.get("partidos") as? List<*>
            val items = raw?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
            val entities = items.map { it.toEntity(date) }
            matchDao.deleteOlderThan(date)
            matchDao.insertAll(entities)
            entities.map { it.toDomain() }
        } catch (_: Exception) {
            emptyList()
        }
    }

    suspend fun getMatchesByLeague(date: String, league: String): List<Match> {
        return matchDao.getMatchesByDateAndLeague(date, league).map { it.toDomain() }
    }

    private fun Map<String, Any?>.toEntity(date: String) = MatchEntity(
        id = this["id"]?.toString() ?: "",
        local = this["local"] as? String ?: "",
        visitante = this["visitante"] as? String ?: "",
        liga = this["liga"] as? String ?: "",
        hora = this["hora"] as? String ?: "",
        status = this["status"] as? String ?: "",
        golLocal = this["gol_local"] as? String,
        golVisitante = this["gol_visitante"] as? String,
        date = date,
    )

    private fun MatchEntity.toDomain() = Match(
        id = id, local = local, visitante = visitante, liga = liga,
        hora = hora, status = status, golLocal = golLocal,
        golVisitante = golVisitante, date = date,
    )
}
