package com.laplace.mobile.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.border
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted

@Composable
fun MatchCard(
    localName: String,
    visitanteName: String,
    hora: String,
    scoreLocal: String? = null,
    scoreVisitante: String? = null,
    status: String? = null,
    /** El bot tiene histórico de estos equipos: se marca con ✔ para ofrecerlo primero. */
    pronosticable: Boolean = false,
    onClick: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    val isLive = status == "live" || status == "en_vivo"
    val isFinal = status == "final" || status == "finished"
    val cardBg = if (isLive) surface else bg
    val timeColor = when {
        isLive -> green
        isFinal -> red
        else -> textMuted
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(cardBg)
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.weight(1f)) {
            TeamCrest(teamName = localName, size = 36.dp)
            Spacer(Modifier.height(4.dp))
            Text(localName, style = MaterialTheme.typography.bodySmall, color = text, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }

        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.width(80.dp),
        ) {
            if (isLive) {
                Text("EN VIVO", style = MaterialTheme.typography.labelSmall, color = green, fontWeight = FontWeight.Bold)
            } else if (isFinal) {
                Text("FINAL", style = MaterialTheme.typography.labelSmall, color = red, fontWeight = FontWeight.Bold)
            }
            if (pronosticable) {
                Text("✔ pronóstico", style = MaterialTheme.typography.labelSmall, color = green)
            }
            Spacer(Modifier.height(4.dp))
            if (scoreLocal != null && scoreVisitante != null) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
                    Text(scoreLocal, style = MaterialTheme.typography.titleLarge, color = text, fontWeight = FontWeight.Bold)
                    Text(" - ", style = MaterialTheme.typography.titleLarge, color = textMuted)
                    Text(scoreVisitante, style = MaterialTheme.typography.titleLarge, color = text, fontWeight = FontWeight.Bold)
                }
            } else {
                Text(hora, style = MaterialTheme.typography.bodyMedium, color = timeColor, fontWeight = FontWeight.Medium)
            }
        }

        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.weight(1f)) {
            TeamCrest(teamName = visitanteName, size = 36.dp)
            Spacer(Modifier.height(4.dp))
            Text(visitanteName, style = MaterialTheme.typography.bodySmall, color = text, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}
