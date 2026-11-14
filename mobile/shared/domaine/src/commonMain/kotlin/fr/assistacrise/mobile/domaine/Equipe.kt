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
) {
    val engagee: Boolean get() = engagementDebut != null
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
            cle = it.id, texte = it.charge, auteur = "", horodatage = it.creeLe, moi = true, parRadio = false,
            urgent = false, enAttente = it.etat == EtatAction.EN_ATTENTE,
            refus = if (it.etat == EtatAction.REFUSEE) (it.erreur ?: "Refusé par le serveur") else null,
        )
    }
