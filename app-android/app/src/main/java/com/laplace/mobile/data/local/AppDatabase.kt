package com.laplace.mobile.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.laplace.mobile.data.local.dao.LogDao
import com.laplace.mobile.data.local.dao.MatchDao
import com.laplace.mobile.data.local.dao.PredictionDao
import com.laplace.mobile.data.local.dao.ProfileDao
import com.laplace.mobile.data.local.entity.LogEntity
import com.laplace.mobile.data.local.entity.MatchEntity
import com.laplace.mobile.data.local.entity.PredictionEntity
import com.laplace.mobile.data.local.entity.ProfileEntity

@Database(
    entities = [MatchEntity::class, PredictionEntity::class, ProfileEntity::class, LogEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun matchDao(): MatchDao
    abstract fun predictionDao(): PredictionDao
    abstract fun profileDao(): ProfileDao
    abstract fun logDao(): LogDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "laplace.db"
                ).build()
                INSTANCE = instance
                instance
            }
        }
    }
}
