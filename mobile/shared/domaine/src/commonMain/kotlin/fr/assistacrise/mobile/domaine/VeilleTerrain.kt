package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * La mini veille du territoire (27/11/2026) : pour la crise ou la manifestation en cours, six
 * rubriques en texte (vigilance météo ; orages, foudre, pluie intense ; rafales, neige, verglas,
 * grêle ; crues et inondation ; séismes ; feux et points chauds). Servie par
 * `carte-terrain/veille/` (backend/core/veille_terrain.py).
 */
@Serializable
data class VeilleTerrain(
    @SerialName("genere_le") val genereLe: String? = null,
    val zones: List<ZoneVeille> = emptyList(),
    /** Les cinq stations-service les plus proches (de ma position, sinon de la zone). */
    val stations: StationsVeille = StationsVeille(),
) {
    /** Ce qui demande l'attention, toutes zones confondues (alerte ou exceptionnel). */
    val alertes: Int get() = zones.sumOf { z -> z.rubriques.sumOf { r -> r.evenements.count { it.important } } }
    val exceptionnel: Boolean get() = zones.any { z -> z.rubriques.any { r -> r.evenements.any { it.niveau == EvenementVeille.EXCEPTIONNEL } } }

    /** Une ligne pour l'écran des missions : « Veille : 2 alertes (Orages, Séismes) » ou « rien à signaler ». */
    fun resume(): String {
        if (zones.isEmpty()) return "Veille : aucune crise ni manifestation en cours"
        val ou = zones.flatMap { z -> z.rubriques.filter { r -> r.evenements.any { it.important } }.map { it.libelleCourt } }.distinct()
        return when {
            alertes == 0 -> "Veille : rien d'important à signaler"
            else -> "Veille : $alertes alerte" + (if (alertes > 1) "s" else "") + " (" + ou.joinToString(", ") + ")"
        }
    }
}

@Serializable
data class StationsVeille(
    @SerialName("autour_de") val autourDe: String? = null,
    val resultats: List<StationVeille> = emptyList(),
)

@Serializable
data class StationVeille(
    @SerialName("distance_km") val distanceKm: Double = 0.0,
    val adresse: String = "",
    val ville: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("carburants_disponibles") val carburants: List<String> = emptyList(),
    @SerialName("ruptures_temporaires") val ruptures: List<String> = emptyList(),
    @SerialName("automate_24_24") val automate: Boolean = false,
) {
    /** « 1,2 km · 12 route de Lyon, Firminy ». */
    val titre: String get() = (distanceKm.toString().replace('.', ',') + " km · " + listOf(adresse, ville).filter { it.isNotBlank() }.joinToString(", "))
        .removeSuffix(" · ")

    /** « Gazole, SP95 · manque : E10 · automate 24/24 », ou « plus rien à délivrer ». */
    val etat: String get() = listOfNotNull(
        if (carburants.isEmpty()) (if (ruptures.isEmpty()) "carburants inconnus" else "plus rien à délivrer") else carburants.joinToString(", "),
        ruptures.takeIf { it.isNotEmpty() }?.let { "manque : " + it.joinToString(", ") },
        if (automate) "automate 24/24" else null,
    ).joinToString(" · ")

    val enRupture: Boolean get() = ruptures.isNotEmpty()
}

@Serializable
data class ZoneVeille(
    /** `crise` ou `manifestation`. */
    val nature: String = "crise",
    val id: String = "",
    val nom: String = "",
    val communes: Int = 0,
    val rubriques: List<RubriqueVeille> = emptyList(),
)

@Serializable
data class RubriqueVeille(
    val code: String = "",
    val libelle: String = "",
    /** `ok`, `perimee` (sources muettes) ou `indisponible`. */
    val etat: String = "ok",
    val evenements: List<EvenementVeille> = emptyList(),
) {
    val libelleCourt: String get() = libelle.substringBefore(",").substringBefore(" et ")

    /** Ce qu'on écrit quand il n'y a rien : jamais un « rien » qui viendrait d'une source tue. */
    val texteSiVide: String get() = when (etat) {
        "perimee" -> "Pas de donnée récente : la source ne répond plus."
        "indisponible" -> "Indisponible pour le moment."
        else -> "Rien à signaler."
    }
}

@Serializable
data class EvenementVeille(
    /** `INFO`, `ALERTE` ou `EXCEPTIONNEL`, selon les seuils conseillés des alertes automatiques. */
    val niveau: String = INFO,
    val titre: String = "",
    val detail: String = "",
) {
    val important: Boolean get() = niveau == ALERTE || niveau == EXCEPTIONNEL

    companion object {
        const val INFO = "INFO"
        const val ALERTE = "ALERTE"
        const val EXCEPTIONNEL = "EXCEPTIONNEL"
    }
}
