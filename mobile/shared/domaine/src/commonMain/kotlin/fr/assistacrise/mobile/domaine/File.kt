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
    /** Déjà parti par la radio, faute de réseau. Le serveur ne l'a pas encore : l'action
     * reste en file pour lui être remise, en lui disant de ne pas le rediffuser. */
    val radio: String? = null,
) {
    /** Le protocole (`MESHCORE`, `MESHTASTIC`) par lequel l'action est déjà partie, s'il y en a un. */
    val parRadio: Boolean get() = radio != null

    companion object {
        const val GENRE_STATUT_MISSION = "STATUT_MISSION"
        const val GENRE_MESSAGE_EQUIPE = "MESSAGE_EQUIPE"
        const val GENRE_POSITION = "POSITION"

        /** Un dépôt citoyen : `cible` est le chemin de l'API, `charge` le corps JSON. */
        const val GENRE_DEPOT = "DEPOT"

        /** Un commentaire de dossier : `cible` est le dossier, `charge` le texte. */
        const val GENRE_COMMENTAIRE = "COMMENTAIRE"

        /** Une photo de dossier : `cible` est le dossier, `charge` un `PhotoEnAttente` en JSON. */
        const val GENRE_PHOTO = "PHOTO"

        /** Un constat de dégâts fait à pied : `cible` est l'identifiant du constat (tiré ici),
         * `charge` le `Constat` en JSON. */
        const val GENRE_CONSTAT = "CONSTAT"

        /** Une photo prise pendant un constat : `cible` est le constat, `charge` un `PhotoEnAttente`.
         * Elle part après son constat (la file garde l'ordre) : le serveur la joint au bien. */
        const val GENRE_PHOTO_CONSTAT = "PHOTO_CONSTAT"

        /** Un message de terrain en un geste : `cible` est l'équipe (pour le canal radio),
         * `charge` un `MessageTerrainSortant` en JSON. */
        const val GENRE_MESSAGE_TERRAIN = "MESSAGE_TERRAIN"

        /** Un message que la radio de ce téléphone a entendu (canal de crise, ancien canal
         * d'équipe, EMCOM), remis au serveur au retour du réseau (23/11/2026) : rien ne se perd
         * hors de portée des passerelles. `charge` : le JSON attendu par `radio/entendus/`. */
        const val GENRE_ENTENDU_RADIO = "ENTENDU_RADIO"

        /** Un signalement de point d'eau incendie (24/11/2026) : `cible` est son identifiant
         * (tiré ici), `charge` le `SignalementPei` en JSON. */
        const val GENRE_SIGNALEMENT_PEI = "SIGNALEMENT_PEI"

        /** Une photo d'un signalement de point d'eau : `cible` est le signalement, `charge` un
         * `PhotoEnAttente`. Elle part après son signalement (la file garde l'ordre). */
        const val GENRE_PHOTO_SIGNALEMENT_PEI = "PHOTO_SIGNALEMENT_PEI"
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
