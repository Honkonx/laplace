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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.laplace.mobile.domain.model.ModuloUsado
import com.laplace.mobile.domain.model.NivelConfianza
import com.laplace.mobile.domain.model.Tripleta
import com.laplace.mobile.domain.model.VistaPrediccion
import com.laplace.mobile.domain.model.porcentaje
import com.laplace.mobile.domain.model.textoPick
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.cyan
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.orange
import com.laplace.mobile.ui.theme.red
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted

const val LEYENDA_ESTIMACION = "Estimación estadística, no una certeza. Cada resultado puede salir distinto de lo más probable."

/** Color del nivel; el texto siempre acompaña, el color nunca es la única señal. */
private fun colorDe(nivel: NivelConfianza) = when (nivel) {
    NivelConfianza.ALTA -> green
    NivelConfianza.MEDIA -> orange
    NivelConfianza.BAJA -> red
}

@Composable
fun ConfianzaChip(nivel: NivelConfianza, modifier: Modifier = Modifier) {
    val color = colorDe(nivel)
    Text(
        text = "Confianza ${nivel.etiqueta.lowercase()}",
        style = MaterialTheme.typography.labelMedium,
        color = color,
        fontWeight = FontWeight.Bold,
        modifier = modifier
            .clip(RoundedCornerShape(20.dp))
            .background(color.copy(alpha = 0.15f))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

/** Barra 1X2 con porcentajes numéricos visibles y una sola descripción para lectores de pantalla. */
@Composable
fun ProbabilidadBarra(
    local: String,
    visitante: String,
    probabilidades: Tripleta,
    modifier: Modifier = Modifier,
) {
    val pLocal = porcentaje(probabilidades.local)
    val pEmpate = porcentaje(probabilidades.empate)
    val pVisitante = porcentaje(probabilidades.visitante)
    val descripcion = "Probabilidades estimadas: ${local.ifBlank { "local" }} $pLocal por ciento, " +
        "empate $pEmpate por ciento, ${visitante.ifBlank { "visitante" }} $pVisitante por ciento."

    Column(modifier = modifier.fillMaxWidth().clearAndSetSemantics { contentDescription = descripcion }) {
        Row(
            modifier = Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(5.dp)),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Box(Modifier.weight(probabilidades.local.toFloat().coerceAtLeast(0.01f)).height(10.dp).background(accent))
            Box(Modifier.weight(probabilidades.empate.toFloat().coerceAtLeast(0.01f)).height(10.dp).background(textDim))
            Box(Modifier.weight(probabilidades.visitante.toFloat().coerceAtLeast(0.01f)).height(10.dp).background(cyan))
        }
        Spacer(Modifier.height(6.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            EtiquetaProbabilidad(local.ifBlank { "Local" }, pLocal, accent, Modifier.weight(1f), Alignment.Start)
            EtiquetaProbabilidad("Empate", pEmpate, textMuted, Modifier.weight(1f), Alignment.CenterHorizontally)
            EtiquetaProbabilidad(visitante.ifBlank { "Visitante" }, pVisitante, cyan, Modifier.weight(1f), Alignment.End)
        }
    }
}

@Composable
private fun EtiquetaProbabilidad(
    nombre: String,
    porcentaje: Int,
    color: Color,
    modifier: Modifier,
    alineacion: Alignment.Horizontal,
) {
    Column(modifier = modifier, horizontalAlignment = alineacion) {
        Text("$porcentaje%", style = MaterialTheme.typography.titleMedium, color = color, fontWeight = FontWeight.Bold)
        Text(nombre, style = MaterialTheme.typography.labelSmall, color = textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Vista de un análisis ya calculado; solo muestra lo que devolvió el motor. 'Sin pronóstico' es un estado válido. */
@Composable
fun PrediccionDetalle(
    vista: VistaPrediccion,
    local: String,
    visitante: String,
    modifier: Modifier = Modifier,
) {
    val probabilidades = vista.probabilidades
    Column(
        modifier = modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(surface).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (!vista.conPronostico || probabilidades == null) {
            SinPronostico(vista)
            return@Column
        }
        ProbabilidadBarra(local, visitante, probabilidades)

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Pick del consenso", style = MaterialTheme.typography.labelSmall, color = textDim)
                Text(
                    vista.pick?.let { textoPick(it, local, visitante) }.orEmpty(),
                    style = MaterialTheme.typography.titleMedium,
                    color = text,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            vista.confianza?.let { ConfianzaChip(it) }
        }
        vista.confianza?.let { Text(it.definicion, style = MaterialTheme.typography.bodySmall, color = textMuted) }

        vista.desactualizadoDias?.let { dias ->
            Text(
                "Modelo desactualizado: los ratings históricos tienen ${(dias / 30).coerceAtLeast(1)} meses. La confianza ya está rebajada.",
                style = MaterialTheme.typography.bodySmall,
                color = orange,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(orange.copy(alpha = 0.12f))
                    .padding(10.dp),
            )
        }

        vista.tasaBase?.let { base ->
            val partidos = vista.tasaBasePartidos?.let { " ($it partidos)" }.orEmpty()
            Text(
                "Tasa base de la liga: local ${porcentaje(base.local)}%, empate ${porcentaje(base.empate)}%, " +
                    "visitante ${porcentaje(base.visitante)}%$partidos",
                style = MaterialTheme.typography.bodySmall,
                color = textMuted,
            )
        }

        if (vista.modulos.isNotEmpty()) ModulosUsados(vista)

        vista.cuotasInformativas?.let {
            Text(
                "Dato del análisis (cuotas del mercado, solo informativo): $it",
                style = MaterialTheme.typography.bodySmall,
                color = textMuted,
            )
        }
        Text(LEYENDA_ESTIMACION, style = MaterialTheme.typography.labelSmall, color = textDim)
    }
}

@Composable
private fun SinPronostico(vista: VistaPrediccion) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Sin pronóstico", style = MaterialTheme.typography.titleMedium, color = text, fontWeight = FontWeight.SemiBold)
        vista.motivoSinPronostico?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = textMuted) }
        vista.motivosSinPronostico.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall, color = textMuted) }
        vista.referencia?.let { ref ->
            val donde = if (vista.referenciaEsDeLaLiga) "esta liga" else "promedio general"
            Text(
                "Referencia, no pronóstico ($donde): Local ${porcentaje(ref.local)}% · Empate ${porcentaje(ref.empate)}% · Visitante ${porcentaje(ref.visitante)}%. No distingue a estos dos equipos.",
                style = MaterialTheme.typography.bodySmall,
                color = textMuted,
            )
        }
        Text(
            "No estimar también es un resultado: preferimos no mostrar un número antes que inventarlo.",
            style = MaterialTheme.typography.labelSmall,
            color = textDim,
        )
    }
}

