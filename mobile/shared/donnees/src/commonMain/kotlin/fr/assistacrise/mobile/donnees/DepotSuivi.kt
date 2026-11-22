package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.EtatSuivi
import fr.assistacrise.mobile.domaine.MotifArret
import fr.assistacrise.mobile.domaine.ReglesSuivi
import fr.assistacrise.mobile.domaine.Releve
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.Json

/**
 * L'état du suivi en mission, gardé sur disque : si Android tue puis relance le service, il
 * doit retrouver depuis quand il suit — le plafond de douze heures ne repart pas de zéro.
 */
class DepotSuivi(
    private val magasin: Magasin,
    private val file: FileAttente,
    private val horloge: () -> Long,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    private val _etat = MutableStateFlow(EtatSuivi())
    val etat: StateFlow<EtatSuivi> = _etat

    suspend fun restaurer() {
        _etat.value = magasin.lire(FICHIER)
            ?.let { runCatching { json.decodeFromString(EtatSuivi.serializer(), it) }.getOrNull() }
            ?: EtatSuivi()
    }

    suspend fun consentir(oui: Boolean) = garder(_etat.value.copy(consentement = oui))

    /** @return vrai si le suivi vient de démarrer. */
    suspend fun demarrerSiBesoin(equipes: List<Equipe>): Boolean {
        if (!ReglesSuivi.doitDemarrer(_etat.value, equipes)) return false
        garder(_etat.value.copy(depuis = horloge(), dernierEnvoi = null))
        return true
    }

    /** `equipes` : `null` si on n'a pas pu joindre le serveur. @return le motif, si le suivi s'arrête. */
    suspend fun arreterSiBesoin(equipes: List<Equipe>?): MotifArret? {
        val motif = ReglesSuivi.motifArret(_etat.value, equipes, horloge()) ?: return null
        garder(_etat.value.copy(depuis = null))
        return motif
    }

    /** Arrêt à la main : il vaut pour l'engagement en cours, pas pour le suivant. */
    suspend fun arreterALaMain(equipes: List<Equipe>) {
        garder(_etat.value.copy(depuis = null, engagementArrete = ReglesSuivi.engagementCourant(equipes)))
    }

    /** Coupe le suivi en cours sans rien retenir (changement de zone, formation) : un engagement
     * de l'autre zone le relancera selon les règles habituelles. */
    suspend fun couper() = garder(_etat.value.copy(depuis = null))

    /** Reprise à la main, après un arrêt à la main. */
    suspend fun reprendre() = garder(_etat.value.copy(engagementArrete = null))

    /** Un relevé arrive du GPS : il part dans la file s'il le mérite. @return vrai s'il est retenu. */
    suspend fun relever(releve: Releve): Boolean {
        val etat = _etat.value
        if (!etat.actif || !ReglesSuivi.doitEnvoyer(etat.dernierEnvoi, releve)) return false
        file.remplacer(
            genre = ActionEnAttente.GENRE_POSITION, cible = "moi",
            charge = "${releve.latitude},${releve.longitude}", libelle = "Ma position",
        )
        garder(etat.copy(dernierEnvoi = releve))
        return true
    }

    suspend fun toutEffacer() {
        magasin.effacer(FICHIER)
        _etat.value = EtatSuivi()
    }

    private suspend fun garder(etat: EtatSuivi) {
        magasin.ecrire(FICHIER, json.encodeToString(EtatSuivi.serializer(), etat))
        _etat.value = etat
    }

    private companion object { const val FICHIER = "suivi" }
}
