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
    /** Le canal radio de la crise ouverte de l'équipe et son indicatif (23/11/2026). */
    @SerialName("canal_crise") val canalCrise: CanalCrise? = null,
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

/**
 * Un seul canal radio par crise (décision du 23/11/2026) : l'équipe y est adressée par son
 * indicatif, « @ALPHA texte ». Canal public : rien de personnel n'y passe.
 */
@Serializable
data class CanalCrise(
    val crise: String,
    val meshtastic: String? = null,
    val meshcore: String? = null,
    val indicatif: String? = null,
) {
    fun nomPour(meshcore: Boolean): String? = if (meshcore) this.meshcore else meshtastic

    /** « @ALPHA texte » si l'équipe a un indicatif. */
    fun adresser(texte: String): String = indicatif?.let { "@$it ${texte.trim()}" } ?: texte.trim()

    /** Rend le texte sans l'adresse s'il est adressé à cet indicatif, sinon null. Le nom que
     * MeshCore met devant est gardé (« Léa: @ALPHA x » → « Léa: x ») : il dit qui parle. */
    fun pourMoi(texte: String): String? {
        val i = indicatif ?: return null
        val m = ADRESSE.find(texte) ?: return null
        if (!m.groupValues[2].equals(i, ignoreCase = true)) return null
        return (m.groupValues[1] + m.groupValues[3]).trim()
    }

    companion object {
        private val ADRESSE = Regex("""^((?:[^:\n@]{1,32}:\s+)?)@([A-Za-z0-9]{2,8})\b[\s:,]*(.*)$""", RegexOption.DOT_MATCHES_ALL)
    }
}

/** Le plan de canaux d'une crise, tel que le serveur le donne (`radio/plan/`) : clés publiques. */
@Serializable
data class PlanRadio(
    val crise: String,
    val version: String = "",
    val meshtastic: List<CanalPlanMeshtastic> = emptyList(),
    val meshcore: List<CanalPlanMeshCore> = emptyList(),
    val avertissement: String = "",
) {
    /** Les canaux du plan absents de la radio (comparés par nom, sans « # », sans la casse). */
    fun absents(meshcoreRadio: Boolean, presents: Collection<String>): List<String> {
        val ont = presents.map { normaliser(it) }.toSet()
        val noms = if (meshcoreRadio) meshcore.map { it.nom } else meshtastic.map { it.nom }
        return noms.filter { normaliser(it) !in ont }
    }

    companion object {
        fun normaliser(nom: String) = nom.trim().removePrefix("#").lowercase()

        /** Premier emplacement Meshtastic libre (1 à 7 ; 0 est le primaire, on n'y touche pas). */
        fun emplacementLibreMeshtastic(roles: Map<Int, Int>): Int? = (1..7).firstOrNull { (roles[it] ?: 0) == 0 }

        /** Premier emplacement MeshCore libre (1 à `total` − 1 ; 0 est le canal Public d'usine). */
        fun emplacementLibreMeshCore(occupes: Set<Int>, total: Int = 40): Int? = (1 until total).firstOrNull { it !in occupes }
    }
}

@Serializable
data class CanalPlanMeshtastic(val nom: String, @SerialName("psk_hex") val pskHex: String = "", val role: String = "")

@Serializable
data class CanalPlanMeshCore(val nom: String, @SerialName("cle_hex") val cleHex: String = "", val role: String = "")
