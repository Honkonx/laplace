package com.laplace.mobile.data.repository

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.laplace.mobile.data.local.dao.ProfileDao
import com.laplace.mobile.data.local.entity.ProfileEntity
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.data.remote.WebhookRequest
import com.laplace.mobile.domain.model.Profile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class ProfileRepository(context: Context, private val profileDao: ProfileDao) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context, "laplace_secure", masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun getDeviceId(): String {
        val authId = com.laplace.mobile.data.local.AuthManager.deviceId
            ?: com.laplace.mobile.data.local.AuthManager. token?.let { com.laplace.mobile.data.local.AuthManager.resolveDeviceId() }
        if (!authId.isNullOrBlank() && authId != "laplace") {
            return authId
        }
        var id = prefs.getString("device_id", null)
        if (id == null) {
            id = "laplace_${System.currentTimeMillis().toString(36)}_${(10000000..99999999).random()}"
            prefs.edit().putString("device_id", id).apply()
        }
        return id
    }

    fun getNickname(): String? = prefs.getString("nickname", null)

    fun saveNickname(nickname: String) {
        prefs.edit().putString("nickname", nickname).apply()
    }

    suspend fun getStats(): Profile {
        val cached = profileDao.getProfile()
        val profile = cached?.toDomain() ?: Profile(deviceId = getDeviceId())

        return try {
            val resp = LaplaceApi.service.callWebhook(
                WebhookRequest(
                    action = "stats",
                    params = emptyMap(),
                    device_id = getDeviceId(),
                    timestamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date()),
                )
            )
            val data = resp.data ?: return profile
            val entity = ProfileEntity(
                nickname = getNickname() ?: (data["nickname"] as? String ?: profile.nickname),
                plan = data["plan"] as? String ?: profile.plan,
                totalPicks = (data["total_picks"] as? String)?.toIntOrNull() ?: profile.totalPicks,
                winRate = (data["win_rate"] as? String)?.removeSuffix("%")?.toIntOrNull() ?: profile.winRate,
                streak = (data["streak"] as? String)?.toIntOrNull() ?: profile.streak,
                hits = (data["hits"] as? String)?.toIntOrNull() ?: profile.hits,
                misses = (data["misses"] as? String)?.toIntOrNull() ?: profile.misses,
            )
            profileDao.insert(entity)
            entity.toDomain()
        } catch (_: Exception) {
            profile
        }
    }

    private fun ProfileEntity.toDomain() = Profile(
        nickname = nickname, deviceId = getDeviceId(), plan = plan,
        totalPicks = totalPicks, winRate = winRate, streak = streak,
        hits = hits, misses = misses,
    )
}
