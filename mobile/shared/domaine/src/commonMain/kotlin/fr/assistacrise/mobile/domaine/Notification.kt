package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Un message adressé à moi par le serveur (`NotificationApplicationSerializer`). Les quatre
 * dates disent où il en est — et c'est le téléphone qui les fait avancer, en accusant.
 */
@Serializable
data class Notification(
    val id: String,
    val genre: String = GENRE_INFORMATION,
    val titre: String = "",
    val corps: String = "",
    val urgent: Boolean = false,
    @SerialName("institution_nom") val institutionNom: String? = null,
    val campagne: CampagneNotifiee? = null,
    @SerialName("date_creation") val dateCreation: String? = null,
    @SerialName("date_remise") val dateRemise: String? = null,
    @SerialName("date_vue") val dateVue: String? = null,
    @SerialName("date_lue") val dateLue: String? = null,
    @SerialName("date_reponse") val dateReponse: String? = null,
) {
    /** On attend quelque chose de moi : une campagne ouverte à laquelle je n'ai pas répondu. */
    val attendUneReponse: Boolean
        get() = campagne != null && !campagne.repondu && !campagne.cloturee

    companion object {
        const val GENRE_CAMPAGNE = "CAMPAGNE"
        const val GENRE_INFORMATION = "INFORMATION"
    }
}

/** La demande de disponibilités portée par une notification, et ce que j'en ai déjà fait. */
@Serializable
data class CampagneNotifiee(
    val id: String,
    @SerialName("periode_debut") val debut: String = "",
    @SerialName("periode_fin") val fin: String = "",
    val cloturee: Boolean = false,
    val repondu: Boolean = false,
    @SerialName("creneaux_declares") val creneauxDeclares: Int = 0,
) {
    /** « Non » est une réponse : avoir répondu sans aucun créneau, c'est avoir dit non. */
    val aReponduNon: Boolean get() = repondu && creneauxDeclares == 0
}

/** Les étapes que le téléphone accuse. Chacune entraîne les précédentes, côté serveur. */
enum class Etape { REMISE, VUE, LUE }

/**
 * Ce qui doit faire sonner le téléphone, quelle qu'en soit l'origine : une notification du
 * serveur, un message d'équipe, une mission nouvelle. `cle` est stable d'un relevé à
 * l'autre : c'est elle qui garantit qu'une même chose ne sonne pas deux fois.
 */
data class Alerte(
    val cle: String,
    val genre: Genre,
    val titre: String,
    val texte: String,
    val urgent: Boolean = false,
    /** L'objet à ouvrir quand on touche l'alerte : notification, équipe ou mission. */
    val cible: String = "",
) {
    enum class Genre { NOTIFICATION, MESSAGE, MISSION, DOSSIER }
}

/**
 * Parmi `presentes`, celles qui n'ont pas encore sonné. `dejaVues == null` : premier relevé
 * depuis la connexion — on prend acte de l'existant sans rien faire sonner, sinon installer
 * l'application déclencherait d'un coup tout l'historique de l'équipe.
 */
fun alertesNouvelles(presentes: List<Alerte>, dejaVues: Set<String>?): List<Alerte> =
    if (dejaVues == null) emptyList() else presentes.filter { it.cle !in dejaVues }