@Composable
private fun ModulosUsados(vista: VistaPrediccion) {
    var abierto by rememberSaveable { mutableStateOf(false) }
    val titulo = "Cómo se calculó · ${vista.modulos.size} ${if (vista.modulos.size == 1) "modelo" else "modelos"}, " +
        "${vista.coinciden} de ${vista.totalModulos} coinciden con el pick"
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .clickable(role = Role.Button, onClickLabel = if (abierto) "Ocultar detalle" else "Ver detalle") { abierto = !abierto },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(titulo, style = MaterialTheme.typography.bodySmall, color = textMuted, modifier = Modifier.weight(1f))
            Icon(
                if (abierto) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                contentDescription = null,
                tint = textMuted,
            )
        }
        if (abierto) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                vista.modulos.forEach { ModuloFila(it) }
            }
        }
    }
}

@Composable
private fun ModuloFila(modulo: ModuloUsado) {
    Column(
        modifier = Modifier.semantics(mergeDescendants = true) {
            contentDescription = "${modulo.etiqueta}: ${modulo.pesoPct} por ciento del peso" +
                if (modulo.coincide) "" else ", no coincide con el pick"
        },
    ) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(modulo.etiqueta, style = MaterialTheme.typography.bodySmall, color = text, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("${modulo.pesoPct}% del peso", style = MaterialTheme.typography.labelSmall, color = textMuted)
        }
        Spacer(Modifier.height(3.dp))
        Box(Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(surfaceLight)) {
            Box(Modifier.fillMaxWidth(modulo.pesoPct / 100f).height(4.dp).background(accent))
        }
        if (!modulo.coincide) {
            Text("Este modelo no coincide con el pick.", style = MaterialTheme.typography.labelSmall, color = textDim)
        }
    }
}
