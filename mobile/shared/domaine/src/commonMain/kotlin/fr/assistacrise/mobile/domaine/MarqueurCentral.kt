package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Le périmètre de la carte (27/11/2026, `carte-terrain/perimetre/`) : la crise en cours de mes
 * équipes (« engagement »), sinon les crises de ma commune (« commune »), sinon rien. */
@Serializable
data class PerimetreCarte(val raison: String = "aucune", val crises: List<CrisePerimetre> = emptyList())

@Serializable
data class CrisePerimetre(
    val id: String,
    val nom: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    /** Le contour dessiné de la crise (GeoJSON), s'il existe. */
    val zone: kotlinx.serialization.json.JsonElement? = null,
) {
    /** Les sommets du contour (latitude, longitude), sinon le centre. */
    fun points(): List<Pair<Double, Double>> {
        val z = zone?.toString()
        val sommets = z?.let { Regex("""\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*]""").findAll(it)
            .map { m -> m.groupValues[2].toDouble() to m.groupValues[1].toDouble() }.toList() }.orEmpty()
        return sommets.ifEmpty { listOfNotNull(if (latitude != null && longitude != null) latitude to longitude else null) }
    }
}

/** Un marqueur terrain tel que le serveur le garde (27/11/2026, `marqueurs-terrain/`) : arrivé par
 * une passerelle radio, l'application ou le site, sur une crise ou une manifestation. */
@Serializable
data class MarqueurCentral(
    val id: String,
    val crise: String? = null,
    val manifestation: String? = null,
    val emoji: String,
    val genre: String = "",
    val libelle: String = "",
    val route: Boolean = false,
    val latitude: Double,
    val longitude: Double,
    val note: String = "",
    @SerialName("auteur_nom") val auteur: String = "",
    @SerialName("source_libelle") val source: String = "",
    @SerialName("cree_le") val creeLe: String = "",
    @SerialName("decision_libelle") val decision: String = "",
) {
    val marqueur: MarqueursRadio.Marqueur get() = MarqueursRadio.Marqueur(emoji, latitude, longitude, note.ifBlank { null })
}


/** Ce à quoi un marqueur posé est rattaché : une crise ouverte OU une manifestation en cours. */
data class Rattachement(val crise: String? = null, val manifestation: String? = null, val nom: String = "") {
    val cle: String get() = crise?.let { "c:$it" } ?: "m:$manifestation"
}
