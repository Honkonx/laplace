package com.laplace.mobile.ui.screens.calendar

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.components.MatchCard
import com.laplace.mobile.ui.components.TeamCrest
import com.laplace.mobile.ui.theme.*
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

private enum class Filter(val label: String) {
    ALL("Todos"),
    WITH_ANALYSIS("Con analisis"),
    FINISHED("Terminados"),
}

@Composable
fun CalendarScreen(navController: NavController) {
    var selectedDate by remember { mutableStateOf(Date()) }
    var leagues by remember { mutableStateOf<Map<String, LeagueData>>(emptyMap()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }
    var selectedFilter by remember { mutableStateOf(Filter.ALL) }

    val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.US)
    val displayFormat = SimpleDateFormat("EEE, dd MMM", Locale("es", "CL"))

    fun loadMatches() {
        loading = true
        error = false
        leagues = emptyMap()
    }

    LaunchedEffect(selectedDate) {
        loading = true
        error = false
        try {
            val resp = LaplaceApi.callWebhook(
                action = "juegos",
                params = mapOf("date" to dateFormat.format(selectedDate)),
            )
            val data = resp.data ?: emptyMap()

            val ligasRaw = data["ligas"] as? Map<*, *>
            if (ligasRaw != null) {
                val parsed = mutableMapOf<String, LeagueData>()
                ligasRaw.forEach { (slug, ligaRaw) ->
                    val liga = ligaRaw as? Map<*, *> ?: return@forEach
                    val nombre = liga["nombre"] as? String ?: slug.toString()
                    val logo = liga["logo"] as? String ?: slug.toString()
                    val rawPartidos = liga["partidos"] as? List<*> ?: emptyList<Any>()
                    val partidos = rawPartidos.filterIsInstance<Map<String, Any?>>()
                    parsed[slug.toString()] = LeagueData(nombre, logo, partidos)
                }
                leagues = parsed
            } else {
                val rawPartidos = data["partidos"] as? List<*>
                val allMatches = rawPartidos?.filterIsInstance<Map<String, Any?>>() ?: emptyList()
                val grouped = allMatches.groupBy { it["liga"] as? String ?: "Otras" }
                val parsed = mutableMapOf<String, LeagueData>()
                grouped.forEach { (name, matches) ->
                    val slug = name.lowercase().replace(" ", "_")
                    parsed[name] = LeagueData(name, slug, matches)
                }
                leagues = parsed
            }
        } catch (_: Exception) {
            error = true
        } finally {
            loading = false
        }
    }

    val filteredLeagues = remember(leagues, selectedFilter) {
        leagues.mapValues { (_, ld) ->
            when (selectedFilter) {
                Filter.ALL -> ld.partidos
                Filter.WITH_ANALYSIS -> ld.partidos.filter { it["tiene_analisis"] == true }
                Filter.FINISHED -> ld.partidos.filter {
                    val s = (it["status"] as? String ?: "").lowercase()
                    s == "final" || s == "finished"
                }
            }.let { ld.copy(partidos = it) }
        }.filter { it.value.partidos.isNotEmpty() }
    }

    Box(Modifier.fillMaxSize().background(bg)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Calendario", style = MaterialTheme.typography.headlineLarge, color = text)
                if (!isSameDay(selectedDate, Date())) {
                    Text(
                        "Hoy",
                        style = MaterialTheme.typography.labelLarge,
                        color = accent,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier
                            .clip(RoundedCornerShape(20.dp))
                            .background(surfaceLight)
                            .clickable { selectedDate = Date() }
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                    )
                }
            }
            Spacer(Modifier.height(16.dp))

            WeekStrip(
                selectedDate = selectedDate,
                onSelect = { selectedDate = it },
                onPreviousWeek = { selectedDate = addDays(selectedDate, -7) },
                onNextWeek = { selectedDate = addDays(selectedDate, 7) },
            )

            Spacer(Modifier.height(16.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Filter.entries.forEach { filter ->
                    FilterChip(
                        selected = selectedFilter == filter,
                        onClick = { selectedFilter = filter },
                        label = { Text(filter.label, style = MaterialTheme.typography.labelMedium) },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = accent,
                            selectedLabelColor = text,
                            containerColor = surfaceLight,
                            labelColor = textMuted,
                        ),
                        shape = RoundedCornerShape(8.dp),
                    )
                }
            }

            Spacer(Modifier.height(20.dp))

            when {
                loading && leagues.isEmpty() -> {
                    Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = accent)
                    }
                }
                error -> {
                    Text(
                        "Error al cargar partidos",
                        color = red,
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.align(Alignment.CenterHorizontally),
                    )
                }
                filteredLeagues.isEmpty() -> {
                    Text(
                        "Sin partidos para esta fecha",
                        color = textMuted,
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.align(Alignment.CenterHorizontally),
                    )
                }
                else -> {
                    filteredLeagues.forEach { (_, league) ->
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(bottom = 8.dp),
                        ) {
                            TeamCrest(
                                teamName = league.nombre,
                                size = 28.dp,
                                league = true,
                            )
                            Spacer(Modifier.width(10.dp))
                            Text(
                                league.nombre,
                                style = MaterialTheme.typography.titleMedium,
                                color = text,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            league.partidos.forEach { match ->
                                val tieneAnalisis = match["tiene_analisis"] == true
                                Box {
                                    MatchCard(
                                        localName = match["local"] as? String ?: "",
                                        visitanteName = match["visitante"] as? String ?: "",
                                        hora = match["hora"] as? String ?: "",
                                        scoreLocal = match["gol_local"] as? String,
                                        scoreVisitante = match["gol_visitante"] as? String,
                                        status = match["status"] as? String,
                                        pronosticable = match["pronosticable"] as? Boolean ?: false,
                                        onClick = {
                                            val id = match["id"]?.toString() ?: ""
                                            navController.navigate(
                                                Screen.Prediction(
                                                    matchId = id,
                                                    date = dateFormat.format(selectedDate),
                                                    local = match["local"] as? String ?: "",
                                                    visitante = match["visitante"] as? String ?: "",
                                                    liga = league.nombre,
                                                ),
                                            )
                                        },
                                    )
                                    if (tieneAnalisis) {
                                        Box(
                                            modifier = Modifier
                                                .align(Alignment.TopEnd)
                                                .padding(top = 4.dp, end = 4.dp)
                                                .size(10.dp)
                                                .clip(CircleShape)
                                                .background(green),
                                        )
                                    }
                                }
                            }
                        }
                        Spacer(Modifier.height(16.dp))
                    }
                }
            }
        }
    }
}

