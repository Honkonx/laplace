package com.laplace.mobile.ui.screens.log

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.HttpLogger
import com.laplace.mobile.ui.theme.*

@Composable
fun LogScreen(navController: NavController) {
    var showClearDialog by remember { mutableStateOf(false) }
    val logs = remember { HttpLogger.getLogs() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .padding(20.dp),
    ) {
        Spacer(Modifier.height(48.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Registro de Actividad", style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
            if (logs.isNotEmpty()) {
                TextButton(onClick = { showClearDialog = true }) {
                    Text("Limpiar", color = red, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        Text("${logs.size} entradas", style = MaterialTheme.typography.bodySmall, color = textDim)
        Spacer(Modifier.height(16.dp))

        if (logs.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("Sin registros aun", style = MaterialTheme.typography.bodyMedium, color = textMuted)
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(logs, key = { "${it.action}_${it.timestamp}" }) { entry ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(surface)
                            .padding(12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(entry.action, style = MaterialTheme.typography.bodySmall, color = text, fontWeight = FontWeight.Medium)
                            Text(
                                "${entry.elapsed}ms",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (entry.elapsed < 3000) textDim else orange,
                            )
                        }
                        val isOk = entry.status in 200..299
                        Text(
                            "${entry.status}",
                            style = MaterialTheme.typography.bodySmall,
                            color = if (isOk) green else red,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }

    if (showClearDialog) {
        AlertDialog(
            onDismissRequest = { showClearDialog = false },
            title = { Text("Limpiar registro") },
            text = { Text("Eliminar todas las entradas del registro?") },
            confirmButton = {
                TextButton(onClick = {
                    HttpLogger.clear()
                    showClearDialog = false
                }) { Text("Limpiar", color = red) }
            },
            dismissButton = {
                TextButton(onClick = { showClearDialog = false }) { Text("Cancelar") }
            },
            containerColor = surface,
            titleContentColor = text,
            textContentColor = textMuted,
        )
    }
}
