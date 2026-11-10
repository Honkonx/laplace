package com.laplace.mobile.ui.screens.agent

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.border
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textDim
import com.laplace.mobile.ui.theme.textMuted

@Composable
fun AgentScreen(viewModel: AgentViewModel = viewModel()) {
    val ui by viewModel.ui.collectAsState()
    var entrada by rememberSaveable { mutableStateOf("") }
    var mostrarOpciones by rememberSaveable { mutableStateOf(false) }
    val clipboard = LocalClipboardManager.current
    val listState = rememberLazyListState()

    val totalFilas = (if (ui.mensajes.isEmpty()) 1 else ui.mensajes.size) +
        (if (ui.enviando) 1 else 0) + (if (ui.errorEnvio != null) 1 else 0)
    LaunchedEffect(totalFilas) { listState.animateScrollToItem(totalFilas - 1) }

    fun enviar(texto: String) {
        viewModel.enviar(texto)
        entrada = ""
    }

    Column(modifier = Modifier.fillMaxSize().background(bg).imePadding()) {
        Cabecera(
            ui = ui,
            hayConversacion = ui.mensajes.isNotEmpty(),
            onModo = viewModel::cambiarModo,
            onOpciones = { viewModel.cargarOpciones(); mostrarOpciones = true },
            onNueva = viewModel::nuevaConversacion,
        )
        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (ui.mensajes.isEmpty()) {
                item(key = "bienvenida") { Bienvenida(onSugerencia = ::enviar) }
            }
            items(ui.mensajes, key = { it.id }) { mensaje ->
                when (mensaje.rol) {
                    RolMensaje.USUARIO -> BurbujaUsuario(mensaje)
                    RolMensaje.AGENTE -> BurbujaAgente(
                        mensaje = mensaje,
                        esUltimo = mensaje.id == ui.mensajes.last().id && !ui.enviando,
                        copiado = ui.copiadoId == mensaje.id,
                        onCopiar = {
                            clipboard.setText(AnnotatedString(mensaje.contenido))
                            viewModel.marcarCopiado(mensaje.id)
                        },
                        onValorar = { util -> viewModel.valorar(mensaje.id, util) },
                        onResponder = ::enviar,
                    )
                }
            }
            if (ui.enviando) item(key = "escribiendo") { IndicadorEscritura() }
            ui.errorEnvio?.let { error ->
                item(key = "error") {
                    AvisoError(error, onReintentar = viewModel::reintentar, onSeguirSinIa = viewModel::seguirSinIa)
                }
            }
        }
        Composer(
            valor = entrada,
            maximo = ui.mensajeMaxCaracteres,
            enviando = ui.enviando,
            onCambio = { entrada = it },
            onEnviar = { enviar(entrada) },
        )
    }

    if (mostrarOpciones) {
        AgentOpcionesSheet(
            estado = ui,
            onCambiarModo = viewModel::cambiarModo,
            onNuevaConversacion = viewModel::nuevaConversacion,
            onActualizar = viewModel::cargarOpciones,
            onCerrar = { mostrarOpciones = false },
        )
    }
}

@Composable
private fun Cabecera(
    ui: AgentUiState,
    hayConversacion: Boolean,
    onModo: (Boolean) -> Unit,
    onOpciones: () -> Unit,
    onNueva: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth().background(surface).padding(start = 16.dp, end = 4.dp, top = 8.dp, bottom = 10.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Laplace", style = MaterialTheme.typography.headlineMedium, color = text)
                Text("Agente de pronósticos · las cifras salen del motor, no de la IA", style = MaterialTheme.typography.bodySmall, color = textMuted)
            }
            if (hayConversacion) {
                IconButton(onClick = onNueva) { Icon(Icons.Filled.Add, contentDescription = "Nueva conversación", tint = textMuted) }
            }
            IconButton(onClick = onOpciones) { Icon(Icons.Filled.Tune, contentDescription = "Opciones del agente", tint = textMuted) }
        }
        Row(
            modifier = Modifier.padding(end = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            SelectorModo(usarIa = ui.usarIa, iaPosible = ui.opciones.iaDisponible != false, onModo = onModo)
            ui.opciones.uso?.takeIf { it.por_dia.limite > 0 }?.let {
                Text(
                    "IA hoy: ${it.por_dia.restantes}/${it.por_dia.limite}",
                    style = MaterialTheme.typography.labelMedium,
                    color = textMuted,
                )
            }
        }
    }
}

@Composable
private fun SelectorModo(usarIa: Boolean, iaPosible: Boolean, onModo: (Boolean) -> Unit) {
    val forma = RoundedCornerShape(20.dp)
    Row(
        modifier = Modifier.selectableGroup().clip(forma).border(BorderStroke(1.dp, border), forma),
    ) {
        listOf(false to "Por reglas", true to "Con IA").forEach { (esIa, etiqueta) ->
            val activo = usarIa == esIa
            val habilitado = !esIa || iaPosible
            Box(
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .background(if (activo) accent.copy(alpha = 0.18f) else surface)
                    .selectable(selected = activo, enabled = habilitado, role = Role.RadioButton) { onModo(esIa) }
                    .padding(horizontal = 16.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    etiqueta,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (activo) accent else if (habilitado) textMuted else textDim,
                    fontWeight = if (activo) FontWeight.Bold else FontWeight.Medium,
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Bienvenida(onSugerencia: (String) -> Unit) {
    Column(modifier = Modifier.padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("¿Qué quieres saber hoy?", style = MaterialTheme.typography.titleLarge, color = text)
        Text(
            "Pregunta por partidos, ligas o cómo leer un pronóstico. Si no hay datos suficientes, Laplace te dirá \"Sin pronóstico\" en vez de inventar un número.",
            style = MaterialTheme.typography.bodyMedium,
            color = textMuted,
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            SUGERENCIAS.forEach { sugerencia ->
                OutlinedButton(onClick = { onSugerencia(sugerencia) }, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text(sugerencia, color = text)
                }
            }
        }
    }
}

@Composable
private fun Composer(valor: String, maximo: Int, enviando: Boolean, onCambio: (String) -> Unit, onEnviar: () -> Unit) {
    val puedeEnviar = valor.isNotBlank() && !enviando
    Row(
        modifier = Modifier.fillMaxWidth().background(surface).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = valor,
            onValueChange = { onCambio(it.take(maximo)) },
            modifier = Modifier.weight(1f),
            placeholder = { Text("Pregunta por un partido o un concepto", color = textDim) },
            maxLines = 4,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            shape = RoundedCornerShape(20.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = text,
                unfocusedTextColor = text,
                focusedBorderColor = accent,
                unfocusedBorderColor = border,
                cursorColor = accent,
            ),
        )
        Box(
            modifier = Modifier.size(48.dp).clip(CircleShape).background(if (puedeEnviar) accent else border),
            contentAlignment = Alignment.Center,
        ) {
            IconButton(onClick = onEnviar, enabled = puedeEnviar, modifier = Modifier.size(48.dp)) {
                Icon(
                    Icons.AutoMirrored.Filled.Send,
                    contentDescription = "Enviar mensaje",
                    tint = if (puedeEnviar) androidx.compose.ui.graphics.Color.White else textDim,
                )
            }
        }
    }
}
