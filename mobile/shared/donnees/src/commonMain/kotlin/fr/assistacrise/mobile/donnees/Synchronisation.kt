package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.StatutMission

/** La radio de l'intervenant, vue d'ici : elle sait, ou non, porter un message à une équipe. */
fun interface EmetteurRadio {
    /** @return le ou les protocoles (`MESHCORE`, `MESHTASTIC`, ou `MESHTASTIC,MESHCORE` quand le
     * téléphone tient une radio de chaque, 23/11/2026) par lesquels le message est parti sur le
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
    private val dossiers: DepotDossiers? = null,
    private val radio: EmetteurRadio? = null,
    private val degats: DepotDegats? = null,
    private val terrain: DepotTerrain? = null,
    /** Le nom de l'appareil, pour « entendu par » (un modèle de téléphone, rien de personnel). */
    private val appareil: String = "téléphone",
    private val pointsEau: DepotPointsEau? = null,
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
                ActionEnAttente.GENRE_MESSAGE_TERRAIN -> when (val r = api.envoyerMessageTerrain(action.charge)) {
                    is Reponse.Injoignable -> {
                        // Pas de réseau : l'étiquette part sur le canal radio de l'équipe, une
                        // seule fois ; le message reste en file pour le serveur.
                        val equipe = equipes.equipes.value.firstOrNull { it.id == action.cible }
                        val radioTexte = terrain?.etiquette(action)
                        if (!action.parRadio && equipe != null && radioTexte != null) {
                            radio?.envoyerAEquipe(equipe, radioTexte)?.let { protocole -> file.noterParRadio(action.id, protocole) }
                        }
                        r
                    }
                    else -> r
                }
                ActionEnAttente.GENRE_POSITION -> {
                    val coordonnees = action.charge.split(",").mapNotNull { it.toDoubleOrNull() }
                    if (coordonnees.size != 2) Reponse.Refus(400, "Position illisible.")
                    else api.declarerMaPosition(coordonnees[0], coordonnees[1])
                }
                ActionEnAttente.GENRE_DEPOT -> {
                    val cle = dossiers?.clePhotoDuDepot(action)
                    val octets = cle?.let { dossiers?.lireOctets(it) }
                    if (cle != null && octets == null) Reponse.Refus(400, "La photo jointe n'est plus sur ce téléphone.")
                    else api.deposer(action.cible, action.charge, octets).also { if (it is Reponse.Ok) dossiers?.oublierLesOctets(action) }
                }
                ActionEnAttente.GENRE_COMMENTAIRE -> api.commenter(action.cible, action.charge)
                ActionEnAttente.GENRE_PHOTO -> envoyerPhoto(action)
                ActionEnAttente.GENRE_CONSTAT -> api.envoyerConstat(action.charge)
                // Un serveur pas encore à jour (404) : on garde pour plus tard, rien n'est perdu.
                ActionEnAttente.GENRE_ENTENDU_RADIO -> when (val r = api.envoyerEntendu(action.charge, appareil)) {
                    is Reponse.Refus -> if (r.code == 404) Reponse.Injoignable("Serveur pas encore à jour.") else r
                    else -> r
                }
                ActionEnAttente.GENRE_PHOTO_CONSTAT -> envoyerPhotoConstat(action)
                // Points d'eau (24/11/2026) : un serveur pas encore à jour (404) garde la file.
                ActionEnAttente.GENRE_SIGNALEMENT_PEI -> when (val r = api.envoyerSignalementPei(action.charge)) {
                    is Reponse.Refus -> if (r.code == 404) Reponse.Injoignable("Serveur pas encore à jour.") else r
                    else -> r
                }
                ActionEnAttente.GENRE_PHOTO_SIGNALEMENT_PEI -> envoyerPhotoSignalementPei(action)
                else -> Reponse.Refus(400, "Action inconnue de cette version de l'application.")
            }
        }
        if (missionsTouchees) missions.rafraichir()
        terrain?.apresSynchronisation()
        // Tout ce qui a été saisi dans le secteur embarqué est parti : il s'efface (décision du 20/11/2026).
        degats?.apresSynchronisation()
        return accusees
    }

    private suspend fun envoyerPhotoSignalementPei(action: ActionEnAttente): Reponse<Unit> {
        val depot = pointsEau ?: return Reponse.Refus(400, "Action inconnue de cette version de l'application.")
        val photo = depot.lirePhoto(action) ?: return Reponse.Refus(400, "Photo illisible.")
        val octets = depot.octets(photo) ?: return Reponse.Refus(400, "Les données de cette photo ne sont plus sur ce téléphone.")
        return when (val r = api.envoyerPhotoSignalementPei(action.cible, octets, photo.commentaire)) {
            is Reponse.Ok -> {
                val recue = r.valeur
                if (recue != null && !recue.equals(photo.empreinte, ignoreCase = true)) {
                    Reponse.Refus(409, "L'empreinte de la photo reçue par le serveur ne correspond pas à celle prise ici. Signalez-le à votre encadrement.")
                } else {
                    depot.oublierLesOctets(action)
                    Reponse.Ok(Unit)
                }
            }
            is Reponse.Refus -> if (r.code == 404) Reponse.Injoignable("Serveur pas encore à jour.") else r
            is Reponse.Injoignable -> r
        }
    }

    private suspend fun envoyerPhotoConstat(action: ActionEnAttente): Reponse<Unit> {
        val depot = degats ?: return Reponse.Refus(400, "Action inconnue de cette version de l'application.")
        val photo = depot.lirePhoto(action) ?: return Reponse.Refus(400, "Photo illisible.")
        val octets = depot.octets(photo) ?: return Reponse.Refus(400, "Les données de cette photo ne sont plus sur ce téléphone.")
        return when (val r = api.envoyerPhotoConstat(action.cible, octets, photo.commentaire)) {
            is Reponse.Ok -> {
                val recue = r.valeur
                if (recue != null && !recue.equals(photo.empreinte, ignoreCase = true)) {
                    Reponse.Refus(409, "L'empreinte de la photo reçue par le serveur ne correspond pas à celle prise ici. Signalez-le à votre encadrement.")
                } else {
                    depot.oublierLesOctets(action)
                    Reponse.Ok(Unit)
                }
            }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    private suspend fun envoyerPhoto(action: ActionEnAttente): Reponse<Unit> {
        val depot = dossiers ?: return Reponse.Refus(400, "Action inconnue de cette version de l'application.")
        val photo = depot.lirePhotoEnAttente(action) ?: return Reponse.Refus(400, "Photo illisible.")
        val octets = depot.octetsEnAttente(photo) ?: return Reponse.Refus(400, "Les données de cette photo ne sont plus sur ce téléphone.")
        return when (val r = api.deposerPhoto(action.cible, octets, photo.commentaire)) {
            is Reponse.Ok -> {
                val recue = r.valeur.empreinte
                if (recue != null && !recue.equals(photo.empreinte, ignoreCase = true)) {
                    // Le serveur n'a pas reçu les octets qui sont partis d'ici. On ne l'efface pas
                    // en silence : la photo reste visible comme refusée, avec la raison.
                    Reponse.Refus(409, "L'empreinte de la photo reçue par le serveur ne correspond pas à celle prise ici. Signalez-le à votre encadrement.")
                } else {
                    depot.oublierLesOctets(action)
                    depot.rafraichir(action.cible)
                    Reponse.Ok(Unit)
                }
            }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }
}
