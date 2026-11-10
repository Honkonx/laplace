package com.laplace.mobile.ui.screens.agent

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.laplace.mobile.data.remote.dto.CupoVentanaDto
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.border
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted
import com.laplace.mobile.ui.theme.orange

/** Motivo honesto por el que la IA no se puede activar, o `null` si sí se puede (o no se sabe). */
internal fun motivoIaNoDisponible(opciones: OpcionesAgente): String? {
    if (opciones.iaDisponible != false) return null
    val modo = opciones.capacidades?.modos?.firstOrNull { it.id == "ia" }
    return when {
        modo?.disponible == false -> "La IA no está configurada en el servidor."
        opciones.uso?.ia_activa == false -> "El administrador desactivó la IA del agente."
        else -> "Agotaste el cupo de IA de hoy. Las respuestas por reglas no gastan cupo."
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentOpcionesSheet(
    estado: AgentUiState,
    onCambiarModo: (Boolean) -> Unit,
    onNuevaConversacion: () -> Unit,
    onActualizar: () -> Unit,
    onCerrar: () -> Unit,
) {
    val opciones = estado.opciones
    ModalBottomSheet(
        onDismissRequest = onCerrar,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = surface,
        contentColor = text,
    ) {
        Column(
            modifier = Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Opciones del agente", style = MaterialTheme.typography.titleLarge, color = text, modifier = Modifier.weight(1f))
                TextButton(onClick = onActualizar, enabled = !opciones.cargando, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text(if (opciones.cargando) "Actualizando…" else "Actualizar")
                }
            }
            SeccionModo(estado, onCambiarModo)
            SeccionCupo(opciones)
            SeccionContexto(opciones)
            SeccionHerramientas(opciones)
            SeccionActividad(opciones)
            OutlinedButton(
                onClick = { onNuevaConversacion(); onCerrar() },
                enabled = estado.mensajes.isNotEmpty(),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) { Text("Empezar una conversación nueva") }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun Seccion(titulo: String, contenido: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(titulo, style = MaterialTheme.typography.titleSmall, color = text, fontWeight = FontWeight.SemiBold)
        contenido()
    }
}

@Composable
private fun SeccionModo(estado: AgentUiState, onCambiarModo: (Boolean) -> Unit) {
    val motivo = motivoIaNoDisponible(estado.opciones)
    Seccion("Modo de respuesta") {
        Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OpcionModo(
                titulo = "Por reglas",
                descripcion = "Respuestas directas con datos verificados del bot. No gasta cupo.",
                seleccionado = !estado.usarIa,
                habilitado = true,
                onClick = { onCambiarModo(false) },
            )
            OpcionModo(
                titulo = "Con IA",
                descripcion = motivo ?: "Redacta en lenguaje natural. Las cifras siguen saliendo del motor.",
                seleccionado = estado.usarIa,
                habilitado = motivo == null,
                onClick = { onCambiarModo(true) },
            )
        }
    }
}

@Composable
private fun OpcionModo(titulo: String, descripcion: String, seleccionado: Boolean, habilitado: Boolean, onClick: () -> Unit) {
    val forma = RoundedCornerShape(12.dp)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clip(forma)
            .border(BorderStroke(1.dp, if (seleccionado) accent else border), forma)
            .background(if (seleccionado) accent.copy(alpha = 0.10f) else surface)
            .selectable(selected = seleccionado, enabled = habilitado, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        RadioButton(
            selected = seleccionado,
            onClick = null,
            enabled = habilitado,
            colors = RadioButtonDefaults.colors(selectedColor = accent, unselectedColor = textMuted),
        )
        Column {
            Text(titulo, style = MaterialTheme.typography.bodyLarge, color = if (habilitado) text else textDim, fontWeight = FontWeight.Medium)
            Text(descripcion, style = MaterialTheme.typography.bodySmall, color = textMuted)
        }
    }
}

@Composable
private fun SeccionCupo(opciones: OpcionesAgente) {
    Seccion("Cupo de IA") {
        val uso = opciones.uso
        if (uso == null) {
            Text("No se pudo consultar el cupo en este momento.", style = MaterialTheme.typography.bodySmall, color = textMuted)
            return@Seccion
        }
        FilaCupo("Hoy", uso.por_dia, "respuestas con IA")
        FilaCupo("Por minuto", uso.por_minuto, "respuestas con IA")
        if (!uso.ia_activa) {
            Text("El administrador desactivó la IA del agente.", style = MaterialTheme.typography.bodySmall, color = orange)
        } else if (uso.por_dia.limite > 0 && uso.por_dia.restantes <= 0) {
            Text("Sigues pudiendo preguntar: las respuestas por reglas no gastan cupo.", style = MaterialTheme.typography.bodySmall, color = textMuted)
        }
    }
}

@Composable
private fun FilaCupo(etiqueta: String, cupo: CupoVentanaDto, unidad: String) {
    if (cupo.limite <= 0) return
    val fraccion = (cupo.restantes.toFloat() / cupo.limite).coerceIn(0f, 1f)
    val renovacion = cupo.reinicia_en_segundos?.takeIf { cupo.restantes <= 0 || cupo.usadas > 0 }?.let { " · se renueva en $it s" }.orEmpty()
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "$etiqueta: ${cupo.restantes} de ${cupo.limite} $unidad$renovacion",
            style = MaterialTheme.typography.bodyMedium,
            color = text,
        )
        LinearProgressIndicator(
            progress = { fraccion },
            modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)),
            color = if (cupo.restantes <= 0) orange else accent,
            trackColor = surfaceLight,
        )
    }
}

