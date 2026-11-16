package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Une collectivité dont je reçois les alertes, parce que je l'ai demandé. C'est un
 * consentement : la commune n'écrit pas à quelqu'un parce qu'il habite là.
 */
@Serializable
data class AbonnementAlerte(
    @SerialName("institution") val id: String,
    @SerialName("institution_nom") val nom: String = "",
)

/** Une commune ou une intercommunalité à laquelle on peut s'abonner. */
@Serializable
data class Collectivite(val id: String, val nom: String = "")
