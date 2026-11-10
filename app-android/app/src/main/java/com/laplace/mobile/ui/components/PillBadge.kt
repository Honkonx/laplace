package com.laplace.mobile.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.orange

@Composable
fun PillBadge(
    text: String,
    plan: String = "FREE",
    modifier: Modifier = Modifier,
) {
    val color = when (plan.uppercase()) {
        "PRO" -> accent
        "MAX" -> green
        else -> orange
    }

    Text(
        text = text,
        color = color,
        fontWeight = FontWeight.Bold,
        style = MaterialTheme.typography.labelLarge,
        modifier = modifier
            .clip(RoundedCornerShape(20.dp))
            .background(color.copy(alpha = 0.15f))
            .padding(horizontal = 16.dp, vertical = 6.dp),
    )
}
