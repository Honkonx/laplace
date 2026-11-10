package com.laplace.mobile.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.laplace.mobile.domain.model.NivelConfianza
import com.laplace.mobile.domain.model.textoPick
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted

/** Procedencia legible del campo `fuente` que emite el job (`claude` = redactado con IA). */
fun etiquetaFuente(fuente: String?): String? = when (fuente?.lowercase()) {
    null, "" -> null
    "claude", "ia" -> "Análisis redactado con IA"
    "python" -> "Motor estadístico"
    else -> fuente
}

/**
 * Pick resumido para cuando solo se conoce lo que devuelve el job (pick + confianza), sin el
 * desglose de probabilidades. Con desglose se usa [PrediccionDetalle].
 */
@Composable
fun PredictionCard(
    pick: String,
    confianza: String? = null,
    source: String? = null,
    local: String = "",
    visitante: String = "",
    modifier: Modifier = Modifier,
) {
    val nivel = NivelConfianza.desdeTexto(confianza)
    if (pick.startsWith("Sin pronóstico")) {
        Column(
            modifier = modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(surface).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text("Sin pronóstico", style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
            Text(
                "No estimar también es un resultado: preferimos no mostrar un número antes que inventarlo.",
                style = MaterialTheme.typography.bodySmall,
                color = textMuted,
            )
        }
        return
    }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(surface)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        etiquetaFuente(source)?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = textMuted) }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Pick del consenso", style = MaterialTheme.typography.labelSmall, color = textDim)
                Text(textoPick(pick, local, visitante), style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
            }
            if (nivel != null) ConfianzaChip(nivel)
        }
        nivel?.let { Text(it.definicion, style = MaterialTheme.typography.bodySmall, color = textMuted) }
        Text(LEYENDA_ESTIMACION, style = MaterialTheme.typography.labelSmall, color = textDim)
    }
}
