package com.laplace.mobile.service

import android.content.Context
import androidx.work.*
import androidx.work.CoroutineWorker
import com.laplace.mobile.LaplaceApp
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        return try {
            val date = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            val resp = LaplaceApi.service.callWebhook(
                WebhookRequest(
                    action = "juegos",
                    params = mapOf("date" to date),
                    device_id = "laplace-sync",
                    timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date()),
                )
            )
            val raw = resp.data?.get("partidos") as? List<*>
            val matches = raw?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
            val db = (applicationContext as LaplaceApp).database
            val entities = matches.map {
                com.laplace.mobile.data.local.entity.MatchEntity(
                    id = it["id"]?.toString() ?: "",
                    local = it["local"] as? String ?: "",
                    visitante = it["visitante"] as? String ?: "",
                    liga = it["liga"] as? String ?: "",
                    hora = it["hora"] as? String ?: "",
                    status = it["status"] as? String ?: "",
                    golLocal = it["gol_local"] as? String,
                    golVisitante = it["gol_visitante"] as? String,
                    date = date,
                )
            }
            db.matchDao().deleteOlderThan(date)
            db.matchDao().insertAll(entities)
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

object SyncScheduler {
    private const val WORK_NAME = "laplace_sync"

    fun schedule(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val request = PeriodicWorkRequestBuilder<SyncWorker>(2, TimeUnit.HOURS)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
    }
}
