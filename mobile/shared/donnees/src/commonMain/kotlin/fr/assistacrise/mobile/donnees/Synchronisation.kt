package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.StatutMission

/** La radio de l'intervenant, vue d'ici : elle sait, ou non, porter un message à une équipe. */
fun interface EmetteurRadio {
    /** @return le protocole (`MESHCORE`, `MESHTASTIC`) par lequel le message est parti sur le
     * canal radio de cette équipe, ou `null` s'il n'est pas parti. */
    suspend fun envoyerAEquipe(equipe: fr.assistacrise.mobile.domaine.Equipe, texte: String): String?
}

/**
 * Fait partir la file d'attente. Le seul endroit qui sait traduire une action en appel au
 * serveur : la file, elle, ne sait pas ce qu'elle transporte.
 */
class Synchronisation(
    private val api: ClientApi,
    private val file: FileAttente,
    private val missions: DepotMissions,
    private val equipes: DepotEquipes,
    private val radio: EmetteurRadio? = null,
) {
    /**
     * Envoie ce qui attend, puis relit ce qui a changé — pour que l'affichage repose sur ce
     * que le serveur a réellement enregistré.
     *
     * @return le nombre d'actions accusées.
     */
    suspend fun envoyerLaFile(force: Boolean = false): Int {
        var missionsTouchees = false
        val accusees = file.vider(force) { action ->
            when (action.genre) {
                ActionEnAttente.GENRE_STATUT_MISSION -> {
                    val statut = StatutMission.entries.firstOrNull { it.name == action.charge }
                    if (statut == null) Reponse.Refus(400, "Statut inconnu de cette version de l'application.")
                    else api.changerStatutMission(action.cible, statut).also { if (it is Reponse.Ok) missionsTouchees = true }
                }
                ActionEnAttente.GENRE_MESSAGE_EQUIPE -> when (val r = api.ecrireAEquipe(action.cible, action.charge, action.radio)) {
                    // La réponse est le fil à jour : on le garde, le message y figure déjà.
                    is Reponse.Ok -> { equipes.garderFil(action.cible, r.valeur); Reponse.Ok(Unit) }
                    is Reponse.Refus -> r
                    is Reponse.Injoignable -> {
                        // Pas de réseau : le message part sur le canal radio de l'équipe, une
                        // seule fois. L'action reste en file — les coéquipiers l'ont entendu,
                        // le serveur pas encore.
                        val equipe = equipes.equipes.value.firstOrNull { it.id == action.cible }
                        if (!action.parRadio && equipe != null) {
                            radio?.envoyerAEquipe(equipe, action.charge)?.let { protocole -> file.noterParRadio(action.id, protocole) }
                        }
                        r
                    }
                }
                ActionEnAttente.GENRE_POSITION -> {
                    val coordonnees = action.charge.split(",").mapNotNull { it.toDoubleOrNull() }
                    if (coordonnees.size != 2) Reponse.Refus(400, "Position illisible.")
                    else api.declarerMaPosition(coordonnees[0], coordonnees[1])
                }
                ActionEnAttente.GENRE_DEPOT -> api.deposer(action.cible, action.charge)
                else -> Reponse.Refus(400, "Action inconnue de cette version de l'application.")
            }
        }
        if (missionsTouchees) missions.rafraichir()
        return accusees
    }
}