private data class LeagueData(
    val nombre: String,
    val logo: String,
    val partidos: List<Map<String, Any?>>,
)

/** Tira de 7 d\u00EDas (la semana de `selectedDate`) \u2014 reemplaza el selector de un solo d\u00EDa por
 * flechas, que obligaba a tocar varias veces para llegar a una fecha cercana. Flechas a los
 * costados siguen ah\u00ED para saltar de semana. 2026-09-08. */
@Composable
private fun WeekStrip(
    selectedDate: Date,
    onSelect: (Date) -> Unit,
    onPreviousWeek: () -> Unit,
    onNextWeek: () -> Unit,
) {
    val weekDays = remember(selectedDate) { weekDaysFor(selectedDate) }
    val dayLabel = SimpleDateFormat("EEE", Locale("es", "CL"))
    val monthLabel = SimpleDateFormat("MMMM yyyy", Locale("es", "CL"))

    Column {
        Row(
            modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                monthLabel.format(selectedDate).replaceFirstChar { it.uppercase() },
                style = MaterialTheme.typography.bodyMedium,
                color = textMuted,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                WeekArrow("\u2039", onPreviousWeek)
                WeekArrow("\u203A", onNextWeek)
            }
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(weekDays) { day ->
                val selected = isSameDay(day, selectedDate)
                val today = isSameDay(day, Date())
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = Modifier
                        .width(44.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(if (selected) accent else surface)
                        .then(
                            if (today && !selected) Modifier.border(1.dp, accent, RoundedCornerShape(12.dp))
                            else Modifier
                        )
                        .clickable { onSelect(day) }
                        .padding(vertical = 10.dp),
                ) {
                    Text(
                        dayLabel.format(day).take(3).replaceFirstChar { it.uppercase() },
                        style = MaterialTheme.typography.labelSmall,
                        color = if (selected) text else textMuted,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        SimpleDateFormat("d", Locale.US).format(day),
                        style = MaterialTheme.typography.titleMedium,
                        color = if (selected) text else if (today) accent else text,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
        }
    }
}

@Composable
private fun WeekArrow(glyph: String, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(32.dp)
            .clip(CircleShape)
            .background(surfaceLight)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(glyph, color = text, style = MaterialTheme.typography.titleMedium)
    }
}

private fun weekDaysFor(date: Date): List<Date> {
    val cal = Calendar.getInstance().apply {
        time = date
        firstDayOfWeek = Calendar.MONDAY
        val diff = (get(Calendar.DAY_OF_WEEK) - Calendar.MONDAY + 7) % 7
        add(Calendar.DAY_OF_YEAR, -diff)
    }
    return (0 until 7).map {
        val d = cal.time
        cal.add(Calendar.DAY_OF_YEAR, 1)
        d
    }
}

private fun isSameDay(a: Date, b: Date): Boolean {
    val ca = Calendar.getInstance().apply { time = a }
    val cb = Calendar.getInstance().apply { time = b }
    return ca.get(Calendar.YEAR) == cb.get(Calendar.YEAR) && ca.get(Calendar.DAY_OF_YEAR) == cb.get(Calendar.DAY_OF_YEAR)
}

private fun addDays(date: Date, days: Int): Date {
    val cal = Calendar.getInstance().apply { time = date }
    cal.add(Calendar.DAY_OF_YEAR, days)
    return cal.time
}
