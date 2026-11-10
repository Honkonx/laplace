package com.laplace.mobile.ui.components

import android.content.Intent
import android.net.Uri
import com.laplace.mobile.BuildConfig
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import coil3.request.crossfade
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import coil3.compose.AsyncImage
import coil3.request.CachePolicy
import coil3.request.ImageRequest
import com.laplace.mobile.R
import com.laplace.mobile.ui.theme.*
import kotlinx.coroutines.delay

private val BANNER_IDS = listOf(
    R.drawable.banner_laplace,
    R.drawable.banner_estadio,
    R.drawable.banner_balon,
)

@Composable
fun BannerCarousel(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    var currentIndex by remember { mutableStateOf(0) }
    var isResumed by remember { mutableStateOf(true) }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            isResumed = event == Lifecycle.Event.ON_RESUME
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    LaunchedEffect(isResumed) {
        if (!isResumed) return@LaunchedEffect
        while (true) {
            delay(3000)
            currentIndex = (currentIndex + 1) % BANNER_IDS.size
        }
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(160.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(surface),
    ) {
        AnimatedContent(
            targetState = currentIndex,
            transitionSpec = {
                fadeIn(tween(300)) togetherWith fadeOut(tween(300))
            },
            label = "banner",
        ) { index ->
            AsyncImage(
                model = ImageRequest.Builder(context)
                    .data(BANNER_IDS[index])
                    .memoryCachePolicy(CachePolicy.ENABLED)
                    .diskCachePolicy(CachePolicy.DISABLED)
                    .crossfade(true)
                    .build(),
                contentDescription = "Banner",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(14.dp),
        ) {
            Text(
                "Laplace",
                style = MaterialTheme.typography.titleMedium,
                color = text,
                fontWeight = FontWeight.Bold,
            )
        }

        Box(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 14.dp, bottom = 10.dp)
                .size(36.dp)
                .clip(CircleShape)
                .background(accent)
                .clickable(enabled = BuildConfig.LAPLACE_COMMUNITY_URL.isNotBlank()) {
                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(BuildConfig.LAPLACE_COMMUNITY_URL))
                    context.startActivity(intent)
                },
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "T",
                color = text,
                fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.labelLarge,
            )
        }

        Row(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            BANNER_IDS.indices.forEach { i ->
                Box(
                    modifier = Modifier
                        .size(if (i == currentIndex) 8.dp else 6.dp)
                        .clip(CircleShape)
                        .background(if (i == currentIndex) accent else textDim.copy(alpha = 0.5f)),
                )
            }
        }
    }
}
