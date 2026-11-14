package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** Un relevé du téléphone. `instant` en millisecondes depuis 1970. */
@Serializable
data class Releve(val latitude: Double, val longitude: Double, val instant: Long, val precisionM: Float = 0f) {
    /** Distance à vol d'oiseau, en mètres (formule de haversine). */
    fun distanceA(autre: Releve): Double {
        val r = 6_371_000.0
        val dLat = Math_toRadians(autre.latitude - latitude)
        val dLon = Math_toRadians(autre.longitude - longitude)
        val a = sin(dLat / 2).pow(2) +
            cos(Math_toRadians(latitude)) * cos(Math_toRadians(autre.latitude)) * sin(dLon / 2).pow(2)
        return 2 * r * asin(sqrt(a))
    }
}

private fun Math_toRadians(degres: Double) = degres * kotlin.math.PI / 180.0

/** Dernière position connue d'un membre d'une de mes équipes (`positions-equipes/`). */
@Serializable
data class PositionMembre(
    val utilisateur: String,
    @SerialName("utilisateur_nom") val nom: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    val horodatage: String? = null,
    @SerialName("team_noms") val equipes: List<String> = emptyList(),
)

/**
 * Le suivi en mission (dossier § 6). Toutes les règles sont ici, hors d'Android, pour être
 * testées sans téléphone.
 *
 * L'asymétrie est délibérée : **démarrer exige le serveur, arrêter jamais.**
 * - on ne suit que si une de mes équipes est engagée, et c'est le serveur qui le dit ;
 * - on arrête sur fin d'engagement, sur le plafond, ou à la main — sans rien demander à
 *   personne. Un téléphone qui perd le réseau ne doit pas suivre indéfiniment.
 */
@Serializable
data class EtatSuivi(
    /** La personne a accepté d'être suivie en mission. Sans cela, rien ne démarre jamais. */
    val consentement: Boolean = false,
    /** Instant de démarrage du suivi en cours, ou `null` s'il est arrêté. */
    val depuis: Long? = null,
    /** Engagement (`engagement_debut` de l'équipe) que la personne a arrêté à la main : on ne
     * redémarre pas tout seul pour celui-là. Un nouvel engagement, lui, relance le suivi. */
    val engagementArrete: String? = null,
    val dernierEnvoi: Releve? = null,
) {
    val actif: Boolean get() = depuis != null
}

enum class MotifArret { FIN_D_ENGAGEMENT, PLAFOND, MANUEL }

object ReglesSuivi {
    /** Plafond dur : au-delà, le suivi s'arrête quoi qu'il arrive. */
    const val PLAFOND_MS = 12 * 3_600_000L

    /** On n'envoie pas plus souvent, même en mouvement. */
    const val INTERVALLE_MIN_MS = 30_000L

    /** À l'arrêt, on confirme tout de même sa présence à ce rythme. */
    const val INTERVALLE_IMMOBILE_MS = 5 * 60_000L

    /** En deçà, on considère que la personne n'a pas bougé (bruit du GPS). */
    const val DEPLACEMENT_MIN_M = 25.0

    /** L'engagement en cours, s'il y en a un : celui de la première équipe engagée. */
    fun engagementCourant(equipes: List<Equipe>): String? =
        equipes.mapNotNull { it.engagementDebut }.minOrNull()

    /** Le suivi doit-il démarrer maintenant ? */
    fun doitDemarrer(etat: EtatSuivi, equipes: List<Equipe>): Boolean {
        val engagement = engagementCourant(equipes) ?: return false
        return etat.consentement && !etat.actif && engagement != etat.engagementArrete
    }

    /**
     * Le suivi doit-il s'arrêter ? `equipes` vaut `null` quand on ne sait pas (pas de réseau) :
     * l'absence de nouvelles n'arrête rien — c'est tout l'intérêt —, seul le plafond joue.
     */
    fun motifArret(etat: EtatSuivi, equipes: List<Equipe>?, maintenant: Long): MotifArret? {
        val depuis = etat.depuis ?: return null
        if (maintenant - depuis >= PLAFOND_MS) return MotifArret.PLAFOND
        if (equipes != null && engagementCourant(equipes) == null) return MotifArret.FIN_D_ENGAGEMENT
        return null
    }

    /** Cadence adaptative : ce relevé mérite-t-il d'être envoyé ? */
    fun doitEnvoyer(dernier: Releve?, nouveau: Releve): Boolean {
        if (dernier == null) return true
        val ecoule = nouveau.instant - dernier.instant
        if (ecoule < INTERVALLE_MIN_MS) return false
        return ecoule >= INTERVALLE_IMMOBILE_MS || dernier.distanceA(nouveau) >= DEPLACEMENT_MIN_M
    }
}
