package com.laplace.mobile.ui.screens.agent

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.outlined.ThumbDown
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.laplace.mobile.ui.components.TextoFormateado
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.border
import com.laplace.mobile.ui.theme.cyan
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val FormaUsuario = RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 4.dp)
private val FormaAgente = RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = 4.dp, bottomEnd = 16.dp)

private fun horaCorta(epochMs: Long): String =
    SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(epochMs))

@Composable
fun BurbujaUsuario(mensaje: MensajeChat, modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        Column(
            modifier = Modifier
                .widthIn(max = 320.dp)
                .clip(FormaUsuario)
                .background(accent.copy(alpha = 0.18f))
                .border(BorderStroke(1.dp, accent.copy(alpha = 0.35f)), FormaUsuario)
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            Text(mensaje.contenido, style = MaterialTheme.typography.bodyLarge, color = text)
            Text(
                horaCorta(mensaje.creadoEn),
                style = MaterialTheme.typography.labelSmall,
                color = textMuted,
                modifier = Modifier.align(Alignment.End).padding(top = 4.dp),
            )
        }
    }
}

/** Línea de herramienta: deja ver QUÉ consultó el agente antes de responder (procedencia de los datos). */
@Composable
fun BurbujaHerramienta(herramienta: String, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(surfaceLight)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Icon(Icons.Filled.Build, contentDescription = null, tint = cyan, modifier = Modifier.size(14.dp))
        Text(
            "Consultó: ${etiquetaHerramienta(herramienta)}",
            style = MaterialTheme.typography.labelMedium,
            color = textMuted,
        )
    }
}

@Composable
private fun Etiqueta(texto: String, color: Color) {
    Text(
        texto,
        style = MaterialTheme.typography.labelSmall,
        color = color,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .background(color.copy(alpha = 0.14f))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BurbujaAgente(
    mensaje: MensajeChat,
    esUltimo: Boolean,
    copiado: Boolean,
    onCopiar: () -> Unit,
    onValorar: (Boolean) -> Unit,
    onResponder: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val fuente = remember(mensaje.modo) { fuenteDeModo(mensaje.modo) }
    val rapidas = remember(mensaje.herramienta) { respuestasRapidas(mensaje.herramienta) }
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        mensaje.herramienta?.let { BurbujaHerramienta(it) }
        Column(
            modifier = Modifier
                .fillMaxWidth(0.95f)
                .clip(FormaAgente)
                .background(surface)
                .border(BorderStroke(1.dp, border), FormaAgente)
                .padding(horizontal = 14.dp, vertical = 12.dp),
        ) {
            TextoFormateado(mensaje.contenido, text)

            if (esUltimo && rapidas.isNotEmpty()) {
                FlowRow(
                    modifier = Modifier.padding(top = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    rapidas.forEach { (envio, etiqueta) ->
                        OutlinedButton(onClick = { onResponder(envio) }, modifier = Modifier.heightIn(min = 48.dp)) { Text(etiqueta) }
                    }
                }
            }

            HorizontalDivider(color = border, modifier = Modifier.padding(top = 10.dp, bottom = 4.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                fuente?.let { f ->
                    Etiqueta(listOfNotNull(f.etiqueta, f.detalle.takeIf { f.esIa }).joinToString(" · "), if (f.esIa) accent else textMuted)
                }
                Text(horaCorta(mensaje.creadoEn), style = MaterialTheme.typography.labelSmall, color = textDim)
            }
            fuente?.detalle?.takeIf { !fuente.esIa }?.let {
                Text(it, style = MaterialTheme.typography.labelSmall, color = textDim, modifier = Modifier.padding(top = 2.dp))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onCopiar) {
                    Icon(
                        if (copiado) Icons.Filled.Check else Icons.Filled.ContentCopy,
                        contentDescription = if (copiado) "Respuesta copiada" else "Copiar respuesta",
                        tint = textMuted,
                    )
                }
                Valoracion(mensaje, onValorar)
            }
        }
    }
}

@Composable
private fun Valoracion(mensaje: MensajeChat, onValorar: (Boolean) -> Unit) {
    if (mensaje.runId == null) return
    when (mensaje.valoracion) {
        EstadoValoracion.UTIL, EstadoValoracion.NO_UTIL -> Text(
            "Gracias, quedó registrada tu valoración.",
            style = MaterialTheme.typography.labelSmall,
            color = textMuted,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        else -> {
            val bloqueado = mensaje.valoracion == EstadoValoracion.ENVIANDO
            IconButton(onClick = { onValorar(true) }, enabled = !bloqueado) {
                Icon(Icons.Outlined.ThumbUp, contentDescription = "La respuesta fue útil", tint = textMuted)
            }
            IconButton(onClick = { onValorar(false) }, enabled = !bloqueado) {
                Icon(Icons.Outlined.ThumbDown, contentDescription = "La respuesta no fue útil", tint = textMuted)
            }
            if (mensaje.valoracion == EstadoValoracion.ERROR) {
                Text(
                    "No se pudo guardar.",
                    style = MaterialTheme.typography.labelSmall,
                    color = red,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
        }
    }
}

@Composable
fun IndicadorEscritura(modifier: Modifier = Modifier) {
    val transicion = rememberInfiniteTransition(label = "escribiendo")
    Row(
        modifier = modifier
            .clip(FormaAgente)
            .background(surface)
            .border(BorderStroke(1.dp, border), FormaAgente)
            .padding(horizontal = 14.dp, vertical = 12.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            repeat(3) { indice ->
                val opacidad by transicion.animateFloat(
                    initialValue = 0.25f,
                    targetValue = 1f,
                    animationSpec = infiniteRepeatable(tween(600), RepeatMode.Reverse, StartOffset(indice * 150)),
                    label = "punto$indice",
                )
                Box(Modifier.size(7.dp).alpha(opacidad).clip(CircleShape).background(textMuted))
            }
        }
        Text("Laplace está revisando los datos…", style = MaterialTheme.typography.bodySmall, color = textMuted)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AvisoError(
    estado: ErrorDeEnvio,
    onReintentar: () -> Unit,
    onSeguirSinIa: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val error = estado.error
    val esLimite = error.tipo == TipoError.LIMITE_DIARIO || error.tipo == TipoError.LIMITE_MINUTO
    val espera = estado.esperaRestante ?: 0
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(red.copy(alpha = 0.10f))
            .border(BorderStroke(1.dp, red.copy(alpha = 0.45f)), RoundedCornerShape(12.dp))
            .padding(14.dp)
            .semantics { liveRegion = LiveRegionMode.Assertive },
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(error.titulo, style = MaterialTheme.typography.titleSmall, color = text, fontWeight = FontWeight.SemiBold)
        Text(error.detalle, style = MaterialTheme.typography.bodyMedium, color = textMuted)
        if (espera > 0) {
            Text("Podrás reintentar en $espera s.", style = MaterialTheme.typography.bodySmall, color = textMuted)
        }
        if (error.reintentable || esLimite) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (error.reintentable) {
                    Button(
                        onClick = onReintentar,
                        enabled = espera <= 0,
                        modifier = Modifier.heightIn(min = 48.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = accent),
                    ) { Text("Reintentar") }
                }
                if (esLimite) {
                    OutlinedButton(onClick = onSeguirSinIa, modifier = Modifier.heightIn(min = 48.dp)) { Text("Seguir sin IA") }
                }
            }
        }
    }
}
