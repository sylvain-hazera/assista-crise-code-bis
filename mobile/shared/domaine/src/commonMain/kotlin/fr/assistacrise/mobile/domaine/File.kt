package fr.assistacrise.mobile.domaine

import kotlinx.serialization.Serializable

@Serializable
enum class EtatAction {
    /** Pas encore accusée par le serveur : sera retentée. */
    EN_ATTENTE,

    /** Le serveur a répondu non. Elle ne sera pas retentée, et reste visible jusqu'à ce que
     * la personne l'écarte : un refus qu'on efface en silence est un envoi qu'on croit fait. */
    REFUSEE,
}

/**
 * Un geste déclaré sur le téléphone et pas encore accusé par le serveur.
 *
 * `genre` et `charge` restent des chaînes : la file ne sait pas ce qu'elle transporte, et
 * c'est voulu — elle doit pouvoir relire après une mise à jour des actions écrites par la
 * version d'avant.
 */
@Serializable
data class ActionEnAttente(
    val id: String,
    val genre: String,
    val cible: String,
    val charge: String,
    val libelle: String,
    val creeLe: Long,
    val tentatives: Int = 0,
    val prochainEssai: Long = 0,
    val etat: EtatAction = EtatAction.EN_ATTENTE,
    val erreur: String? = null,
) {
    companion object {
        const val GENRE_STATUT_MISSION = "STATUT_MISSION"
        const val GENRE_MESSAGE_EQUIPE = "MESSAGE_EQUIPE"
        const val GENRE_POSITION = "POSITION"

        /** Un dépôt citoyen : `cible` est le chemin de l'API, `charge` le corps JSON. */
        const val GENRE_DEPOT = "DEPOT"
    }
}

/** Superpose aux missions du serveur les changements de statut encore en file. */
fun superposerLaFile(missions: List<Mission>, file: List<ActionEnAttente>): List<MissionAffichee> {
    val derniers = file
        .filter { it.genre == ActionEnAttente.GENRE_STATUT_MISSION && it.etat == EtatAction.EN_ATTENTE }
        .associate { it.cible to it.charge }   // la dernière déclaration l'emporte
    return missions.map { mission ->
        val declare = derniers[mission.id]?.let { nom -> StatutMission.entries.firstOrNull { it.name == nom } }
        if (declare == null) MissionAffichee(mission, nonConfirme = false)
        else MissionAffichee(mission.copy(statut = declare), nonConfirme = true)
    }
}

/** État du lien, tel que le voit le reste de l'application (dossier § 4). */
enum class EtatLien { INTERNET, MESH, AUCUN }
