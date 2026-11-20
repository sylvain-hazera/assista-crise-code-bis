package fr.assistacrise.mobile.domaine

import kotlinx.serialization.Serializable

/*
 * « Votre application doit être mise à jour » (demande du 20/11/2026).
 *
 * Le site publie, à côté des APK, `/mobile/version.json` (scripts/publier-mobile.sh) :
 *   {"version": "0.10.0", "code": 14, "minimum": 0,
 *    "applications": {"assista-crise": "assista-crise.apk", "reserve-resilience": "…"}}
 * `code` est le numéro de version de l'APK publié ; `minimum`, le plus petit numéro encore
 * accepté. L'application le lit au démarrage et au retour du réseau, et propose la mise à jour.
 *
 * Jamais bloquante : une application de crise doit rester utilisable sans réseau ni mise à
 * jour. « Obligatoire » veut dire « redemandée souvent », pas « l'application s'arrête ».
 * Logique pure, commune à Android et iOS.
 */

@Serializable
data class VersionPubliee(
    val version: String,
    /** Absent des fichiers publiés avant le 20/11/2026 : on ne propose alors rien. */
    val code: Int? = null,
    val minimum: Int? = null,
    val fichier: String? = null,
    val applications: Map<String, String> = emptyMap(),
)

enum class UrgenceMiseAJour { AUCUNE, CONSEILLEE, OBLIGATOIRE }

data class MiseAJourProposee(
    val urgence: UrgenceMiseAJour,
    val versionPubliee: String,
    /** Adresse de l'APK à télécharger. */
    val adresse: String,
)

object MisesAJour {
    /** Délai avant de reproposer une mise à jour écartée par « Plus tard ». */
    const val REPORT_CONSEILLEE_MS = 24 * 3600_000L
    const val REPORT_OBLIGATOIRE_MS = 3600_000L

    fun urgence(publiee: VersionPubliee, codeInstalle: Int): UrgenceMiseAJour = when {
        publiee.code == null || publiee.code <= codeInstalle -> UrgenceMiseAJour.AUCUNE
        (publiee.minimum ?: 0) > codeInstalle -> UrgenceMiseAJour.OBLIGATOIRE
        else -> UrgenceMiseAJour.CONSEILLEE
    }

    /**
     * Ce qu'il faut proposer, ou null. `marque` : la clé de l'application dans `applications`
     * (« assista-crise ») ; `site` : l'adresse du site qui publie (« https://www.assista-crise.fr ») ;
     * `reporteeLe` : quand la personne a répondu « Plus tard » pour CETTE version, ou null.
     */
    fun aProposer(
        publiee: VersionPubliee, codeInstalle: Int, marque: String, site: String,
        reporteeLe: Long?, maintenant: Long,
    ): MiseAJourProposee? {
        val urgence = urgence(publiee, codeInstalle)
        if (urgence == UrgenceMiseAJour.AUCUNE) return null
        val report = if (urgence == UrgenceMiseAJour.OBLIGATOIRE) REPORT_OBLIGATOIRE_MS else REPORT_CONSEILLEE_MS
        if (reporteeLe != null && maintenant - reporteeLe < report) return null
        val fichier = publiee.applications[marque] ?: publiee.fichier ?: return null
        // Le nom vient du site : rien qui sorte du dossier des APK.
        if (!fichier.matches(Regex("[A-Za-z0-9._-]+\\.apk"))) return null
        return MiseAJourProposee(urgence, publiee.version, "${site.trimEnd('/')}/mobile/$fichier")
    }
}
