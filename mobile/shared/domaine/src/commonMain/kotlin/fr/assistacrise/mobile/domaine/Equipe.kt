package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Une équipe dont je suis membre, chef ou régulateur (`TeamSerializer`, réduit). */
@Serializable
data class Equipe(
    val id: String,
    @SerialName("name") val nom: String = "",
    @SerialName("institution_nom") val institutionNom: String? = null,
    @SerialName("mission_active_titre") val missionTitre: String? = null,
    @SerialName("mission_active_statut") val missionStatut: String? = null,
    /** Posé par un cadre quand l'équipe part sur le terrain, effacé à la mise au repos. */
    @SerialName("engagement_debut") val engagementDebut: String? = null,
    /** Le canal radio de l'équipe, par protocole : c'est par lui qu'on se parle sans réseau. */
    @SerialName("canal_meshcore_nom") val canalMeshCore: String? = null,
    @SerialName("canal_meshtastic_nom") val canalMeshtastic: String? = null,
    @SerialName("leader") val chef: String? = null,
    /** La mission en cours de l'équipe : un dossier qu'on lui confie en fait partie. */
    @SerialName("mission_active") val missionActive: String? = null,
    val regulateur: String? = null,
) {
    val engagee: Boolean get() = engagementDebut != null

    /** Le chef et le régulateur font avancer les dossiers de l'équipe ; les autres les lisent. */
    fun estDirigeePar(idCompte: String?): Boolean = idCompte != null && (idCompte == chef || idCompte == regulateur)
}

/**
 * Un message de la messagerie d'équipe. Le serveur fusionne déjà les trois voies (salon
 * Matrix, canal MeshCore, canal Meshtastic) en un seul fil ; `source` dit par où il est venu.
 */
@Serializable
data class MessageEquipe(
    @SerialName("event_id") val id: String,
    val source: String = SOURCE_MATRIX,
    val texte: String = "",
    val horodatage: Long = 0,
    @SerialName("expediteur_nom") val auteur: String = "",
    val moi: Boolean = false,
    val urgent: Boolean = false,
) {
    companion object {
        const val SOURCE_MATRIX = "matrix"

        /** Entendu par la radio de ce téléphone, pas (encore) rendu par le serveur. */
        const val SOURCE_RADIO_LOCALE = "radio"
        const val PREFIXE_RADIO_LOCALE = "radio-"
    }
}

/** Un message tel qu'on l'affiche : reçu du serveur, ou écrit ici et pas encore parti. */
data class MessageAffiche(
    val cle: String,
    val texte: String,
    val auteur: String,
    val horodatage: Long,
    val moi: Boolean,
    val parRadio: Boolean,
    val urgent: Boolean,
    val enAttente: Boolean = false,
    val refus: String? = null,
)

/** Le fil d'une équipe : ce que le serveur a rendu, suivi de ce qui attend encore dans la file. */
fun filDeMessages(recus: List<MessageEquipe>, file: List<ActionEnAttente>, idEquipe: String): List<MessageAffiche> =
    recus.map {
        MessageAffiche(it.id, it.texte, it.auteur, it.horodatage, it.moi, it.source != MessageEquipe.SOURCE_MATRIX, it.urgent)
    } + file.filter { it.genre == ActionEnAttente.GENRE_MESSAGE_EQUIPE && it.cible == idEquipe }.map {
        MessageAffiche(
            cle = it.id, texte = it.charge, auteur = "", horodatage = it.creeLe, moi = true, parRadio = it.parRadio,
            urgent = false, enAttente = it.etat == EtatAction.EN_ATTENTE,
            refus = if (it.etat == EtatAction.REFUSEE) (it.erreur ?: "Refusé par le serveur") else null,
        )
    }
