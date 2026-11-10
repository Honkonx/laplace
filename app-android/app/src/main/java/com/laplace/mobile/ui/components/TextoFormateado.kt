package com.laplace.mobile.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.laplace.mobile.ui.theme.surfaceLight

/** Bloques de la mini-sintaxis que emite el agente: párrafos, listas, tablas simples, **negrita** y `código`.
 * Se construye todo con `AnnotatedString`, nunca se interpreta marcado del modelo más allá de esto. */
sealed interface BloqueTexto {
    data class Parrafo(val lineas: List<String>) : BloqueTexto
    data class Vinetas(val items: List<String>) : BloqueTexto
    data class Numerada(val items: List<String>) : BloqueTexto
    data class Tabla(val filas: List<List<String>>) : BloqueTexto
}

private val REGEX_VINETA = Regex("""^\s*[-*•]\s+""")
private val REGEX_NUMERADA = Regex("""^\s*\d+[.)]\s+""")
private val REGEX_SEPARADOR_TABLA = Regex("""^\s*\|?[\s:-]+(\|[\s:-]+)+\|?\s*$""")
private val REGEX_INLINE = Regex("""\*\*(.+?)\*\*|`(.+?)`""")

private fun esFilaTabla(linea: String) = linea.trim().let { it.startsWith("|") && it.endsWith("|") }

private fun celdas(linea: String) = linea.trim().removePrefix("|").removeSuffix("|").split("|").map { it.trim() }

fun parsearBloques(texto: String): List<BloqueTexto> =
    texto.trim().split(Regex("""\n\s*\n""")).mapNotNull { bruto ->
        val lineas = bruto.lines().filter { it.isNotBlank() }
        when {
            lineas.isEmpty() -> null
            lineas.size >= 2 && lineas.all(::esFilaTabla) && lineas.any { REGEX_SEPARADOR_TABLA.matches(it) } ->
                BloqueTexto.Tabla(lineas.filterNot { REGEX_SEPARADOR_TABLA.matches(it) }.map(::celdas))
            lineas.all { REGEX_VINETA.containsMatchIn(it) } -> BloqueTexto.Vinetas(lineas.map { it.replace(REGEX_VINETA, "") })
            lineas.all { REGEX_NUMERADA.containsMatchIn(it) } -> BloqueTexto.Numerada(lineas.map { it.replace(REGEX_NUMERADA, "") })
            else -> BloqueTexto.Parrafo(lineas.map { it.trimEnd() })
        }
    }

fun textoEnLinea(texto: String, fondoCodigo: Color): AnnotatedString = buildAnnotatedString {
    var cursor = 0
    for (coincidencia in REGEX_INLINE.findAll(texto)) {
        append(texto.substring(cursor, coincidencia.range.first))
        val negrita = coincidencia.groups[1]?.value
        val codigo = coincidencia.groups[2]?.value
        if (negrita != null) {
            withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(negrita) }
        } else if (codigo != null) {
            withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = fondoCodigo)) { append(codigo) }
        }
        cursor = coincidencia.range.last + 1
    }
    append(texto.substring(cursor))
}

@Composable
fun TextoFormateado(texto: String, color: Color, modifier: Modifier = Modifier) {
    val bloques = remember(texto) { parsearBloques(texto) }
    val estilo = MaterialTheme.typography.bodyMedium
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        bloques.forEach { bloque ->
            when (bloque) {
                is BloqueTexto.Parrafo -> Text(textoEnLinea(bloque.lineas.joinToString("\n"), surfaceLight), style = estilo, color = color)
                is BloqueTexto.Vinetas -> ListaItems(bloque.items, color) { "•" }
                is BloqueTexto.Numerada -> ListaItems(bloque.items, color) { "${it + 1}." }
                is BloqueTexto.Tabla -> Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    bloque.filas.forEachIndexed { indice, fila ->
                        Text(
                            textoEnLinea(fila.joinToString("  ·  "), surfaceLight),
                            style = estilo,
                            color = color,
                            fontWeight = if (indice == 0) FontWeight.SemiBold else FontWeight.Normal,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ListaItems(items: List<String>, color: Color, marca: (Int) -> String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        items.forEachIndexed { indice, item ->
            Row {
                Text(marca(indice), style = MaterialTheme.typography.bodyMedium, color = color, modifier = Modifier.width(22.dp))
                Text(textoEnLinea(item, surfaceLight), style = MaterialTheme.typography.bodyMedium, color = color, modifier = Modifier.weight(1f).padding(end = 4.dp))
            }
        }
    }
}
