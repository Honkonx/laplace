package com.laplace.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.laplace.mobile.data.local.entity.MatchEntity

@Dao
interface MatchDao {
    @Query("SELECT * FROM matches WHERE date = :date ORDER BY hora ASC")
    suspend fun getMatchesByDate(date: String): List<MatchEntity>

    @Query("SELECT * FROM matches WHERE date = :date AND liga = :league ORDER BY hora ASC")
    suspend fun getMatchesByDateAndLeague(date: String, league: String): List<MatchEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(matches: List<MatchEntity>)

    @Query("DELETE FROM matches WHERE date < :cutoff")
    suspend fun deleteOlderThan(cutoff: String)

    @Query("DELETE FROM matches")
    suspend fun deleteAll()
}
