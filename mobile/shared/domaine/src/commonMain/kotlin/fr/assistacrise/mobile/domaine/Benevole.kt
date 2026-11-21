package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Les quatre créneaux d'une journée, dans l'ordre du serveur (`Creneau`). */
enum class Creneau(val libelle: String) { MATIN("Matin"), MIDI("Midi"), SOIR("Soir"), NUIT("Nuit") }

@Serializable
data class JourDeGrille(
    val date: String,
    val creneaux: Map<String, Boolean> = emptyMap(),
) {
    fun coche(c: Creneau): Boolean = creneaux[c.name] == true
    val complet: Boolean get() = Creneau.entries.all(::coche)
    val vide: Boolean get() = Creneau.entries.none(::coche)
}

@Serializable
data class RessourceBenevole(@SerialName("institution_nom") val institutionNom: String? = null)

/** La demande à laquelle la grille répond, quand on l'ouvre depuis une campagne. */
@Serializable
data class CampagneDemandee(
    val id: String,
    val intitule: String = "",
    @SerialName("motif_libelle") val motif: String = "",
    val texte: String = "",
    @SerialName("institution_nom") val institutionNom: String = "",
    @SerialName("periode_debut") val debut: String = "",
    @SerialName("periode_fin") val fin: String = "",
)

/**
 * Mes disponibilités (`MesDisponibilitesView`) : une ligne par jour, quatre créneaux. Pas de
 * troisième état — une case décochée veut dire indisponible, c'est la règle du serveur.
 */
@Serializable
data class Grille(
    val ressources: List<RessourceBenevole> = emptyList(),
    val jours: List<JourDeGrille> = emptyList(),
    val campagne: CampagneDemandee? = null,
) {
    /** Sans fiche de ressource, il n'y a rien à déclarer : l'écran le dit au lieu d'une grille vide. */
    val sansRessource: Boolean get() = ressources.isEmpty()

    /** La grille telle qu'elle sera une fois ce créneau (ou la journée, `creneau == null`) posé. */
    fun avec(date: String, creneau: Creneau?, disponible: Boolean): Grille = copy(
        jours = jours.map { jour ->
            if (jour.date != date) jour
            else jour.copy(creneaux = jour.creneaux + (creneau?.let { listOf(it) } ?: Creneau.entries).associate { it.name to disponible })
        },
    )
}

/** Ma fiche de bénévole (`FicheBenevoleSerializer`), réduite à ce que la personne corrige. */
@Serializable
data class Fiche(
    val adresse: String = "",
    @SerialName("code_postal") val codePostal: String = "",
    val ville: String = "",
    @SerialName("departement_code") val departement: String? = null,
    @SerialName("date_naissance") val dateNaissance: String? = null,
    val metier: String = "",
    val situation: String = "",
    @SerialName("frequence_engagement") val frequence: String = "",
    val message: String = "",
    @SerialName("diplome_premier_secours") val premiersSecours: Boolean = false,
    /** Ce que je sais faire : le même arbre que « Proposer mon aide » sur le site. */
    @SerialName("competences_detail") val competences: List<Competence> = emptyList(),
    val avertissement: String? = null,
    /** Faux pour un compte créé par import : il n'a pas encore de mot de passe, seulement son lien. */
    @SerialName("mot_de_passe_defini") val motDePasseDefini: Boolean = true,
) {
    companion object {
        /** Miroir de `SituationProfessionnelle` et `FrequenceEngagement` (backend/core/models.py). */
        val SITUATIONS = listOf(
            "" to "Non renseignée", "SALARIE" to "Salarié(e)", "RETRAITE" to "Retraité(e)",
            "INDEPENDANT" to "Indépendant(e)", "FONCTIONNAIRE" to "Fonctionnaire",
            "ETUDIANT" to "Étudiant(e)", "RECHERCHE_EMPLOI" to "En recherche d'emploi", "AUTRE" to "Autre",
        )
        val FREQUENCES = listOf(
            "" to "Non renseigné", "OCCASIONNELLE" to "Occasionnel (moins de 5 jours par an)",
            "REGULIERE" to "Régulier (environ 10 jours par an)", "FREQUENTE" to "Fréquent (plus de 10 jours par an)",
        )
    }
}

/** Un titre que j'ai déclaré (permis, diplôme) et ce que l'encadrement en a dit. */
@Serializable
data class Titre(
    val id: String,
    @SerialName("qualification_nom") val nom: String? = null,
    val statut: String = "DECLAREE",
    @SerialName("statut_libelle") val statutLibelle: String? = null,
    @SerialName("motif_refus") val motifRefus: String? = null,
    val qualification: String? = null,
    @SerialName("date_expiration") val expiration: String? = null,
    val expiree: Boolean = false,
) {
    val refuse: Boolean get() = statut == "REFUSEE"
    val verifie: Boolean get() = statut == "VERIFIEE"
}

