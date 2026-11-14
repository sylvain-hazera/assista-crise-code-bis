package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Le compte connecté, tel que le serveur le décrit (`UserSerializer`, réduit à ce que
 * l'application lit). Les noms de champs sont ceux de l'API : c'est ici, et nulle part
 * ailleurs, que le vocabulaire du serveur est traduit.
 */
@Serializable
data class Compte(
    val id: String,
    val email: String = "",
    @SerialName("first_name") val prenom: String = "",
    @SerialName("last_name") val nom: String = "",
    val type: String = TYPE_UTILISATEUR_SIMPLE,
    @SerialName("institution_nom") val institutionNom: String? = null,
    @SerialName("institution_id") val institutionId: String? = null,
    @SerialName("reserve_a_verifier") val reserveAVerifier: Boolean = false,
    @SerialName("phone_number") val telephone: String? = null,
) {
    val nomComplet: String
        get() = listOf(prenom, nom).filter { it.isNotBlank() }.joinToString(" ").ifBlank { email }

    /**
     * Une seule application, deux modes, choisis par le compte et non par un réglage
     * (dossier § 13) : rattaché à une institution, ou porteur d'un rôle institutionnel,
     * c'est un intervenant ; sinon un citoyen.
     */
    val mode: Mode
        get() = if (institutionId != null || type in TYPES_INSTITUTIONNELS) Mode.INTERVENANT else Mode.CITOYEN

    /**
     * Le serveur réserve l'écriture d'une mission aux rôles institutionnels
     * (`MissionViewSet.get_permissions`). L'application ne propose donc le geste qu'à eux :
     * un bouton qui mène à un refus certain est pire que pas de bouton.
     */
    val peutPiloterLesMissions: Boolean
        get() = type in TYPES_INSTITUTIONNELS

    companion object {
        const val TYPE_UTILISATEUR_SIMPLE = "UTIL_SIMPLE"

        /** Miroir de `INSTITUTIONAL_TYPES` (backend/core/permissions.py). */
        val TYPES_INSTITUTIONNELS = setOf("AUT_LOCALE", "SECOURS", "ADMIN", "REGULATEUR")
    }
}

enum class Mode { INTERVENANT, CITOYEN }
