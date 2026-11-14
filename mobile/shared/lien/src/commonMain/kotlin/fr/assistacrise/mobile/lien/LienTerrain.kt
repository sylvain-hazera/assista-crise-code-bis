package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.domaine.EtatLien
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * L'état du lien de terrain, vu par le reste de l'application (dossier § 4). Elle ne nomme
 * jamais MeshCore ni Meshtastic : elle sait seulement par où ça passe.
 *
 * Lot 0 : Internet ou rien. Les radios s'y brancheront aux lots 5 et 6, en ajoutant une
 * source — pas en changeant ce contrat.
 */
class IndicateurLien {
    private var reseauPresent = false
    private var radioConnectee = false
    private var echecsDeSuite = 0

    /** Le serveur a répondu depuis la dernière fois que le système a dit « aucun réseau ». */
    private var reussiSansReseau = false

    private val _etat = MutableStateFlow(EtatLien.AUCUN)
    val etat: StateFlow<EtatLien> = _etat

    /**
     * Vrai après un premier échec : on ne sait plus. L'appelant doit réessayer vite, plutôt
     * que d'attendre son prochain tour — c'est le second essai qui tranche.
     */
    val enDoute: Boolean get() = echecsDeSuite in 1 until ECHECS_POUR_CONCLURE

    /**
     * Ce que dit le système : y a-t-il un réseau, quel qu'il soit ? Son absence est une
     * certitude (mode avion, aucune couverture) ; sa présence n'est qu'un indice.
     */
    fun reseau(present: Boolean) {
        if (present && !reseauPresent) echecsDeSuite = 0     // un réseau revient : on repart confiant
        if (!present) reussiSansReseau = false               // ce qu'on savait ne vaut plus
        reseauPresent = present
        calculer()
    }

    /**
     * Ce que dit le serveur : le dernier appel a-t-il abouti ? C'est lui qui tranche, dans
     * les deux sens — mais pas sur un seul échec.
     *
     * - Un Wi-Fi sans Internet, un portail captif ou un central en panne donnent « réseau
     *   présent » et rien au bout : deux échecs de suite l'emportent.
     * - Le Wi-Fi d'un satellite de collectivité coupé d'Internet est jugé « sans connexion »
     *   par le système alors que le serveur local répond : une réussite l'emporte aussi.
     * - **Un échec isolé ne prouve rien** (constaté le 14/11/2026 sur un vrai téléphone) :
     *   une connexion endormie que l'on réveille, un changement d'antenne, une requête
     *   perdue. Afficher « hors ligne » pour cela, puis attendre une minute avant de
     *   revérifier, faisait douter d'un lien qui marchait.
     */
    fun echange(reussi: Boolean) {
        if (reussi) { echecsDeSuite = 0; reussiSansReseau = !reseauPresent } else echecsDeSuite++
        calculer()
    }

    fun radio(connectee: Boolean) {
        radioConnectee = connectee
        calculer()
    }

    private fun calculer() {
        val internet = when {
            echecsDeSuite >= ECHECS_POUR_CONCLURE -> false   // le serveur ne répond plus
            reseauPresent -> true                            // un réseau, et pas de preuve du contraire
            else -> reussiSansReseau                         // le satellite : pas de réseau vu, mais il répond
        }
        _etat.value = when {
            internet -> EtatLien.INTERNET
            radioConnectee -> EtatLien.MESH
            else -> EtatLien.AUCUN
        }
    }

    companion object {
        const val ECHECS_POUR_CONCLURE = 2
    }
}