/** Un dossier confié à une de mes équipes (`DossierSerializer`, réduit). */
@Serializable
data class Dossier(
    val id: String,
    val numero: String = "",
    val titre: String = "",
    val description: String = "",
    @SerialName("description_origine") val descriptionOrigine: String? = null,
    @SerialName("crise_nom") val criseNom: String? = null,
    val equipe: String? = null,
    @SerialName("equipe_nom") val equipeNom: String? = null,
    /** La mission sous laquelle le dossier est rangé, s'il y en a une. */
    val mission: String? = null,
    val commune: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("contact_nom") val contactNom: String? = null,
    @SerialName("contact_telephone") val contactTelephone: String? = null,
    val statut: String = "",
    val priorite: String = "NORMALE",
    val ordre: Int = 0,
    val important: Boolean = false,
) {
    val clos: Boolean get() = statut == "CLOTURE" || statut == "RESOLU"
    val situe: Boolean get() = latitude != null && longitude != null
    val statutLibelle: String get() = STATUTS[statut] ?: statut

    companion object {
        /** Miroir de `Dossier.Statut`, avec les mots de la page « Mes interventions » du site. */
        val STATUTS = mapOf(
            "EN_ATTENTE_DISTRIBUTION" to "En attente de distribution", "NOUVEAU" to "Pris en compte",
            "EN_ATTENTE_AFFECTATION" to "En attente d'affectation", "AFFECTE" to "Affecté à l'équipe",
            "EN_COURS" to "En cours", "RESOLU" to "En attente de clôture", "CLOTURE" to "Terminé",
        )

        /** Ce qu'un chef d'équipe peut poser lui-même (`DossierViewSet.definir_statut`). */
        val STATUTS_DE_TERRAIN = listOf("AFFECTE", "EN_COURS")
        private val RANG = mapOf("URGENTE" to 0, "NORMALE" to 1, "BASSE" to 2)

        /** L'ordre de la page du site : l'urgent d'abord, puis l'ordre voulu par le régulateur. */
        fun trier(dossiers: List<Dossier>): List<Dossier> =
            dossiers.sortedWith(compareBy({ it.clos }, { RANG[it.priorite] ?: 1 }, { it.ordre }))
    }
}

/** Un commentaire laissé sur un dossier (`DossierCommentaireSerializer`). */
@Serializable
data class Commentaire(
    val id: String,
    val commentaire: String = "",
    @SerialName("auteur_nom") val auteur: String = "",
    @SerialName("date_creation") val date: String? = null,
)

/**
 * Une photo versée à un dossier (`DocumentSerializer`). `empreinte` est le SHA-256 que le
 * serveur a calculé sur les octets reçus ; la position est celle inscrite dans la photo.
 */
@Serializable
data class Photo(
    val id: String,
    val commentaire: String? = null,
    @SerialName("auteur_nom") val auteur: String = "",
    @SerialName("date_upload") val date: String? = null,
    @SerialName("sha256") val empreinte: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
)

/**
 * Ce qui accompagne une photo prise ici jusqu'à son arrivée au serveur. `cle` désigne les
 * octets, gardés chiffrés ; `empreinte` est calculée sur le téléphone, au moment de la prise,
 * pour être comparée à celle que le serveur rendra.
 */
@Serializable
data class PhotoEnAttente(
    val cle: String,
    val empreinte: String,
    val commentaire: String = "",
    val priseLe: Long = 0,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val precisionM: Float? = null,
)

/** Une ligne du fil d'un dossier : un commentaire reçu, ou écrit ici et pas encore parti. */
data class CommentaireAffiche(val cle: String, val texte: String, val auteur: String, val instant: Long?, val enAttente: Boolean = false, val refus: String? = null)

fun filDuDossier(recus: List<Commentaire>, file: List<ActionEnAttente>, idDossier: String, instantDe: (String?) -> Long?): List<CommentaireAffiche> =
    recus.map { CommentaireAffiche(it.id, it.commentaire, it.auteur, instantDe(it.date)) }.sortedBy { it.instant ?: 0 } +
        file.filter { it.genre == ActionEnAttente.GENRE_COMMENTAIRE && it.cible == idDossier }.map {
            CommentaireAffiche(
                it.id, it.charge, "Vous", it.creeLe, enAttente = it.etat == EtatAction.EN_ATTENTE,
                refus = if (it.etat == EtatAction.REFUSEE) (it.erreur ?: "Refusé par le serveur") else null,
            )
        }

/** Une mission d'une équipe, avec les dossiers que CETTE équipe y traite. */
data class MissionDEquipe(val mission: MissionAffichee, val dossiers: List<Dossier>)

/**
 * Ce qu'une équipe a à faire. `equipe == null` : les missions que je vois sans appartenir à
 * aucune de leurs équipes (un cadre voit celles de toute son institution).
 */
