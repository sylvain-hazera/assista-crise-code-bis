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
    private var dernierEchangeReussi: Boolean? = null

    private val _etat = MutableStateFlow(EtatLien.AUCUN)
    val etat: StateFlow<EtatLien> = _etat

    /** Ce que dit le système : une connexion à Internet, validée par lui, existe-t-elle ? */
    fun reseau(present: Boolean) {
        reseauPresent = present
        // Le réseau a changé : ce qu'on savait du serveur ne vaut plus rien, dans un sens
        // comme dans l'autre.
        dernierEchangeReussi = null
        calculer()
    }

    /**
     * Ce que dit le serveur : le dernier appel a-t-il abouti ? C'est lui qui tranche, dans
     * les deux sens.
     *
     * - Un Wi-Fi sans Internet, un portail captif ou un central en panne donnent « réseau
     *   présent » et rien au bout : l'échec l'emporte.
     * - À l'inverse, le Wi-Fi d'un satellite de collectivité coupé d'Internet est jugé
     *   « sans connexion » par le système, alors que le serveur local répond : la réussite
     *   l'emporte aussi. Se fier au seul système afficherait « hors ligne » au moment précis
     *   où le satellite fait son travail.
     */
    fun echange(reussi: Boolean) {
        dernierEchangeReussi = reussi
        calculer()
    }

    fun radio(connectee: Boolean) {
        radioConnectee = connectee
        calculer()
    }

    private fun calculer() {
        val internet = dernierEchangeReussi ?: reseauPresent
        _etat.value = when {
            internet -> EtatLien.INTERNET
            radioConnectee -> EtatLien.MESH
            else -> EtatLien.AUCUN
        }
    }
}
