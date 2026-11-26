package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

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
