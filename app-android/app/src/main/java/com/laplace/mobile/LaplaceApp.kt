package com.laplace.mobile

import android.app.Application
import com.laplace.mobile.data.local.AppDatabase
import com.laplace.mobile.service.NotificationHelper
import com.laplace.mobile.service.PreloadScheduler

class LaplaceApp : Application() {
    lateinit var database: AppDatabase
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        database = AppDatabase.getInstance(this)
        NotificationHelper.createChannels(this)
        PreloadScheduler.schedule(this)
    }

    companion object {
        lateinit var instance: LaplaceApp
            private set
    }
}
