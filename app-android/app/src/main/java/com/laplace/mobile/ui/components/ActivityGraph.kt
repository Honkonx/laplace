package com.laplace.mobile.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.accentGlow
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim

@Composable
fun ActivityGraph(
    data: List<Int>,
    label: String = "Actividad (30 días)",
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .padding(16.dp),
    ) {
        Text(label, style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(12.dp))
        Canvas(
            modifier = Modifier.fillMaxWidth().height(120.dp),
        ) {
            if (data.isEmpty()) return@Canvas
            val maxVal = (data.maxOrNull() ?: 1).coerceAtLeast(1)
            val barWidth = size.width / data.size * 0.7f
            val gap = size.width / data.size * 0.3f

            data.forEachIndexed { index, value ->
                val barHeight = (value.toFloat() / maxVal) * size.height
                val x = index * (barWidth + gap)
                drawRoundRect(
                    color = accent.copy(alpha = 0.6f),
                    topLeft = Offset(x, size.height - barHeight),
                    size = Size(barWidth, barHeight),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(2f, 2f),
                )
            }
        }
    }
}
