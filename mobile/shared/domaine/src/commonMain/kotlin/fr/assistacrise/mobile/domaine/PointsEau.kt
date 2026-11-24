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
) {
    val indicatif: Boolean get() = source == "OSM"
    val libelleEtat: String get() = when (etat) {
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
