package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot

/*
 * L'évaluation des dégâts à pied (DOSSIER-ADRESSES-ET-DEGATS.md, § 5), réservée au personnel
 * municipal et aux élus. Une personne seule, téléphone à la main : la tournée des points les plus
 * proches, « le point est-il bien placé ? », l'évaluation, les photos, un point nouveau là où il
 * n'y a pas d'adresse. Tout part par la file d'attente ; hors réseau, la tournée se calcule sur le
 * secteur embarqué.
 */

/** Les cinq états d'un bien, comme sur le site. */
enum class EtatBien(val libelle: String, val avecDegats: Boolean) {
    PAS_DE_DEGATS("Pas de dégâts", false),
    DEGATS_FAIBLES("Dégâts faibles", true),
    DEGATS_FORTS("Dégâts forts", true),
    DETRUITE("Détruit", true),
}

enum class Danger(val libelle: String) {
    STRUCTURE("Structure instable"), ELECTRICITE("Électricité"), GAZ("Gaz"), EAU("Eau"), AUTRE("Autre danger"),
}

/** Un type de bien du catalogue (logement, véhicule, route…), extensible depuis le terrain. */
@Serializable
data class TypeBien(
    val id: String,
    val nom: String,
    @SerialName("a_une_adresse") val aUneAdresse: Boolean = true,
)

/** Un point de la tournée : une adresse du référentiel, ou un bien déjà référencé. */
@Serializable
data class PointTournee(
    @SerialName("ban_id") val banId: String? = null,
    val habitation: String? = null,
    val libelle: String,
    val latitude: Double,
    val longitude: Double,
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("statut_evaluation") val statutEvaluation: String? = null,
    @SerialName("type_bien") val typeBien: String? = null,
    @SerialName("position_corrigee") val positionCorrigee: Boolean = false,
    /** Évalué sur ce téléphone, en attente d'envoi. */
    val enAttente: Boolean = false,
) {
    val evalue: Boolean get() = enAttente || (statutEvaluation != null && statutEvaluation != "NON_EVALUEE")
}

/** Ce qui est embarqué pour évaluer hors réseau autour d'un point (GET habitations/secteur/). */
@Serializable
data class SecteurEmbarque(
    val crise: String,
    val latitude: Double,
    val longitude: Double,
    @SerialName("rayon_m") val rayonM: Double,
    @SerialName("genere_le") val genereLe: String,
    /** « rayon » ou « commune » (toute la commune, 23/11/2026). */
    val perimetre: String = "rayon",
    /** Le serveur a rogné le secteur à la commune : on n'embarque pas ce qu'on n'a pas le droit d'évaluer. */
    @SerialName("limite_a_la_commune") val limiteALaCommune: Boolean = false,
    /** Plus d'adresses que le plafond : le secteur est incomplet, il faut le réduire. */
    val tronque: Boolean = false,
    val adresses: List<AdresseEmbarquee> = emptyList(),
    val biens: List<BienEmbarque> = emptyList(),
    val dossiers: List<DossierEmbarque> = emptyList(),
    val cercles: List<List<List<Double>>> = emptyList(),
    /** Constats faits sur ce téléphone depuis l'embarquement : l'effacement attend leur envoi. */
    val constatsFaits: Int = 0,
)

@Serializable
data class AdresseEmbarquee(val banId: String, val libelle: String, val latitude: Double, val longitude: Double)

@Serializable
data class BienEmbarque(
    val id: String,
    @SerialName("ban_id") val banId: String? = null,
    val adresse: String,
    val latitude: Double,
    val longitude: Double,
    @SerialName("statut_evaluation") val statutEvaluation: String? = null,
    @SerialName("type_bien") val typeBien: String? = null,
    @SerialName("position_corrigee") val positionCorrigee: Boolean = false,
)

@Serializable
data class DossierEmbarque(val id: String, val numero: String = "", val titre: String = "", val statut: String = "", val habitation: String)

