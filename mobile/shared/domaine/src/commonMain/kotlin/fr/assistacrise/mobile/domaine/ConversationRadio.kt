package fr.assistacrise.mobile.domaine

import kotlinx.serialization.Serializable

/** Un message de la messagerie radio (canal du nœud ou message direct), gardé sur le téléphone.
 * Depuis le 26/11/2026 : comment il est arrivé (sauts, signal), son identifiant radio (pour les
 * réponses et réactions Meshtastic) et, pour un message envoyé, ce que la radio en a dit. */
@Serializable
data class MessageConversationRadio(
    val moi: Boolean,
    val auteur: String,
    val texte: String,
    val horodatage: Long,
    val envoye: Boolean = true,
    /** Relais traversés (0 = entendu directement) ; null si inconnu. */
    val sauts: Int? = null,
    /** Signal du dernier saut (dB). */
    val snr: Float? = null,
    val rssi: Int? = null,
    /** MeshCore : arrivé par une route directe (sauts non transmis). */
    val routeDirecte: Boolean = false,
    /** Meshtastic : passé par Internet (MQTT) en chemin. */
    val parInternet: Boolean = false,
    /** Identifiant radio : paquet Meshtastic, ou identifiant local d'un message direct MeshCore. */
    val idRadio: Long = 0,
    /** Le message auquel celui-ci répond (Meshtastic `reply_id`). */
    val repondA: Long = 0,
    /** Message envoyé : ce qu'il est devenu. */
    val statut: StatutEnvoiRadio? = null,
    /** Aller-retour de l'accusé (ms), quand la radio le donne (MeshCore). */
    val delaiMs: Long? = null,
    /** Réactions posées sur ce message : émoji → auteurs. */
    val reactions: Map<String, List<String>> = emptyMap(),
    /** MeshCore : heure d'émission (secondes) que porte la trame ; avec le texte et le nom radio
     * de l'auteur, elle désigne le message dans une réaction (ReactionsRadio). */
    val horodatageRadio: Long = 0,
    /** Nom radio de l'auteur sur un canal (le mien pour un message envoyé). */
    val nomRadio: String? = null,
    /** Message envoyé : le texte tel qu'il est parti (premier morceau), s'il diffère de `texte`. */
    val texteEmis: String? = null,
) {
    /** Le texte qui a circulé sur la radio. */
    val texteRadio: String get() = texteEmis ?: texte

    /** « 2 sauts · SNR 5,5 dB · −92 dBm » : ce que les applications officielles affichent. */
    fun reception(): String = listOfNotNull(
        when {
            routeDirecte -> "route directe"
            sauts == 0 -> "direct"
            sauts != null -> "$sauts saut" + if (sauts > 1) "s" else ""
            else -> null
        },
        snr?.let { "SNR " + ((kotlin.math.round(it * 10) / 10.0).toString().removeSuffix(".0").replace('.', ',')) + " dB" },
        rssi?.let { "${it} dBm".replace('-', '−') },
        if (parInternet) "via Internet" else null,
    ).joinToString(" · ")
}

/** Ce que devient un message radio envoyé (26/11/2026). */
@Serializable
enum class StatutEnvoiRadio(val libelle: String) {
    /** Parti de la radio, sans accusé (canal : personne n'accuse réception). */
    PARTI("envoyé"),
    /** Message direct : un relais l'a pris en charge, le destinataire n'a pas encore confirmé. */
    RELAYE("relayé"),
    RECU("reçu ✓"),
    ECHEC("non remis"),
}
