package fr.assistacrise.mobile

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.Inscription
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.MissionAffichee
import fr.assistacrise.mobile.domaine.MotifArret
import fr.assistacrise.mobile.domaine.PositionMembre
import fr.assistacrise.mobile.domaine.Releve
import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.StatutMission
import fr.assistacrise.mobile.domaine.superposerLaFile
import fr.assistacrise.mobile.domaine.validerInscription
import fr.assistacrise.mobile.donnees.Reponse
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Un formulaire en cours : envoi, erreur générale, erreurs par champ (clés de l'API). */
data class EtatFormulaire(
    val enCours: Boolean = false,
    val erreur: String? = null,
    val champs: Map<String, String> = emptyMap(),
)

enum class Ecran { CONNEXION, INSCRIPTION, MISSIONS, EQUIPES, MESSAGERIE, CARTE, COMPTE }

class ModeleApplication(private val app: Application) : ViewModel() {

    val compte = app.session.compte
    val lien = app.lien.etat
    val file = app.file.actions
    val equipes = app.equipes.equipes
    val fils = app.equipes.fils
    val suivi = app.suivi.etat
    val missions: StateFlow<List<MissionAffichee>> =
        combine(app.depot.missions, app.file.actions, ::superposerLaFile)
            .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    /** Faux tant que la session du lancement précédent n'a pas été relue du disque. */
    var pret by mutableStateOf(false); private set
    var ecran by mutableStateOf(Ecran.CONNEXION); private set
    var connexion by mutableStateOf(EtatFormulaire()); private set
    var inscription by mutableStateOf(EtatFormulaire()); private set
    var synchronisation by mutableStateOf(false); private set

    /** L'équipe dont la messagerie est ouverte. */
    var equipeOuverte by mutableStateOf<String?>(null); private set
    var positions by mutableStateOf<List<PositionMembre>>(emptyList()); private set

    /** Message passager, affiché une fois puis effacé par l'écran. */
    var message by mutableStateOf<String?>(null); private set

    private val verrouSynchro = Mutex()

    init {
        viewModelScope.launch {
            app.session.restaurer()
            app.file.restaurer()
            app.depot.restaurer()
            app.equipes.restaurer()
            app.suivi.restaurer()
            // Le suivi était actif quand l'application a été fermée : il reprend.
            if (compte.value != null && suivi.value.actif) ServiceSuivi.demarrer(app)
            pret = true
            if (compte.value != null) synchroniser(force = true, bavard = false)
        }
        viewModelScope.launch {
            app.reseau.present.collect { present ->
                app.lien.reseau(present)
                // Le réseau revient : c'est le moment d'envoyer ce qui attendait.
                if (present && pret && compte.value != null) synchroniser(force = true, bavard = false)
            }
        }
        viewModelScope.launch {
            // Tant que quelque chose attend, on retente au rythme du recul de la file. Sinon
            // on relit simplement le serveur de temps en temps : c'est ainsi qu'un engagement
            // décidé par un cadre arrive jusqu'au téléphone et démarre le suivi.
            var tours = 0
            while (true) {
                delay(15_000)
                tours++
                if (compte.value == null) continue
                val enAttente = file.value.any { it.etat == EtatAction.EN_ATTENTE }
                if (enAttente || tours % 4 == 0) synchroniser(force = false, bavard = false)
            }
        }
    }

    fun aller(vers: Ecran) {
        ecran = vers
        connexion = EtatFormulaire()
        inscription = EtatFormulaire()
    }

    fun messageLu() { message = null }

    // --- Compte --------------------------------------------------------------------------

    fun connecter(email: String, motDePasse: String) {
        if (connexion.enCours) return
        if (email.isBlank() || motDePasse.isEmpty()) {
            connexion = EtatFormulaire(erreur = "Indiquez votre adresse e-mail et votre mot de passe.")
            return
        }
        connexion = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            connexion = when (val r = app.api.connecter(email, motDePasse)) {
                is Reponse.Ok -> { ouvrir(); EtatFormulaire() }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message)
                is Reponse.Injoignable -> EtatFormulaire(erreur = r.message)
            }
        }
    }

    fun inscrire(saisie: Inscription) {
        if (inscription.enCours) return
        val erreurs = validerInscription(saisie)
        if (erreurs.isNotEmpty()) {
            inscription = EtatFormulaire(erreur = "Corrigez les champs signalés.", champs = erreurs)
            return
        }
        inscription = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            when (val r = app.api.inscrire(saisie)) {
                is Reponse.Ok -> {
                    // Un compte de particulier est utilisable tout de suite : on connecte
                    // la personne plutôt que de lui faire ressaisir ce qu'elle vient de taper.
                    when (app.api.connecter(saisie.email, saisie.motDePasse)) {
                        is Reponse.Ok -> {
                            ouvrir()
                            message = "Compte créé. Un e-mail de bienvenue vous a été envoyé."
                        }
                        else -> {
                            aller(Ecran.CONNEXION)
                            message = "Compte créé. Consultez vos e-mails, puis connectez-vous."
                        }
                    }
                    inscription = EtatFormulaire()
                }
                is Reponse.Refus -> inscription = EtatFormulaire(
                    erreur = if (r.champs.isEmpty()) r.message else "Corrigez les champs signalés.",
                    champs = r.champs,
                )
                is Reponse.Injoignable -> inscription = EtatFormulaire(erreur = r.message)
            }
        }
    }

    fun demanderNouveauMotDePasse(email: String) {
        viewModelScope.launch {
            message = when (val r = app.api.demanderNouveauMotDePasse(email)) {
                is Reponse.Ok -> "Si un compte existe pour cette adresse, un e-mail vient de lui être envoyé."
                is Reponse.Refus -> r.message
                is Reponse.Injoignable -> r.message
            }
        }
    }

    fun deconnecter() {
        viewModelScope.launch {
            app.api.deconnecter()
            ServiceSuivi.arreter(app)
            app.depot.toutEffacer()
            app.equipes.toutEffacer()
            app.suivi.toutEffacer()
            app.file.toutEffacer()
            positions = emptyList()
            aller(Ecran.CONNEXION)
        }
    }

    private suspend fun ouvrir() {
        ecran = Ecran.MISSIONS
        synchroniser(force = true, bavard = false)
    }

    // --- Missions ------------------------------------------------------------------------

    fun actualiser() {
        viewModelScope.launch { synchroniser(force = true, bavard = true) }
    }

    fun declarerStatut(mission: Mission, statut: StatutMission) {
        viewModelScope.launch {
            app.depot.declarerStatut(mission, statut)   // sur disque avant tout envoi
            synchroniser(force = true, bavard = false)
        }
    }

    fun ecarter(idAction: String) {
        viewModelScope.launch { app.file.retirer(idAction) }
    }

    /**
     * Envoie la file puis relit les missions. `bavard` : dire le résultat à la personne
     * (elle l'a demandé) ; sinon l'indicateur de lien suffit — on n'affiche pas une erreur
     * toutes les quinze secondes à quelqu'un qui est dans un tunnel.
     */
    private suspend fun synchroniser(force: Boolean, bavard: Boolean) = verrouSynchro.withLock {
        synchronisation = true
        try {
            app.synchro.envoyerLaFile(force)
            val r = app.depot.rafraichir()
            app.lien.echange(r !is Reponse.Injoignable)
            when (r) {
                is Reponse.Ok -> {
                    app.api.moi()
                    val e = app.equipes.rafraichir()
                    piloterLeSuivi(if (e is Reponse.Ok) equipes.value else null)
                }
                is Reponse.Refus -> if (r.code == 401) {
                    // La session a été fermée par le client : retour à la connexion, en le disant.
                    aller(Ecran.CONNEXION)
                    message = r.message
                } else if (bavard) message = r.message
                is Reponse.Injoignable -> {
                    piloterLeSuivi(null)
                    if (bavard) message = r.message
                }
            }
        } finally {
            synchronisation = false
        }
    }

    // --- Équipes et messagerie -----------------------------------------------------------

    fun ouvrirMessagerie(equipe: Equipe) {
        equipeOuverte = equipe.id
        ecran = Ecran.MESSAGERIE
    }

    /** Relit le fil ouvert. Appelé en boucle par l'écran tant qu'il est affiché. */
    suspend fun relireLeFil() {
        val id = equipeOuverte ?: return
        val r = app.equipes.rafraichirFil(id)
        app.lien.echange(r !is Reponse.Injoignable)
    }

    fun ecrire(equipe: Equipe, texte: String) {
        if (texte.isBlank()) return
        viewModelScope.launch {
            app.equipes.ecrire(equipe, texte)          // sur disque avant tout envoi
            verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
        }
    }

    // --- Carte et suivi ------------------------------------------------------------------

    fun chargerLesPositions() {
        viewModelScope.launch {
            when (val r = app.api.positionsEquipes()) {
                is Reponse.Ok -> {
                    // Sans moi : ma position est déjà le point bleu clair de la carte.
                    positions = r.valeur.filter { it.latitude != null && it.longitude != null && it.utilisateur != compte.value?.id }
                    app.lien.echange(true)
                }
                is Reponse.Refus -> Unit
                is Reponse.Injoignable -> app.lien.echange(false)
            }
        }
    }

    /**
     * La carte vient de lire ma position : je la partage avec mes équipes, si j'en ai. Le
     * serveur le veut ainsi — la position se déclare à l'occasion d'un geste, jamais par un
     * traçage silencieux (`MaPositionView`). Le suivi continu, lui, est le service.
     */
    fun partagerMaPosition(releve: Releve) {
        if (equipes.value.isEmpty()) return
        viewModelScope.launch {
            app.file.remplacer(ActionEnAttente.GENRE_POSITION, "moi", "${releve.latitude},${releve.longitude}", "Ma position")
            verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
            chargerLesPositions()
        }
    }

    /** La personne accepte, ou retire, le suivi en mission. */
    fun consentirAuSuivi(oui: Boolean) {
        viewModelScope.launch {
            app.suivi.consentir(oui)
            if (oui) { app.suivi.reprendre(); piloterLeSuivi(equipes.value) }
            else { app.suivi.arreterALaMain(equipes.value); ServiceSuivi.arreter(app) }
        }
    }

    fun arreterLeSuivi() {
        viewModelScope.launch {
            app.suivi.arreterALaMain(equipes.value)
            ServiceSuivi.arreter(app)
        }
    }

    fun reprendreLeSuivi() {
        viewModelScope.launch { app.suivi.reprendre(); piloterLeSuivi(equipes.value) }
    }

    /** `connues` : mes équipes telles que le serveur vient de les donner, ou `null` s'il n'a pas répondu. */
    private suspend fun piloterLeSuivi(connues: List<Equipe>?) {
        when (app.suivi.arreterSiBesoin(connues)) {
            MotifArret.FIN_D_ENGAGEMENT -> { ServiceSuivi.arreter(app); message = "Fin d'engagement : le suivi de position est arrêté." }
            MotifArret.PLAFOND -> { ServiceSuivi.arreter(app); message = "Le suivi de position s'est arrêté après douze heures." }
            else -> Unit
        }
        if (connues != null && app.suivi.demarrerSiBesoin(connues)) {
            if (ServiceSuivi.autorise(app)) {
                ServiceSuivi.demarrer(app)
                message = "Votre équipe est engagée : votre position est partagée."
            } else {
                // Consentement donné mais permission retirée depuis dans les réglages.
                app.suivi.arreterALaMain(connues)
            }
        }
    }

    companion object {
        val Fabrique: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                ModeleApplication(this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as Application)
            }
        }
    }
}