/** Le constat, tel qu'il part au serveur (POST habitations/constat/). `id` est tiré ICI. */
@Serializable
data class Constat(
    val id: String,
    val crise: String,
    @SerialName("ban_id") val banId: String? = null,
    /** Un bien déjà référencé sans adresse : réévalué, pas doublé. */
    val habitation: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("position_corrigee") val positionCorrigee: Boolean = false,
    @SerialName("type_bien") val typeBien: String? = null,
    @SerialName("type_bien_libre") val typeBienLibre: String? = null,
    val description: String? = null,
    @SerialName("statut_evaluation") val statutEvaluation: String,
    val dangers: List<String> = emptyList(),
    @SerialName("personne_sur_place") val personneSurPlace: Boolean? = null,
    @SerialName("a_reloger") val aReloger: Boolean? = null,
    @SerialName("ouvrir_dossier") val ouvrirDossier: Boolean = false,
    val commentaire: String? = null,
    @SerialName("constate_le") val constateLe: String,
)

/** Distance à plat, juste à quelques centimètres près sur quelques kilomètres. */
fun distanceM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val est = (lon2 - lon1) * 111_320.0 * cos((lat1 + lat2) / 2 * PI / 180)
    return hypot(est, (lat2 - lat1) * 111_320.0)
}

/**
 * La tournée hors réseau : les adresses du secteur embarqué (avec l'état du bien de cette adresse
 * s'il est référencé), les biens sans adresse, et par-dessus ce qui a été évalué ici et attend
 * d'être envoyé. Du plus proche au plus lointain, dans le rayon.
 */
fun tourneeHorsLigne(secteur: SecteurEmbarque, enFile: List<Constat>, latitude: Double, longitude: Double,
                     rayonM: Double = 150.0, nombre: Int = 200): List<PointTournee> {
    val biensParAdresse = secteur.biens.filter { it.banId != null }.associateBy { it.banId }
    val evaluesIci = enFile.mapNotNull { it.banId }.toSet()
    val points = secteur.adresses.map { a ->
        val bien = biensParAdresse[a.banId]
        PointTournee(banId = a.banId, habitation = bien?.id, libelle = a.libelle,
                     latitude = bien?.latitude ?: a.latitude, longitude = bien?.longitude ?: a.longitude,
                     statutEvaluation = bien?.statutEvaluation, typeBien = bien?.typeBien,
                     positionCorrigee = bien?.positionCorrigee ?: false, enAttente = a.banId in evaluesIci)
    } + secteur.biens.filter { it.banId == null }.map { b ->
        PointTournee(habitation = b.id, libelle = b.adresse, latitude = b.latitude, longitude = b.longitude,
                     statutEvaluation = b.statutEvaluation, typeBien = b.typeBien)
    } + enFile.filter { it.banId == null && it.latitude != null && it.longitude != null }.map { c ->
        PointTournee(libelle = c.description ?: "Point ajouté ici", latitude = c.latitude!!, longitude = c.longitude!!,
                     statutEvaluation = c.statutEvaluation, enAttente = true)
    }
    return points.map { it.copy(distanceM = distanceM(latitude, longitude, it.latitude, it.longitude)) }
        .filter { it.distanceM <= rayonM }.sortedBy { it.distanceM }.take(nombre)
}

/** Le point le plus proche qui reste à évaluer : « Suivant : 14 rue des Pins, à 20 m ». */
fun prochainPoint(points: List<PointTournee>, sauf: String? = null): PointTournee? =
    points.firstOrNull { !it.evalue && (it.banId ?: it.habitation) != sauf }

/**
 * Le secteur embarqué s'efface dès la synchronisation de ce qui y a été saisi (décision du
 * 20/11/2026) : au moins un constat fait, et plus aucun constat ni photo de constat en file.
 */
fun secteurAEffacer(secteur: SecteurEmbarque?, file: List<ActionEnAttente>): Boolean =
    secteur != null && secteur.constatsFaits > 0 &&
        file.none { it.genre == ActionEnAttente.GENRE_CONSTAT || it.genre == ActionEnAttente.GENRE_PHOTO_CONSTAT }
