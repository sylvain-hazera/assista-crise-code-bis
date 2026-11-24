package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Points d'eau incendie (24/11/2026). Trois sources qui ne se mélangent jamais : OpenStreetMap
 * (indicatif), la base du SDIS, et les points signalés puis validés par la commune. La réserve
 * et les intervenants signalent ; la commune valide ; le SDIS reste la référence.
 */
@Serializable
data class PointEau(
    val id: Long,
    val source: String = "",
    val ref: String = "",
    @SerialName("type_pei") val typePei: String = "",
    @SerialName("type_libelle") val typeLibelle: String = "Point d'eau",
    @SerialName("source_eau") val sourceEau: String = "",
    val diametre: Int? = null,
    val debit: Double? = null,
    val volume: Double? = null,
    @SerialName("ref_terrain") val refTerrain: String = "",
    val gestionnaire: String = "",
    val etat: String = "INCONNU",
    val latitude: Double,
    val longitude: Double,
    val attribution: String? = null,
    /** Ouvert par le circuit feu : une pompe est en place, remplissage possible. */
    @SerialName("actif_crise") val actifCrise: Boolean = false,
) {
    val indicatif: Boolean get() = source == "OSM"
    val libelleEtat: String get() = if (actifCrise) "Pompe en place : remplissage possible" else when (etat) {
        "DISPONIBLE" -> "Disponible"
        "INDISPONIBLE" -> "Indisponible"
        "DEFAUT" -> "Défaut signalé"
        else -> "État inconnu"
    }
    val libelleSource: String get() = when (source) {
        "OSM" -> "OpenStreetMap (indicatif, non validé par le SDIS)"
        "SDIS" -> "Base du SDIS"
        "TERRAIN" -> "Signalé et validé par la commune"
        else -> source
    }
}

@Serializable
data class ReponsePointsEau(val tronque: Boolean = false, val total: Int = 0, val resultats: List<PointEau> = emptyList())

enum class GenreSignalementPei(val libelle: String, val surUnPoint: Boolean) {
    INDISPONIBLE("Indisponible", true),
    REMIS_EN_SERVICE("Remis en service", true),
    DEFAUT("Défaut constaté", true),
    NOUVEAU("Nouveau point d'eau", false),
}

enum class NaturePei(val code: String, val libelle: String) {
    PI("PI", "Poteau d'incendie"),
    BI("BI", "Bouche d'incendie"),
    PA("PA", "Point d'aspiration (rivière, étang, piscine…)"),
    CI("CI", "Citerne ou réserve"),
}

/** Ce qui part au serveur ; l'identifiant est tiré ici : renvoyé dix fois, un seul signalement. */
@Serializable
data class SignalementPei(
    val id: String,
    val genre: String,
    val pei: Long? = null,
    val latitude: Double,
    val longitude: Double,
    @SerialName("precision_m") val precisionM: Int? = null,
    @SerialName("type_pei") val typePei: String = "",
    @SerialName("source_eau") val sourceEau: String = "",
    @SerialName("debit_estime") val debitEstime: Double? = null,
    @SerialName("volume_estime") val volumeEstime: Double? = null,
    val commentaire: String = "",
    @SerialName("observe_le") val observeLe: String,
    val crise: String? = null,
)

/** Un de mes signalements, tel que le serveur le connaît (suivi : à valider, validé…). */
@Serializable
data class SuiviSignalementPei(
    val id: String,
    val genre: String = "",
    @SerialName("genre_libelle") val genreLibelle: String = "",
    val statut: String = "",
    @SerialName("statut_libelle") val statutLibelle: String = "",
    val pei: Long? = null,
    @SerialName("motif_decision") val motifDecision: String = "",
    @SerialName("observe_le") val observeLe: String = "",
)

const val RAYON_DOUBLON_PEI_M = 50.0

/** Distance à vol d'oiseau, en mètres. */
fun distanceMetres(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val rad = kotlin.math.PI / 180
    val a = sin((lat2 - lat1) * rad / 2).pow(2) + cos(lat1 * rad) * cos(lat2 * rad) * sin((lon2 - lon1) * rad / 2).pow(2)
    return 2 * 6_371_000.0 * asin(sqrt(a))
}

/** Les points déjà connus à moins de 50 m : un « nouveau » point d'eau en est peut-être un. */
fun doublonsPossibles(points: List<PointEau>, latitude: Double, longitude: Double,
                      rayonM: Double = RAYON_DOUBLON_PEI_M): List<PointEau> =
    points.filter { distanceMetres(latitude, longitude, it.latitude, it.longitude) <= rayonM }
        .sortedBy { distanceMetres(latitude, longitude, it.latitude, it.longitude) }

/** Le point le plus proche d'un toucher sur la carte, s'il est assez près (en mètres). */
fun pointLePlusProche(points: List<PointEau>, latitude: Double, longitude: Double, rayonM: Double): PointEau? =
    doublonsPossibles(points, latitude, longitude, rayonM).firstOrNull()

/** Les points de plusieurs relevés réunis, sans doublon, plafonnés. */
fun reunirPointsEau(listes: List<List<PointEau>>, plafond: Int = 5000): List<PointEau> =
    listes.flatten().distinctBy { it.id }.take(plafond)

/** Le point d'eau d'une mission du circuit feu : le binôme y met une pompe et le déclare actif. */
@Serializable
data class PointEauMission(
    val id: String,
    val nom: String = "",
    val statut: String = "DEMANDE",
    @SerialName("statut_libelle") val statutLibelle: String = "",
    val latitude: Double = 0.0,
    val longitude: Double = 0.0,
    val debit: Double? = null,
    val volume: Double? = null,
)

/** Les gestes du binôme, dans l'ordre du terrain. */
enum class EtatPointEau(val libelle: String, val bouton: String) {
    EN_ROUTE("Binôme en route", "En route"),
    ACTIF("Actif : remplissage possible", "Pompe en place, point actif"),
    FERME("Fermé", "Point fermé"),
}

/** Ce que le binôme peut déclarer depuis l'état connu (comme le serveur l'accepte). */
fun gestesPossibles(statut: String): List<EtatPointEau> = when (statut) {
    "DEMANDE" -> listOf(EtatPointEau.EN_ROUTE, EtatPointEau.ACTIF)
    "EN_ROUTE" -> listOf(EtatPointEau.ACTIF)
    "ACTIF" -> listOf(EtatPointEau.FERME)
    "FERME" -> listOf(EtatPointEau.ACTIF)
    else -> emptyList()
}

/** L'état affiché : le dernier geste encore en file prime sur ce que le serveur a dit. */
fun etatPointEauAffiche(point: PointEauMission, file: List<ActionEnAttente>): Pair<String, Boolean> {
    val enFile = file.lastOrNull { it.genre == ActionEnAttente.GENRE_ETAT_POINT_EAU && it.cible == point.id && it.etat == EtatAction.EN_ATTENTE }
        ?: return point.statut to false
    val etat = Regex("\"etat\"\\s*:\\s*\"([A-Z_]+)\"").find(enFile.charge)?.groupValues?.get(1) ?: return point.statut to false
    return etat to true
}
