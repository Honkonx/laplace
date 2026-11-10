plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.compose.compiler)
    alias(libs.plugins.ksp)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.laplace.mobile"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.laplace.mobile"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    buildTypes.all {
        val apiKey = providers.gradleProperty("laplaceApiKey").getOrElse(System.getenv("LAPLACE_API_KEY") ?: "")
        val agentUrl = providers.gradleProperty("laplaceAgentUrl").getOrElse(System.getenv("LAPLACE_AGENT_URL") ?: "")
        val apiKeyLiteral = apiKey.replace("\\", "\\\\").replace("\"", "\\\"")
        val agentUrlLiteral = agentUrl.replace("\\", "\\\\").replace("\"", "\\\"")
        // URL del backend: sin dominio propio en el repo. Por defecto apunta al backend local visto desde el emulador de Android.
        val baseUrl = providers.gradleProperty("laplaceBaseUrl").getOrElse(System.getenv("LAPLACE_BASE_URL") ?: "http://10.0.2.2:9001/")
        val baseUrlLiteral = baseUrl.replace("\\", "\\\\").replace("\"", "\\\"")
        buildConfigField("String", "LAPLACE_BASE_URL", "\"$baseUrlLiteral\"")
        // Enlace de la comunidad (grupo de Telegram) que abre el banner; vacío = el botón queda inactivo.
        val communityUrl = providers.gradleProperty("laplaceCommunityUrl").getOrElse(System.getenv("LAPLACE_COMMUNITY_URL") ?: "")
        val communityUrlLiteral = communityUrl.replace("\\", "\\\\").replace("\"", "\\\"")
        buildConfigField("String", "LAPLACE_COMMUNITY_URL", "\"$communityUrlLiteral\"")
        buildConfigField("String", "LAPLACE_AUTH_KEY", "\"$apiKeyLiteral\"")
        buildConfigField("String", "LAPLACE_AGENT_URL", "\"$agentUrlLiteral\"")
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    implementation(libs.compose.navigation)

    implementation(libs.lifecycle.runtime.ktx)
    implementation(libs.lifecycle.viewmodel.compose)

    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.gson)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)

    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)

    implementation(libs.coil)
    implementation(libs.coil.network)
    implementation(libs.workmanager)
    implementation(libs.fcm)
    implementation(libs.markwon)
    implementation(libs.coroutines)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.security.crypto)
}
