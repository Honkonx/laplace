package com.laplace.mobile.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.laplace.mobile.MainActivity
import com.laplace.mobile.R

object NotificationHelper {
    private const val CHANNEL_PICKS = "laplace_picks"
    private const val CHANNEL_MATCHES = "laplace_matches"
    private const val CHANNEL_SYSTEM = "laplace_system"

    fun createChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_PICKS, "Top Picks", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Mejores predicciones del día"
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_MATCHES, "Partidos", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Notificaciones de partidos en vivo y resultados"
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_SYSTEM, "Sistema", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Notificaciones del sistema Laplace"
            }
        )
    }

    fun showPickNotification(context: Context, title: String, message: String) {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_PICKS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()

        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(System.currentTimeMillis().toInt(), notification)
    }

    fun showMatchNotification(context: Context, title: String, message: String) {
        val notification = NotificationCompat.Builder(context, CHANNEL_MATCHES)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .build()

        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(System.currentTimeMillis().toInt(), notification)
    }
}
