package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Une demande de mobilisation qui m'est adressée (`DemandeMobilisationSerializer`, réduit) :
 * c'est elle que je présente, sous forme de QR code, à qui me demande ce que je fais là.
 */
@Serializable
data class Mobilisation(
    val id: String,
    @SerialName("crise_nom") val criseNom: String = "",
    @SerialName("institution_emettrice_nom") val institutionNom: String = "",
    @SerialName("type_demande_libelle") val nature: String = "",
    @SerialName("point_operationnel_nom") val pointNom: String? = null,
    @SerialName("lieu_texte") val lieuTexte: String = "",
    val statut: String = "ACTIVE",
    @SerialName("cible_utilisateur") val cibleUtilisateur: String? = null,
    @SerialName("date_creation") val date: String? = null,
    @SerialName("jeton_verification") val jeton: String? = null,
    /** L'adresse que le serveur inscrit dans le QR code de l'attestation PDF. */
    @SerialName("adresse_verification") val adresse: String? = null,
) {
    val active: Boolean get() = statut == "ACTIVE"
    val lieu: String get() = pointNom?.takeIf { it.isNotBlank() } ?: lieuTexte
    val reference: String get() = id.take(8).uppercase()

    /** Ce que le QR code contient : l'adresse de la page de vérification, comme sur l'attestation PDF. */
    fun adresseDeVerification(urlSite: String): String? =
        // Celle du serveur d'abord : le QR code de l'écran doit être celui du papier.
        adresse?.takeIf { it.isNotBlank() } ?: jeton?.let { "${urlSite.trimEnd('/')}/verifier-mobilisation/$it" }
}

/** Le verdict du serveur sur un QR code (`verdict_mobilisation`). Sans compte, ni nom ni lieu. */
@Serializable
data class Verdict(
    val valide: Boolean = false,
    val connue: Boolean = false,
    val motif: String = "",
    val complet: Boolean = false,
    val reference: String = "",
    @SerialName("institution_emettrice") val institution: String = "",
    val crise: String = "",
    val nature: String = "",
    val destinataire: String? = null,
    val lieu: String? = null,
    @SerialName("date_creation") val date: String? = null,
    @SerialName("date_revocation") val dateRevocation: String? = null,
)

/**
 * Le jeton porté par un QR code de mobilisation, ou `null` si ce n'en est pas un.
 *
 * **On ne suit jamais l'adresse lue** : on n'en garde que le jeton, que l'on soumet à NOTRE
 * serveur. Un QR code collé par-dessus un autre peut pointer n'importe où ; le pire qu'il
 * obtienne ici est « aucune attestation ne correspond ». L'hôte n'est donc pas vérifié — les
 * attestations portent le domaine de l'institution qui les émet, et il y en a plusieurs.
 */
fun jetonDeMobilisation(lu: String): String? {
    val texte = lu.trim()
    val apres = texte.substringAfter("/verifier-mobilisation/", "").substringBefore('?').substringBefore('#').trim('/')
    // Les anciennes attestations ajoutent « /donnees » ou rien ; le jeton est le premier segment.
    val jeton = apres.substringBefore('/')
    return jeton.takeIf { it.length in 20..64 && it.all { c -> c.isLetterOrDigit() || c == '-' || c == '_' } }
}