data class TravailDEquipe(val equipe: Equipe?, val missions: List<MissionDEquipe>, val sansMission: List<Dossier>)

/**
 * Range les dossiers là où ils se font : dans une mission, dans une équipe.
 *
 * **Un dossier confié à une équipe fait partie de la mission en cours de cette équipe**, même
 * quand le serveur ne l'a pas écrit sur le dossier lui-même — c'est le cas de tous ceux
 * affectés sans préciser de mission. La 0.5.0 les rangeait à part, sous « autres dossiers » :
 * c'était lire la base au lieu de lire l'organisation (retour de Sylvain du 14/11/2026).
 *
 * `sansMission` ne reçoit donc que les dossiers d'une équipe qui n'a AUCUNE mission en cours :
 * une anomalie d'organisation, que l'écran montre comme telle plutôt que de la cacher.
 */
fun rangerParEquipe(equipes: List<Equipe>, missions: List<MissionAffichee>, dossiers: List<Dossier>): List<TravailDEquipe> {
    val connues = missions.associateBy { it.mission.id }
    val parEquipe = equipes.map { equipe ->
        val siens = dossiers.filter { it.equipe == equipe.id }
        // La mission écrite sur le dossier, sinon celle de l'équipe : sa mission en cours, ou à
        // défaut la seule mission non terminée qu'elle ait — il n'y a alors pas d'ambiguïté.
        val parDefaut = equipe.missionActive?.takeIf { it in connues }
            ?: missions.filter { equipe.id in it.mission.equipes && it.mission.statut != StatutMission.TERMINEE }.singleOrNull()?.mission?.id
        val parMission = siens.groupBy { d -> (d.mission?.takeIf { it in connues } ?: parDefaut) }
        val idsDeLEquipe = (missions.filter { equipe.id in it.mission.equipes }.map { it.mission.id } +
            listOfNotNull(equipe.missionActive?.takeIf { it in connues }) + parMission.keys.filterNotNull()).distinct()
        TravailDEquipe(
            equipe,
            // La mission en cours de l'équipe d'abord : c'est celle sur laquelle on est.
            idsDeLEquipe.sortedByDescending { it == equipe.missionActive }.map { id -> MissionDEquipe(connues.getValue(id), parMission[id].orEmpty()) },
            parMission[null].orEmpty(),
        )
    }
    val rangees = parEquipe.flatMap { t -> t.missions.map { it.mission.mission.id } }.toSet()
    val autres = missions.filter { it.mission.id !in rangees }.map { MissionDEquipe(it, emptyList()) }
    return parEquipe.filter { it.missions.isNotEmpty() || it.sansMission.isNotEmpty() } +
        if (autres.isEmpty()) emptyList() else listOf(TravailDEquipe(null, autres, emptyList()))
}

/** Une compétence du catalogue partagé (`Competence`) : un thème, ou un sous-thème rangé sous
 * son `parent`. Jamais plus d'un niveau. */
@Serializable
data class Competence(
    val id: String,
    val nom: String = "",
    val parent: String? = null,
    val active: Boolean = true,
) {
    companion object {
        /** Les thèmes et leurs sous-thèmes, dans l'ordre du catalogue, compétences actives seulement. */
        fun arbre(catalogue: List<Competence>): List<Pair<Competence, List<Competence>>> {
            val actives = catalogue.filter { it.active }
            return actives.filter { it.parent == null }.map { theme -> theme to actives.filter { it.parent == theme.id } }
        }
    }
}

/** Un titre du catalogue (permis, diplôme, pièce) pour lequel on peut déposer un justificatif. */
@Serializable
data class TitreDuCatalogue(
    val id: String,
    val nom: String = "",
    val actif: Boolean = true,
    val conservation: Conservation? = null,
)

/** Ce que deviendra la pièce déposée : dit AVANT le dépôt, c'est ce qui en fait un choix. */
@Serializable
data class Conservation(val regime: String = "", val duree: String = "") {
    val detruiteApresVerification: Boolean get() = regime == "VERIFIER_DETRUIRE"
    val phrase: String
        get() = if (detruiteApresVerification) "Ce document sera détruit dès qu'il aura été vérifié."
        else if (duree.isNotBlank()) "Ce document sera conservé : ${duree.lowercase()}." else "Ce document sera conservé par votre association."
}

/** Le profil que la personne corrige elle-même. */
data class Profil(val prenom: String, val nom: String, val telephone: String)

/** Les erreurs d'un changement de mot de passe, par champ. Le serveur revérifie la robustesse. */
fun validerMotDePasse(ancien: String?, nouveau: String, confirmation: String): Map<String, String> = buildMap {
    if (ancien != null && ancien.isEmpty()) put("old_password", "Indiquez votre mot de passe actuel.")
    if (nouveau.length < 8) put("new_password", "Au moins 8 caractères.")
    else if (nouveau != confirmation) put("confirmation", "Les deux saisies ne sont pas identiques.")
}
