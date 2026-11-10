package com.laplace.mobile.domain.model

import com.laplace.mobile.data.remote.dto.PrediccionWebDto
import com.laplace.mobile.data.remote.dto.TasaBaseLigaDto
import kotlin.math.roundToInt

/** Presentación pura de una predicción: ordena lo que devolvió el motor, no calcula
 * probabilidades (eso es del backend, AGENTS.md §3). Espejo de `frontend/src/lib/prediccion.ts`. */
enum class NivelConfianza(val etiqueta: String, val definicion: String) {
    ALTA("Alta", "Probabilidad ponderada del pick de 60% o más."),
    MEDIA("Media", "Probabilidad ponderada del pick entre 50% y 60%."),
    BAJA("Baja", "Probabilidad menor a 50%, o evidencia limitada (por ejemplo, un equipo sin historial): poca ventaja sobre el azar, tómalo como una lectura y no como una señal."),
    ;

    companion object {
        /** Acepta "ALTA"/"media" o un porcentaje ("72%") que emiten jobs antiguos. */
        fun desdeTexto(valor: String?): NivelConfianza? {
            val limpio = valor?.trim()?.uppercase().orEmpty()
            entries.firstOrNull { it.name == limpio }?.let { return it }
            val porcentaje = limpio.removeSuffix("%").toIntOrNull() ?: return null
            return when {
                porcentaje >= 60 -> ALTA
                porcentaje >= 50 -> MEDIA
                else -> BAJA
            }
        }
    }
}

data class Tripleta(val local: Double, val empate: Double, val visitante: Double)

data class ModuloUsado(val id: String, val etiqueta: String, val pesoPct: Int, val coincide: Boolean)

data class VistaPrediccion(
    val conPronostico: Boolean,
    val probabilidades: Tripleta?,
    /** "Local" | "Empate" | "Visitante" tal como lo emite el consenso. */
    val pick: String?,
    val confianza: NivelConfianza?,
    val modulos: List<ModuloUsado>,
    val totalModulos: Int,
    val coinciden: Int,
    val desactualizadoDias: Int?,
    val tasaBase: Tripleta?,
    val tasaBasePartidos: Int?,
    val cuotasInformativas: String?,
    val motivoSinPronostico: String?,
    val motivosSinPronostico: List<String>,
    /** Frecuencia histórica de la liga (o general) cuando no hay pronóstico: referencia, nunca un pick. */
    val referencia: Tripleta?,
    val referenciaEsDeLaLiga: Boolean,
)

val MODULOS_ETIQUETA = mapOf(
    "odds" to "Cuotas del mercado (sin margen)",
    "historico" to "Dixon-Coles con histórico",
    "forma" to "Forma reciente",
    "tabla" to "Tabla de posiciones",
    "poisson" to "Poisson",
    "h2h" to "Enfrentamientos directos",
    "bsd_ml" to "Modelo ML externo",
)

private const val MOTIVO_POR_DEFECTO = "Faltan datos verificables de ambos equipos para estimar este partido."

private fun TasaBaseLigaDto?.comoTripleta(): Tripleta? {
    val local = this?.pct_local ?: return null
    val empate = pct_empate ?: return null
    val visitante = pct_visitante ?: return null
    return Tripleta(local / 100, empate / 100, visitante / 100)
}

fun construirVista(dto: PrediccionWebDto): VistaPrediccion {
    val consenso = dto.consenso
    val pick = consenso?.pick_final
    val sinPick = pick.isNullOrBlank() || pick.startsWith("Sin pronóstico") || (consenso?.total_modulos ?: 0) == 0
    val ponderada = consenso?.prob_ponderada
    val aFavor = consenso?.modulos_en_consenso.orEmpty().toSet()
    val modulos = consenso?.peso_efectivo.orEmpty().entries
        .filter { it.value > 0 }
        .sortedByDescending { it.value }
        .map { (id, peso) -> ModuloUsado(id, MODULOS_ETIQUETA[id] ?: id, (peso * 100).roundToInt(), id in aFavor) }

    val historico = dto.modulos?.get("historico")
    val desactualizado = if (historico?.ok == true && historico.modelo_desactualizado == true) {
        historico.edad_modelo_dias?.roundToInt()
    } else {
        null
    }
    val cuotas = dto.odds_info?.takeIf { it.isNotBlank() && !it.startsWith("Sin odds") }
    val conPronostico = !sinPick && ponderada != null

    return VistaPrediccion(
        conPronostico = conPronostico,
        probabilidades = if (conPronostico) ponderada?.let { Tripleta(it.local, it.empate, it.visitante) } else null,
        pick = if (sinPick) null else pick,
        confianza = if (sinPick) null else NivelConfianza.desdeTexto(consenso?.confianza_final),
        modulos = modulos,
        totalModulos = consenso?.total_modulos ?: 0,
        coinciden = consenso?.coinciden ?: 0,
        desactualizadoDias = desactualizado,
        tasaBase = dto.tasa_base_liga.comoTripleta(),
        tasaBasePartidos = dto.tasa_base_liga?.partidos,
        cuotasInformativas = cuotas,
        motivoSinPronostico = if (conPronostico) {
            null
        } else {
            dto.calidad_datos?.reason?.takeIf { it.isNotBlank() }
                ?: consenso?.detalle?.takeIf { it.isNotBlank() }
                ?: MOTIVO_POR_DEFECTO
        },
        motivosSinPronostico = if (conPronostico) emptyList() else dto.motivos_sin_pronostico.orEmpty().take(3),
        referencia = if (conPronostico) null else dto.referencia_tasa_base.comoTripleta(),
        referenciaEsDeLaLiga = dto.referencia_tasa_base?.nivel == "liga",
    )
}

/** "Local" -> "River gana"; "Empate" -> "Empate"; cualquier otro texto se deja tal cual. */
fun textoPick(pick: String, local: String, visitante: String): String = when (pick) {
    "Local" -> "${local.ifBlank { "Local" }} gana"
    "Visitante" -> "${visitante.ifBlank { "Visitante" }} gana"
    else -> pick
}

fun porcentaje(valor: Double): Int = (valor * 100).roundToInt()
