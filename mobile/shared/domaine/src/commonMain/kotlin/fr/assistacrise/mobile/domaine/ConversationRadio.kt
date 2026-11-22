package fr.assistacrise.mobile.domaine

import kotlinx.serialization.Serializable

/** Un message de la messagerie radio (canal du nœud ou message direct), gardé sur le téléphone. */
@Serializable
data class MessageConversationRadio(
    val moi: Boolean,
    val auteur: String,
    val texte: String,
    val horodatage: Long,
    val envoye: Boolean = true,
)
