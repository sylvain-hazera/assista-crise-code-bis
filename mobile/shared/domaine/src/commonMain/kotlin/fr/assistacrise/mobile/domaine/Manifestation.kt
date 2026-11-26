package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Une manifestation d'association (26/11/2026, `manifestations/`) : course à baliser, dispositif
 * de signalisation radio, exercice, formation. Le bénévole s'inscrit sur un poste ; complet, il
 * passe en liste d'attente.
 */
@Serializable
data class ManifestationAsso(
    val id: String,
    @SerialName("institution_nom") val association: String = "",
    @SerialName("type_libelle") val type: String = "",
    val titre: String,
    val lieu: String = "",
    val organisateur: String = "",
    val debut: String,
    val fin: String,
    val statut: String = "PUBLIEE",
    @SerialName("statut_libelle") val statutLibelle: String = "",
    val places: Int = 0,
    val occupes: Int = 0,
    @SerialName("je_suis_inscrit") val inscrit: Boolean = false,
    val consignes: String = "",
    val postes: List<PosteManifestation> = emptyList(),
    /** Ce que chaque commune traversée a ouvert à l'association (26/11/2026). */
    val partages: List<PartageCommune> = emptyList(),
)

@Serializable
data class PartageCommune(
    val id: String,
    @SerialName("commune_code") val commune: String = "",
    val mairie: String? = null,
    val ouvert: OuvertParLaCommune = OuvertParLaCommune(),
)

/** Seulement ce que la mairie a accepté, et seulement pendant la manifestation. */
@Serializable
data class OuvertParLaCommune(
    val contact: ContactMairie? = null,
    val consignes: String? = null,
    val crises: List<CriseOuverte> = emptyList(),
)

@Serializable
data class ContactMairie(val nom: String = "", val telephone: String = "")

@Serializable
data class CriseOuverte(val id: String, val nom: String)

@Serializable
data class PosteManifestation(
    val id: String,
    val intitule: String,
    val debut: String,
    val fin: String,
    val places: Int = 1,
    val occupes: Int = 0,
    val attente: Int = 0,
    val remarque: String = "",
    @SerialName("mon_statut") val monStatut: String? = null,
    @SerialName("mon_rang_attente") val monRangAttente: Int? = null,
    /** Type de point (PC de manifestation, point de signalisation…) et position, si le bureau l'a placé. */
    @SerialName("type_point_libelle") val typePointLibelle: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
) {
    val complet: Boolean get() = occupes >= places
    /** Inscrit ou en liste d'attente : on peut se désister. */
    val engage: Boolean get() = monStatut == "INSCRIT" || monStatut == "LISTE_ATTENTE"

    /** Ce que le bénévole lit à côté du poste. */
    fun etat(): String = when (monStatut) {
        "INSCRIT" -> "Vous êtes inscrit"
        "LISTE_ATTENTE" -> "Liste d'attente" + (monRangAttente?.let { ", n° $it" } ?: "")
        "PRESENT" -> "Présent"
        "ABSENT" -> "Absent"
        else -> if (complet) "Complet ($occupes/$places)" + (if (attente > 0) ", $attente en attente" else "") else "$occupes/$places inscrit(s)"
    }
}

@Serializable
data class ListeManifestations(val manifestations: List<ManifestationAsso> = emptyList())
