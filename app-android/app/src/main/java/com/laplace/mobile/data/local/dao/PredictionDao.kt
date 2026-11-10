package com.laplace.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.laplace.mobile.data.local.entity.PredictionEntity

@Dao
interface PredictionDao {
    @Query("SELECT * FROM predictions WHERE matchId = :matchId")
    suspend fun getPrediction(matchId: String): PredictionEntity?

    @Query("SELECT * FROM predictions ORDER BY cachedAt DESC")
    suspend fun getAllPredictions(): List<PredictionEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(prediction: PredictionEntity)

    @Query("DELETE FROM predictions")
    suspend fun deleteAll()

    @Query("DELETE FROM predictions WHERE cachedAt < :cutoff")
    suspend fun deleteOlderThan(cutoff: Long)
}
