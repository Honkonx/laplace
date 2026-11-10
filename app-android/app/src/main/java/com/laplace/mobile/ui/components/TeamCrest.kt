package com.laplace.mobile.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import coil3.request.CachePolicy
import coil3.request.ImageRequest
import coil3.request.crossfade
import com.laplace.mobile.data.repository.LogoRepository
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import java.io.File

@Composable
fun TeamCrest(
    teamName: String,
    size: Dp = 40.dp,
    modifier: Modifier = Modifier,
    league: Boolean = false,
    logoUrl: String? = null,
) {
    val context = LocalContext.current
    val prefix = if (league) "league_" else "team_"
    val slug = teamName.lowercase().replace(" ", "_").replace(".", "")

    val cachedPath = LogoRepository.getCachedPath(slug, league)
    val drawableResId = context.resources.getIdentifier("$prefix$slug", "drawable", context.packageName)

    val imageUri: Any? = when {
        logoUrl != null -> logoUrl
        cachedPath != null -> File(cachedPath)
        drawableResId != 0 -> drawableResId
        else -> null
    }

    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .background(surfaceLight),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = teamName.take(2).uppercase(),
            color = text.copy(alpha = 0.4f),
            fontWeight = FontWeight.Bold,
        )
        if (imageUri != null) {
            AsyncImage(
                model = ImageRequest.Builder(context)
                    .data(imageUri)
                    .memoryCachePolicy(CachePolicy.ENABLED)
                    .diskCachePolicy(CachePolicy.ENABLED)
                    .crossfade(true)
                    .build(),
                contentDescription = teamName,
                modifier = Modifier.size(size).clip(CircleShape),
                contentScale = ContentScale.Fit,
            )
        }
    }
}
