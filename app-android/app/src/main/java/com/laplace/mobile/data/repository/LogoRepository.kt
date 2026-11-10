package com.laplace.mobile.data.repository

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

object LogoRepository {
    private const val PREFS_NAME = "logo_cache"
    private const val BASE_DIR = "logos"

    private var prefs: SharedPreferences? = null
    private var baseDir: File? = null

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    fun init(context: Context) {
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        baseDir = File(context.filesDir, BASE_DIR)
        baseDir?.mkdirs()
        File(baseDir, "teams").mkdirs()
        File(baseDir, "leagues").mkdirs()
    }

    private fun getLocalPath(subdir: String, slug: String): File? {
        val dir = baseDir?.let { File(it, subdir) } ?: return null
        val file = File(dir, "${slug}.png")
        return if (file.exists()) file else null
    }

    fun getCachedPath(slug: String, league: Boolean = false): String? {
        val subdir = if (league) "leagues" else "teams"
        return getLocalPath(subdir, slug)?.absolutePath
    }

    suspend fun sync(slugs: Map<String, String>, league: Boolean = false) = withContext(Dispatchers.IO) {
        val subdir = if (league) "leagues" else "teams"
        slugs.forEach { (slug, url) ->
            val cachedUrl = prefs?.getString("url_${subdir}_$slug", null)
            if (cachedUrl == url) {
                val local = getLocalPath(subdir, slug)
                if (local != null) return@forEach
            }
            downloadLogo(slug, url, subdir)
        }
    }

    private fun downloadLogo(slug: String, url: String, subdir: String) {
        try {
            val request = Request.Builder().url(url).build()
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return

            val dir = baseDir?.let { File(it, subdir) } ?: return
            dir.mkdirs()
            val file = File(dir, "${slug}.png")
            response.body?.byteStream()?.use { input ->
                file.outputStream().use { output ->
                    input.copyTo(output)
                }
            }
            prefs?.edit()
                ?.putString("url_${subdir}_$slug", url)
                ?.apply()
        } catch (_: Exception) {}
    }

    fun clearCache() {
        baseDir?.deleteRecursively()
        baseDir?.mkdirs()
        prefs?.edit()?.clear()?.apply()
    }
}