@Composable
private fun SeccionContexto(opciones: OpcionesAgente) {
    var memoriaAbierta by rememberSaveable { mutableStateOf(false) }
    Seccion("Contexto que usa Laplace") {
        val memoria = opciones.memoria
        Text(
            if (memoria == null) "Memoria personal: no disponible ahora." else "Memoria personal: ${memoria.size} ${if (memoria.size == 1) "dato" else "datos"}.",
            style = MaterialTheme.typography.bodyMedium,
            color = text,
        )
        if (!memoria.isNullOrEmpty()) {
            TextButton(onClick = { memoriaAbierta = !memoriaAbierta }, modifier = Modifier.heightIn(min = 48.dp)) {
                Text(if (memoriaAbierta) "Ocultar mi memoria" else "Ver mi memoria")
            }
            if (memoriaAbierta) {
                memoria.take(8).forEach {
                    Text("${it.topic_key}: ${it.content}", style = MaterialTheme.typography.bodySmall, color = textMuted)
                }
            }
        }
        val k = opciones.capacidades?.conocimiento
        if (k != null && k.version.isNotBlank()) {
            Text(
                "Conocimiento ${k.version}: ${k.equipos_con_perfil} equipos con perfil, ${k.ligas_cubiertas} ligas cubiertas" +
                    (k.datos_hasta?.let { ", datos hasta $it" } ?: "") + ".",
                style = MaterialTheme.typography.bodySmall,
                color = textMuted,
            )
        } else {
            Text("No se pudo leer qué conocimiento tiene cargado el servidor.", style = MaterialTheme.typography.bodySmall, color = textMuted)
        }
    }
}

@Composable
private fun SeccionHerramientas(opciones: OpcionesAgente) {
    Seccion(if (opciones.esAdmin) "Herramientas (administrador)" else "Herramientas disponibles") {
        val herramientas = opciones.herramientasVisibles
        if (herramientas.isEmpty()) {
            Text("No se pudo leer el catálogo de herramientas.", style = MaterialTheme.typography.bodySmall, color = textMuted)
            return@Seccion
        }
        herramientas.forEach {
            Column {
                Text(
                    etiquetaHerramienta(it.name) + if (it.admin_only) "  ·  solo admin" else "",
                    style = MaterialTheme.typography.bodyMedium,
                    color = text,
                    fontWeight = FontWeight.Medium,
                )
                Text(it.description, style = MaterialTheme.typography.bodySmall, color = textMuted)
            }
        }
    }
}

@Composable
private fun SeccionActividad(opciones: OpcionesAgente) {
    val tareas = opciones.tareas.orEmpty()
    val subagentes = opciones.subagentes.orEmpty()
    if (tareas.isEmpty() && subagentes.isEmpty()) return
    HorizontalDivider(color = border)
    Seccion("Actividad") {
        tareas.take(5).forEach {
            Text("Tarea ${it.kind}: ${it.status}${it.error?.let { e -> " ($e)" }.orEmpty()}", style = MaterialTheme.typography.bodySmall, color = textMuted)
        }
        subagentes.forEach {
            Text(
                "${it.name} · ${if (it.enabled) "activo" else "inactivo"}" + it.capabilities.takeIf { c -> c.isNotEmpty() }?.joinToString(", ", " · ").orEmpty(),
                style = MaterialTheme.typography.bodySmall,
                color = textMuted,
            )
        }
    }
}
