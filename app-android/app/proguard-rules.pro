# Laplace ProGuard Rules

# Keep Retrofit interfaces
-keep,allowobfuscation interface com.laplace.mobile.data.remote.** { *; }

# Keep Room entities
-keep class com.laplace.mobile.data.local.entity.** { *; }

# Keep domain models
-keep class com.laplace.mobile.domain.model.** { *; }

# Keep DTOs
-keep class com.laplace.mobile.data.remote.dto.** { *; }

# Keep WebhookRequest/Response (used by Retrofit)
-keep class com.laplace.mobile.data.remote.WebhookRequest { *; }
-keep class com.laplace.mobile.data.remote.WebhookResponse { *; }

# Keep Gson serialized classes
-keepattributes Signature
-keepattributes *Annotation*
-keep class com.google.gson.** { *; }

# Keep Kotlin Serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

# Keep Coil
-keep class coil.** { *; }

# Keep FCM
-keep class com.google.firebase.** { *; }
-dontwarn com.google.firebase.**

# Keep WorkManager
-keep class androidx.work.** { *; }

# Remove debug logging
-assumenosideeffects class android.util.Log {
    public static boolean isLoggable(java.lang.String, int);
    public static int v(...);
    public static int d(...);
    public static int i(...);
}
