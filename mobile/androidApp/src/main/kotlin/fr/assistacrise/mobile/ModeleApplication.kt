package fr.assistacrise.mobile

import fr.assistacrise.mobile.domaine.TypeMessageTerrain
import fr.assistacrise.mobile.domaine.Constat
import fr.assistacrise.mobile.donnees.DepotDegats
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import fr.assistacrise.mobile.domaine.AbonnementAlerte
import fr.assistacrise.mobile.domaine.Collectivite
import fr.assistacrise.mobile.domaine.Alerte
import fr.assistacrise.mobile.domaine.Creneau
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.Etape
import fr.assistacrise.mobile.domaine.Fiche
import fr.assistacrise.mobile.domaine.Notification
import fr.assistacrise.mobile.domaine.Profil
import fr.assistacrise.mobile.domaine.validerMotDePasse
import fr.assistacrise.mobile.domaine.Depot
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.GenreDepot
import fr.assistacrise.mobile.domaine.validerDepot
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.Inscription
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.Verdict
import fr.assistacrise.mobile.domaine.jetonDeMobilisation
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
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Un formulaire en cours : envoi, erreur générale, erreurs par champ (clés de l'API). */
data class EtatFormulaire(
    val enCours: Boolean = false,
    val erreur: String? = null,
    val champs: Map<String, String> = emptyMap(),
)

/** Où en est la connexion. Le code n'est demandé qu'aux comptes qui en ont un. */
enum class EtapeConnexion { ADRESSE, CODE, MOT_DE_PASSE }

enum class Ecran {
    CONNEXION, INSCRIPTION, MISSIONS, EQUIPES, MESSAGERIE, CARTE, AIDE, DEPOT, COMPTE,
    NOTIFICATIONS, NOTIFICATION, DISPONIBILITES, FICHE, INTERVENTIONS, DOSSIER,
    SCANNER, VERDICT, MOBILISATIONS, MON_COMPTE, DEGATS, RADIO_AVANCEE, RADIO_CONVERSATION,
}

class ModeleApplication(private val app: Application) : ViewModel() {

    val compte = app.session.compte
    val lien = app.lien.etat
    /** La file affichée : sans les messages radio entendus en attente de remise au serveur, qui
     * ne sont pas des envois de la personne (ils partent seuls, 23/11/2026). */
    val file: StateFlow<List<fr.assistacrise.mobile.domaine.ActionEnAttente>> = app.file.actions
        .map { l -> l.filter { it.genre != fr.assistacrise.mobile.domaine.ActionEnAttente.GENRE_ENTENDU_RADIO } }
        .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())
    val equipes = app.equipes.equipes

    // --- Non-lus et mentions de la messagerie d'équipe (23/11/2026) ---------------------------
    // « Le petit chiffre sur l'enveloppe, puis le moyen (chat, Meshtastic, MeshCore), puis le
    // canal. » Ce qu'on a lu, équipe par équipe : un horodatage, rien de personnel.
    private val lecturesEquipes = app.getSharedPreferences("lectures-equipes", android.content.Context.MODE_PRIVATE)
    private val _luesEquipes = MutableStateFlow(lecturesEquipes.all.mapNotNull { (k, v) -> (v as? Long)?.let { k to it } }.toMap())

    data class NonLus(val messages: Int = 0, val mentions: Int = 0)

    /** Par équipe : messages non lus (hors les miens), et parmi eux ceux qui me mentionnent. Une
     * équipe jamais ouverte sur ce téléphone part de zéro (pas tout l'historique d'un coup). */
    val nonLusEquipes: StateFlow<Map<String, NonLus>> = combine(app.equipes.fils, _luesEquipes) { fils, lues ->
        val noms = app.mesNoms()
        fils.mapValues { (id, fil) ->
            val depuis = lues[id] ?: return@mapValues NonLus()
            val nouveaux = fil.filter { !it.moi && it.horodatage > depuis }
            NonLus(nouveaux.size, nouveaux.count { fr.assistacrise.mobile.domaine.Mentions.mentionne(it.texte, noms) })
        }
    }.stateIn(viewModelScope, SharingStarted.Eagerly, emptyMap())

    init {
        // Le point de départ d'une équipe jamais ouverte ici : son dernier message connu.
        viewModelScope.launch {
            app.equipes.fils.collect { fils ->
                val manquantes = fils.filterKeys { it !in _luesEquipes.value }
                if (manquantes.isNotEmpty()) {
                    val depart = manquantes.mapValues { (_, fil) -> fil.maxOfOrNull { it.horodatage } ?: System.currentTimeMillis() }
                    lecturesEquipes.edit().apply { depart.forEach { (k, v) -> putLong(k, v) } }.apply()
                    _luesEquipes.value = _luesEquipes.value + depart
                }
            }
        }
    }

    /** L'équipe est lue jusqu'à son dernier message. */
    fun marquerEquipeLue(id: String) {
        val dernier = app.equipes.fils.value[id]?.maxOfOrNull { it.horodatage } ?: System.currentTimeMillis()
        val t = maxOf(dernier, _luesEquipes.value[id] ?: 0L)
        lecturesEquipes.edit().putLong(id, t).apply()
        _luesEquipes.value = _luesEquipes.value + (id to t)
    }

    val mentionsRadio = app.messagerieRadio.mentions

    /** Le chiffre de l'enveloppe : tout ce qui n'est pas lu (équipes et radio), et les mentions. */
    val totalMessages: StateFlow<NonLus> = combine(nonLusEquipes, app.messagerieRadio.nonLus, app.messagerieRadio.mentions) { eq, radio, men ->
        NonLus(eq.values.sumOf { it.messages } + radio.values.sum(), eq.values.sumOf { it.mentions } + men.values.sum())
    }.stateIn(viewModelScope, SharingStarted.Eagerly, NonLus())
    val fils = app.equipes.fils
    val suivi = app.suivi.etat
    /** Les deux liaisons radio (23/11/2026) : Meshtastic puis MeshCore. */
    val radios = app.radio.etats
    val radiosTrouvees = app.radio.trouvees
    val rechercheRadio = app.radio.recherche
    val erreurRechercheRadio = app.radio.erreurRecherche
    val crises = app.citoyen.crises
    val informations = app.citoyen.informations
    val typesDemande = app.citoyen.typesDemande
    val typesInformation = app.citoyen.typesInformation
    val notifications = app.notifications.notifications
    val grille = app.benevole.grille
    val fiche = app.benevole.fiche
    val titres = app.benevole.titres
    val dossiers = app.benevole.dossiers
    val typesOffre = app.citoyen.typesOffre
    val mobilisations = app.benevole.mobilisations
    val catalogue = app.benevole.catalogue
    val catalogueCompetences = app.benevole.competences
    val commentaires = app.dossiers.commentaires
    val photos = app.dossiers.photos
    val missions: StateFlow<List<MissionAffichee>> =
        combine(app.depot.missions, app.file.actions, ::superposerLaFile)
            .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    /** Faux tant que la session du lancement précédent n'a pas été relue du disque. */
    var pret by mutableStateOf(false); private set
    var ecran by mutableStateOf(Ecran.CONNEXION); private set
    var connexion by mutableStateOf(EtatFormulaire()); private set
    var etapeConnexion by mutableStateOf(EtapeConnexion.ADRESSE); private set
    /** Preuve que le code de sécurité a été donné, à joindre au mot de passe (cinq minutes). */
    private var jetonEtape = ""
    var inscription by mutableStateOf(EtatFormulaire()); private set
    var synchronisation by mutableStateOf(false); private set

    /** L'équipe dont la messagerie est ouverte. */
    var equipeOuverte by mutableStateOf<String?>(null); private set
    var positions by mutableStateOf<List<PositionMembre>>(emptyList()); private set

    /** Le dépôt en cours de saisie : quel geste, sur quelle crise. */
    var depotOuvert by mutableStateOf<Pair<GenreDepot, Crise>?>(null); private set
    var depot by mutableStateOf(EtatFormulaire()); private set

    /** Combien de notifications je n'ai pas encore eues sous les yeux : la pastille. */
    var nonVues by mutableStateOf(0); private set
    var notificationOuverte by mutableStateOf<String?>(null); private set

    /** Un écran du bénévole attend le serveur (grille, fiche, dossiers). */
    var chargement by mutableStateOf(false); private set
    /** Le serveur n'a pas répondu à cet écran : ce qu'il montre date, ou manque. */
    var horsLigne by mutableStateOf(false); private set
    /** La case de la grille en cours d'envoi (`date|créneau`) : elle seule est désactivée. */
    var caseEnCours by mutableStateOf<String?>(null); private set
    var formulaireFiche by mutableStateOf(EtatFormulaire()); private set

    /** Le dossier ouvert, et l'écran d'où on y est venu (pour y revenir). */
    var dossierOuvert by mutableStateOf<String?>(null); private set
    var retourDuDossier by mutableStateOf(Ecran.MISSIONS); private set
    /** Une photo est en cours de préparation (réduction, position, empreinte). */
    var photoEnCours by mutableStateOf(false); private set
    /** Vignettes déjà chargées, par identifiant de photo ou clé de photo en attente. En mémoire seulement. */
    val vignettes = mutableStateMapOf<String, ImageBitmap>()
    /** Le lieu touché sur la carte, pour le dépôt en cours. `null` : la position du moment. */
    var lieuChoisi by mutableStateOf<Releve?>(null); private set
    var retourDuDepot by mutableStateOf(Ecran.AIDE); private set

    /** Le verdict du dernier QR code lu. `null` : pas de réponse du serveur — on ne sait pas. */
    var verdict by mutableStateOf<Verdict?>(null); private set
    var verificationEnCours by mutableStateOf(false); private set
    var erreurScanner by mutableStateOf<String?>(null); private set
    private var retourDuScanner = Ecran.CONNEXION

    /** L'application est-elle à l'écran ? Ce qu'on a sous les yeux ne fait pas sonner. */
    private var visible = false

    /** Message passager, affiché une fois puis effacé par l'écran. */
    var message by mutableStateOf<String?>(null); private set

    private val verrouSynchro = Mutex()

    init {
        viewModelScope.launch {
            app.restaurer()
            nonVues = app.notifications.nonVues()
            if (compte.value != null) Alertes.planifierLaVeille(app)
            // Le suivi était actif quand l'application a été fermée : il reprend.
            if (compte.value != null) app.radio.reprendre()
            lireModeRadioAvance()
            // Le suivi était actif, ou une radio est choisie : le service de terrain reprend.
            if (compte.value != null) ServiceTerrain.actualiser(app)
            pret = true
            if (compte.value != null) synchroniser(force = true, bavard = false)
        }
        // Bascule vers le satellite, et retour : l'écran suit, et la personne sait où elle est.
        viewModelScope.launch {
            var precedent = app.bascule.etat.value
            app.bascule.etat.collect { e ->
                if (e == precedent) return@collect
                when (e) {
                    fr.assistacrise.mobile.donnees.BasculeServeur.Etat.SATELLITE -> {
                        message = "Le central ne répond pas : vous êtes sur le satellite « ${app.serveur.satellite.value?.nom ?: "du site"} ». " +
                            "Connectez-vous avec vos identifiants habituels."
                        if (compte.value == null) aller(Ecran.CONNEXION)
                    }
                    fr.assistacrise.mobile.donnees.BasculeServeur.Etat.CENTRAL -> if (precedent == fr.assistacrise.mobile.donnees.BasculeServeur.Etat.SATELLITE) {
                        message = "Le central répond de nouveau : retour au central."
                        if (compte.value != null) { ecran = Ecran.MISSIONS; synchroniser(force = true, bavard = false) }
                    }
                    else -> Unit
                }
                precedent = e
            }
        }
        // Sur le satellite : le central est resondé chaque minute, on y revient dès qu'il répond.
        viewModelScope.launch {
            while (true) {
                delay(60_000)
                runCatching { app.bascule.verifierRetour() }
            }
        }
        viewModelScope.launch {
            app.reseau.present.collect { present ->
                app.lien.reseau(present)
                if (present) verifierLaMiseAJour()
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
                // Un échec isolé laisse un doute : on le lève tout de suite, sans attendre
                // le tour normal.
                if (enAttente || app.lien.enDoute || tours % 4 == 0) synchroniser(force = app.lien.enDoute, bavard = false)
            }
        }
    }

    fun aller(vers: Ecran) {
        ecran = vers
        connexion = EtatFormulaire()
        inscription = EtatFormulaire()
        depot = EtatFormulaire()
    }

    fun messageLu() { message = null }

    /**
     * L'application revient à l'écran. Android a pu l'endormir entre-temps : ce qu'elle
     * affiche date, et ses connexions sont peut-être mortes. On relit tout de suite.
     */
    fun auPremierPlan() {
        visible = true
        app.premierPlan = true
        if (pret && compte.value != null) viewModelScope.launch { synchroniser(force = true, bavard = false) }
    }

    fun enArrierePlan() { visible = false; app.premierPlan = false }

    // --- Compte --------------------------------------------------------------------------

    /**
     * Connexion en étapes : l'adresse, puis le code de sécurité si le compte est protégé,
     * puis le mot de passe. L'ordre est voulu — tant que le code n'a pas été donné, le
     * serveur ne regarde pas le mot de passe.
     */
    fun continuerLaConnexion(email: String) {
        if (connexion.enCours) return
        if (email.isBlank()) {
            connexion = EtatFormulaire(erreur = "Indiquez votre adresse e-mail.")
            return
        }
        connexion = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            connexion = when (val r = app.api.debutConnexion(email)) {
                is Reponse.Ok -> {
                    etapeConnexion = if (r.valeur) EtapeConnexion.CODE else EtapeConnexion.MOT_DE_PASSE
                    EtatFormulaire()
                }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message)
                is Reponse.Injoignable -> EtatFormulaire(erreur = r.message)
            }
        }
    }

    fun donnerLeCode(email: String, code: String) {
        if (connexion.enCours) return
        if (code.trim().length < 6) {
            connexion = EtatFormulaire(erreur = "Saisissez les 6 chiffres de votre application d'authentification.")
            return
        }
        connexion = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            connexion = when (val r = app.api.verifierCode(email, code)) {
                is Reponse.Ok -> {
                    jetonEtape = r.valeur
                    etapeConnexion = EtapeConnexion.MOT_DE_PASSE
                    EtatFormulaire()
                }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message)
                is Reponse.Injoignable -> EtatFormulaire(erreur = r.message)
            }
        }
    }

    /** Ce que le serveur a répondu à « renvoyer le code » (la même phrase pour toute adresse). */
    var messageEnvoiCode by mutableStateOf<String?>(null); private set

    fun renvoyerLeCode(email: String) {
        if (connexion.enCours) return
        viewModelScope.launch {
            messageEnvoiCode = when (val r = app.api.renvoyerCode(email)) {
                is Reponse.Ok -> r.valeur
                is Reponse.Refus -> r.message
                is Reponse.Injoignable -> r.message
            }
        }
    }

    /** Revenir à l'adresse : ce qui a été donné ensuite est oublié. */
    fun recommencerLaConnexion() {
        jetonEtape = ""
        messageEnvoiCode = null
        etapeConnexion = EtapeConnexion.ADRESSE
        connexion = EtatFormulaire()
    }

    fun connecter(email: String, motDePasse: String) {
        if (connexion.enCours) return
        if (email.isBlank() || motDePasse.isEmpty()) {
            connexion = EtatFormulaire(erreur = "Indiquez votre adresse e-mail et votre mot de passe.")
            return
        }
        connexion = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            connexion = when (val r = app.api.connecter(email, motDePasse, jetonEtape)) {
                is Reponse.Ok -> {
                    jetonEtape = ""
                    etapeConnexion = EtapeConnexion.ADRESSE
                    ouvrir()
                    EtatFormulaire()
                }
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

    // --- Formation (22/11/2026) -------------------------------------------------------------

    /** « PROD » ou « DEMO » : la zone de travail, comme la bascule « Formation » du site. */
    val zone = app.session.environnement

    /**
     * Passe en formation (données fictives de démonstration) ou revient aux données réelles.
     * Refusé tant que des envois attendent : ils appartiennent à la zone où ils ont été écrits.
     * Les copies locales de l'autre zone sont effacées, puis tout est relu ; le suivi en cours
     * est coupé (un engagement de la nouvelle zone le relancera). La radio, elle, reste : c'est
     * la même radio réelle, et ses canaux de démonstration sont déjà ceux des équipes fictives.
     */
    fun basculerFormation(oui: Boolean) {
        viewModelScope.launch {
            val zoneVoulue = if (oui) fr.assistacrise.mobile.donnees.Session.DEMO else fr.assistacrise.mobile.donnees.Session.PROD
            if (zone.value == zoneVoulue) return@launch
            if (oui && compte.value?.peutSeFormer != true) { message = "La formation n'est pas ouverte à votre compte."; return@launch }
            if (app.file.actions.value.any { it.etat == fr.assistacrise.mobile.domaine.EtatAction.EN_ATTENTE }) {
                message = "Des envois attendent encore le réseau : ils doivent partir avant de changer de zone."
                return@launch
            }
            verrouSynchro.withLock {
                app.suivi.couper()
                app.session.changerDEnvironnement(zoneVoulue)
                app.notifications.toutEffacer()
                app.depot.toutEffacer()
                app.equipes.toutEffacer()
                app.terrain.toutEffacer()
                app.points.toutEffacer()
                app.citoyen.toutEffacer()
                app.alertes.toutRetirer()
                app.veille.toutEffacer()
                app.dossiers.toutEffacer(file.value)
                vignettes.clear()
                app.benevole.toutEffacer()
                app.file.toutEffacer()
                nonVues = 0
                positions = emptyList()
            }
            ServiceTerrain.actualiser(app)
            message = if (oui) "Formation : vous travaillez sur des données fictives." else "Retour aux données réelles."
            synchroniser(force = true, bavard = true)
        }
    }

    fun deconnecter() {
        viewModelScope.launch {
            // Tant que la session vit : dire au serveur que ce téléphone ne joint plus ce compte.
            Alertes.arreterLaVeille(app)
            app.notifications.toutEffacer()
            app.api.deconnecter()
            ServiceTerrain.actualiser(app)
            app.radio.toutDeconnecter()
            app.depot.toutEffacer()
            app.equipes.toutEffacer()
            app.suivi.toutEffacer()
            app.terrain.toutEffacer()
            app.points.toutEffacer()
            app.messagerieRadio.toutEffacer()
            app.citoyen.toutEffacer()
            app.alertes.toutRetirer()
            app.veille.toutEffacer()
            app.dossiers.toutEffacer(file.value)
            vignettes.clear()
            app.benevole.toutEffacer()
            nonVues = 0
            app.file.toutEffacer()
            positions = emptyList()
            aller(Ecran.CONNEXION)
        }
    }

    // --- Satellite du site, quand le central ne répond pas (23/11/2026) ---------------------

    val etatServeur = app.bascule.etat
    val satelliteActif = app.serveur.satellite
    var adresseSatellite by mutableStateOf(""); private set
    var refusAdresseSatellite by mutableStateOf<String?>(null); private set
    var essaiSatelliteEnCours by mutableStateOf(false); private set

    fun saisirAdresseSatellite(texte: String) { adresseSatellite = texte; refusAdresseSatellite = null }

    fun essayerAdresseSatellite() {
        essaiSatelliteEnCours = true
        viewModelScope.launch {
            refusAdresseSatellite = app.bascule.essayerAdresse(adresseSatellite)
            essaiSatelliteEnCours = false
        }
    }

    fun chercherLeSatellite() = app.lancerLaRecherche()

    fun continuerSansReseau() = app.bascule.abandonner()

    fun seConnecterAUnSatellite() = app.bascule.demanderAdresse()

    /** Android affichera-t-il nos notifications ? (Relu à chaque affichage de l'écran Compte.) */
    val notificationsAutorisees: Boolean get() = app.alertes.autorisees

    fun revenirAuCentral() {
        viewModelScope.launch { app.bascule.revenirAuCentral() }
    }

    private suspend fun ouvrir() {
        Alertes.planifierLaVeille(app)
        ecran = Ecran.MISSIONS
        synchroniser(force = true, bavard = false)
    }

    // --- Missions ------------------------------------------------------------------------

    fun actualiser() {
        viewModelScope.launch { synchroniser(force = true, bavard = true) }
    }

    /** Les points importants des crises, embarqués pour le GPS hors ligne. */
    val pointsCrise = app.points.points
    val cartesHorsLigne get() = app.cartes

    /** « Aller vers » a conduit jusqu'au point : on propose d'envoyer « Arrivé sur les lieux ». */
    fun arriveSurLesLieux(dossierId: String?) {
        envoyerMessageTerrain(TypeMessageTerrain.ARRIVE, dossiers.value.firstOrNull { it.id == dossierId })
    }

    // --- Utilisateur radio avancé (22/11/2026) -----------------------------------------------

    /**
     * La radio que les menus avancés et la messagerie radio regardent, quand le téléphone en
     * tient deux (23/11/2026). À défaut de choix, la première radio prête.
     */
    var protocoleRadio by mutableStateOf<fr.assistacrise.mobile.lien.Protocole?>(null); private set
    fun choisirRadio(protocole: fr.assistacrise.mobile.lien.Protocole) { protocoleRadio = protocole }
    val liaisonChoisie: LiaisonRadio get() =
        protocoleRadio?.let { app.radio.pour(it) }?.takeIf { it.etat.value.phase == LiaisonRadio.Phase.PRETE }
            ?: app.radio.pretes().firstOrNull() ?: app.radio.pour(protocoleRadio ?: fr.assistacrise.mobile.lien.Protocole.MESHTASTIC)
    val radio get() = liaisonChoisie.etat
    val radioAvance get() = liaisonChoisie.avance
    val piloteRadio get() = liaisonChoisie.piloteCourant
    fun piloteDe(protocole: fr.assistacrise.mobile.lien.Protocole) = app.radio.pour(protocole).piloteCourant
    /** L'équipe dont ce canal (de la radio choisie) est le canal géré par la plateforme. */
    fun equipeDuCanalRadio(index: Int) = app.radio.equipeDuCanal(liaisonChoisie.emplacement, index)
    private val preferences by lazy { app.getSharedPreferences("radio", android.content.Context.MODE_PRIVATE) }
    var modeRadioAvance by mutableStateOf(false); private set

    fun basculerModeRadioAvance(oui: Boolean) {
        modeRadioAvance = oui
        preferences.edit().putBoolean("avance", oui).apply()
    }

    fun lireModeRadioAvance() { modeRadioAvance = preferences.getBoolean("avance", false) }

    /**
     * Envoie à la radio des trames d'administration déjà construites, puis relit ce qu'elle a
     * gardé. `resume` dit ce qui part (sans jamais citer une clé).
     */
    fun envoyerALaRadio(trames: List<ByteArray>, resume: String, relire: Boolean = true) {
        viewModelScope.launch {
            val liaison = liaisonChoisie
            val ok = liaison.envoyerAdmin(trames)
            message = if (ok) "$resume : envoyé à la radio." else "$resume : la radio n'a pas pris la commande."
            if (ok && relire) { kotlinx.coroutines.delay(1_500); liaison.relireAvance() }
        }
    }

    // --- Messagerie radio (22/11/2026) ---------------------------------------------------------

    val conversationsRadio = app.messagerieRadio.conversations
    val nonLusRadio = app.messagerieRadio.nonLus
    var conversationRadio by mutableStateOf<String?>(null); private set

    // Le fil ouvert à l'écran, pour les notifications des messages radio (23/11/2026). Placé ICI,
    // après la déclaration de `conversationRadio` : viewModelScope démarre la coroutine sur-le-champ
    // (Main.immediate), et lire une propriété pas encore initialisée faisait planter l'application
    // au démarrage (0.18.0).
    init {
        viewModelScope.launch {
            androidx.compose.runtime.snapshotFlow { Triple(ecran, equipeOuverte, conversationRadio) }.collect { (e, eq, conv) ->
                app.equipeAffichee = eq.takeIf { e == Ecran.MESSAGERIE }
                app.messagerieRadio.ouverte = conv.takeIf { e == Ecran.RADIO_CONVERSATION }
            }
        }
    }

    fun ouvrirConversationRadio(cle: String) {
        conversationRadio = cle
        app.messagerieRadio.marquerLue(cle)
        aller(Ecran.RADIO_CONVERSATION)
    }

    fun fermerConversationRadio() {
        aller(Ecran.EQUIPES)
    }

    fun nomDuContactRadio(cle: String) = app.messagerieRadio.nomDuContact(cle)

    /** Notifier, ou non, les messages d'un canal radio (les messages directs le sont toujours). */
    fun canalRadioNotifie(cle: String) = app.messagerieRadio.notifie(cle)
    fun notifierCanalRadio(cle: String, oui: Boolean) = app.messagerieRadio.notifier(cle, oui)

    fun ecrireALaRadio(cle: String, texte: String) {
        viewModelScope.launch {
            val ok = app.messagerieRadio.envoyer(cle, texte)
            if (!ok) message = "La radio n'a pas pris le message (radio déconnectée, ou contact inconnu)."
        }
    }

    fun relireLaRadio() { viewModelScope.launch { if (!liaisonChoisie.relireAvance()) message = "La radio n'est pas prête." } }

    /** Le journal des messages de terrain envoyés de ce téléphone. */
    val journalTerrain = app.terrain.journal

    /**
     * Un message de terrain en un geste (22/11/2026). Part par la file : données si le
     * serveur répond, sinon sur le canal radio de l'équipe. La position est jointe si on en
     * connaît une (celle du suivi, ou la dernière du téléphone).
     */
    fun envoyerMessageTerrain(type: TypeMessageTerrain, dossier: fr.assistacrise.mobile.domaine.Dossier?, texte: String = "", nombre: Int? = null) {
        viewModelScope.launch {
            // L'équipe du dossier porte le message par radio ; à défaut, la première de mes équipes.
            val equipe = dossier?.equipe?.let { id -> equipes.value.firstOrNull { it.id == id } } ?: equipes.value.firstOrNull()
            val position = dernierePosition()
            try {
                app.terrain.envoyer(type, dossier?.mission, equipe?.id, texte, nombre, position?.first, position?.second, dossier?.id)
            } catch (e: IllegalArgumentException) {
                message = e.message; return@launch
            }
            message = if (type.prioritaire) "${type.libelle} : envoyé en priorité." else "${type.libelle} : envoyé."
            verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
        }
    }

    @android.annotation.SuppressLint("MissingPermission")   // vérifiée juste avant
    private fun dernierePosition(): Pair<Double, Double>? {
        app.suivi.etat.value.dernierEnvoi?.let { return it.latitude to it.longitude }
        if (!ServiceTerrain.positionAutorisee(app)) return null
        val lm = app.getSystemService(android.location.LocationManager::class.java) ?: return null
        return listOf(android.location.LocationManager.GPS_PROVIDER, android.location.LocationManager.NETWORK_PROVIDER)
            .mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
            .maxByOrNull { it.time }?.let { it.latitude to it.longitude }
    }

    fun declarerStatut(mission: Mission, statut: StatutMission) {
        viewModelScope.launch {
            app.depot.declarerStatut(mission, statut)   // sur disque avant tout envoi
            synchroniser(force = true, bavard = false)
        }
    }

    fun ecarter(idAction: String) {
        viewModelScope.launch {
            // Une photo écartée ne laisse pas ses octets derrière elle.
            file.value.firstOrNull { it.id == idAction }?.let { app.dossiers.oublierLesOctets(it) }
            app.file.retirer(idAction)
        }
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
                    app.citoyen.rafraichir()
                    // Les points des crises ouvertes, pour le GPS hors ligne.
                    app.points.rafraichir(crises.value.filter { it.ouverte }.map { it.id })
                    // Les dossiers de mes équipes : ils s'affichent sous les missions, et sur la carte.
                    if (equipes.value.isNotEmpty()) {
                        if (app.benevole.chargerLesDossiers(equipes.value.map { it.id }.toSet()) is Reponse.Ok) {
                            // Ce qui n'est plus à faire quitte le téléphone, photos et commentaires compris.
                            app.dossiers.garderSeulement(app.benevole.dossiers.value.map { it.id }.toSet())
                        }
                    }
                    compte.value?.id?.let { app.benevole.chargerLesMobilisations(it) }
                    // Les satellites de mon institution, gardés pour le jour où le central se tait.
                    if (app.serveur.satellite.value == null) {
                        (app.api.satellitesLocaux() as? Reponse.Ok)?.let { app.serveur.retenirConnus(it.valeur) }
                    }
                    veiller()
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

    // --- Notifications --------------------------------------------------------------------

    /**
     * Se présente au serveur, puis relève ce qui est nouveau. Ce que la personne a déjà sous
     * les yeux ne sonne pas : faire vibrer le téléphone pour le message qu'elle est en train
     * de lire, c'est lui apprendre à couper les notifications.
     */
    private suspend fun veiller() {
        app.notifications.presenter("ANDROID", BuildConfig.VERSION_NAME, app.alertes.autorisees)
        app.veille.relever(relire = false) { alerte ->
            val sousLesYeux = visible && when (alerte.genre) {
                Alerte.Genre.MESSAGE -> ecran == Ecran.MESSAGERIE && equipeOuverte == alerte.cible
                Alerte.Genre.NOTIFICATION -> ecran == Ecran.NOTIFICATIONS
                Alerte.Genre.MISSION -> ecran == Ecran.MISSIONS
                Alerte.Genre.DOSSIER -> ecran == Ecran.DOSSIER && dossierOuvert == alerte.cible
            }
            if (sousLesYeux) {
                if (alerte.genre == Alerte.Genre.NOTIFICATION) app.notifications.noter(Etape.VUE, listOf(alerte.cible))
                true
            } else app.alertes.afficher(alerte)
        }
        nonVues = app.notifications.nonVues()
    }

    /** La personne ouvre la liste : tout ce qui y figure est désormais « vu ». */
    fun ouvrirNotifications() {
        ecran = Ecran.NOTIFICATIONS
        viewModelScope.launch {
            app.notifications.rafraichir()
            val aVoir = notifications.value.filter { it.dateVue == null }
            aVoir.forEach { app.alertes.retirer("n:${it.id}") }
            app.notifications.noter(Etape.VUE, aVoir.map { it.id })
            nonVues = app.notifications.nonVues()
        }
    }

    /** Elle en ouvre une : « lue ». */
    fun ouvrirNotification(id: String) {
        notificationOuverte = id
        ecran = Ecran.NOTIFICATION
        app.alertes.retirer("n:$id")
        viewModelScope.launch {
            app.notifications.noter(Etape.LUE, listOf(id))
            nonVues = app.notifications.nonVues()
        }
    }

    /** On a touché une notification du système : aller là où elle mène. */
    fun ouvrirDepuisAlerte(genre: String?, cible: String?) {
        if (compte.value == null || cible == null) return
        when (genre) {
            Alerte.Genre.NOTIFICATION.name -> ouvrirNotification(cible)
            Alerte.Genre.MESSAGE.name ->
                if (cible.startsWith(MessagerieRadio.CIBLE)) ouvrirConversationRadio(cible.removePrefix(MessagerieRadio.CIBLE))
                else { equipeOuverte = cible; ecran = Ecran.MESSAGERIE }
            Alerte.Genre.MISSION.name -> ecran = Ecran.MISSIONS
            Alerte.Genre.DOSSIER.name -> ouvrirDossier(cible)
        }
    }

    /** « Je ne suis pas disponible sur cette période » : une réponse, et elle exige le serveur. */
    fun repondreNon(notification: Notification) {
        val campagne = notification.campagne ?: return
        chargement = true
        viewModelScope.launch {
            when (val r = app.benevole.repondreIndisponible(campagne.id)) {
                is Reponse.Ok -> { app.notifications.rafraichir(); message = "C'est noté : vous ne serez pas relancé." }
                is Reponse.Refus -> message = r.message
                is Reponse.Injoignable -> message = "Pas de réseau : votre réponse n'est pas partie. Réessayez dès que vous captez."
            }
            chargement = false
        }
    }

    // --- Le bénévole : disponibilités, fiche, dossiers ------------------------------------------

    /** `campagne` : la grille s'ouvre sur SA période, et chaque case cochée lui vaut réponse. */
    fun ouvrirDisponibilites(campagne: String? = null) {
        ecran = Ecran.DISPONIBILITES
        chargerEcran { app.benevole.chargerLaGrille(campagne) }
    }

    fun basculerCreneau(date: String, creneau: Creneau?, disponible: Boolean) {
        if (caseEnCours != null) return
        caseEnCours = "$date|${creneau?.name ?: ""}"
        viewModelScope.launch {
            when (val r = app.benevole.declarer(date, creneau, disponible)) {
                is Reponse.Ok -> if (grille.value?.campagne != null) app.notifications.rafraichir()
                is Reponse.Refus -> message = r.message
                // La case n'a pas bougé, et on dit pourquoi : pas de disponibilité imaginaire.
                is Reponse.Injoignable -> message = "Pas de réseau : ce créneau n'est pas enregistré."
            }
            caseEnCours = null
        }
    }

    fun ouvrirFiche() {
        ecran = Ecran.FICHE
        formulaireFiche = EtatFormulaire()
        val id = compte.value?.id ?: return
        chargerEcran { app.benevole.chargerLaFiche(id) }
    }

    fun enregistrerFiche(saisie: Fiche) {
        formulaireFiche = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            formulaireFiche = when (val r = app.benevole.enregistrerLaFiche(saisie)) {
                is Reponse.Ok -> { message = "Fiche enregistrée."; EtatFormulaire() }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message, champs = r.champs)
                is Reponse.Injoignable -> EtatFormulaire(erreur = "Pas de réseau : votre fiche n'est pas enregistrée.")
            }
        }
    }

    fun ouvrirInterventions() {
        ecran = Ecran.INTERVENTIONS
        chargerEcran {
            // Mes équipes d'abord : affecté il y a une minute, je dois voir les dossiers tout de suite.
            app.equipes.rafraichir()
            app.benevole.chargerLesDossiers(equipes.value.map { it.id }.toSet())
        }
    }

    fun definirStatutDossier(dossier: Dossier, statut: String) {
        viewModelScope.launch {
            when (val r = app.benevole.definirStatut(dossier, statut)) {
                is Reponse.Ok -> Unit
                is Reponse.Refus -> message = r.message
                is Reponse.Injoignable -> message = "Pas de réseau : le statut n'a pas changé."
            }
        }
    }

    // --- Mon compte : profil, mot de passe, documents -----------------------------------------

    var formulaireProfil by mutableStateOf(EtatFormulaire()); private set
    var formulaireMotDePasse by mutableStateOf(EtatFormulaire()); private set
    var depotDocument by mutableStateOf(EtatFormulaire()); private set

    fun ouvrirMonCompte() {
        ecran = Ecran.MON_COMPTE
        formulaireProfil = EtatFormulaire(); formulaireMotDePasse = EtatFormulaire(); depotDocument = EtatFormulaire()
        val id = compte.value?.id ?: return
        chargerEcran {
            app.benevole.chargerLaFiche(id)          // dit si le compte a déjà un mot de passe
            app.benevole.chargerMesDocuments(id)
        }
    }

    fun enregistrerProfil(profil: Profil) {
        if (profil.nom.trim().length < 2) { formulaireProfil = EtatFormulaire(champs = mapOf("last_name" to "Indiquez votre nom.")); return }
        formulaireProfil = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            formulaireProfil = when (val r = app.api.modifierProfil(profil)) {
                is Reponse.Ok -> { message = "Profil enregistré."; EtatFormulaire() }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message, champs = r.champs)
                is Reponse.Injoignable -> EtatFormulaire(erreur = "Pas de réseau : votre profil n'est pas enregistré.")
            }
        }
    }

    /** `ancien == null` : compte sans mot de passe (créé par import), qui en choisit un. */
    // ── Alertes de la commune ──────────────────────────────────────────────────────────────
    // L'abonnement est un consentement : il se donne et se retire ici, pour soi-même. Rien n'en
    // est gardé sur le téléphone — la liste se relit au serveur à chaque ouverture de l'écran.
    var abonnementsAlerte by mutableStateOf<List<AbonnementAlerte>>(emptyList()); private set
    var collectivitesTrouvees by mutableStateOf<List<Collectivite>>(emptyList()); private set
    var erreurAbonnement by mutableStateOf<String?>(null); private set
    /** Dernière recherche lancée : une réponse arrivée après une frappe plus récente est ignorée. */
    private var rechercheDeCollectivite = ""

    fun chargerAbonnementsAlerte() {
        viewModelScope.launch {
            when (val r = app.api.mesAbonnementsAlerte()) {
                is Reponse.Ok -> { abonnementsAlerte = r.valeur; erreurAbonnement = null }
                is Reponse.Refus -> erreurAbonnement = r.message
                is Reponse.Injoignable -> erreurAbonnement = "Pas de réseau : vos abonnements ne peuvent pas être lus pour l'instant."
            }
        }
    }

    fun chercherCollectivites(recherche: String) {
        val q = recherche.trim()
        rechercheDeCollectivite = q
        if (q.length < 2) { collectivitesTrouvees = emptyList(); return }
        viewModelScope.launch {
            val r = app.api.collectivitesPourAlerte(q)
            if (q != rechercheDeCollectivite) return@launch
            if (r is Reponse.Ok) {
                val deja = abonnementsAlerte.map { it.id }.toSet()
                collectivitesTrouvees = r.valeur.filter { it.id !in deja }
            }
        }
    }

    fun sAbonnerAuxAlertes(idCollectivite: String, reussi: () -> Unit) {
        viewModelScope.launch {
            when (val r = app.api.sAbonnerAuxAlertes(idCollectivite)) {
                is Reponse.Ok -> { collectivitesTrouvees = emptyList(); rechercheDeCollectivite = ""; reussi(); chargerAbonnementsAlerte() }
                is Reponse.Refus -> erreurAbonnement = r.message
                is Reponse.Injoignable -> erreurAbonnement = "Pas de réseau : l'abonnement n'est pas enregistré."
            }
        }
    }

    fun seDesabonnerDesAlertes(idCollectivite: String) {
        viewModelScope.launch {
            when (val r = app.api.seDesabonnerDesAlertes(idCollectivite)) {
                is Reponse.Ok -> chargerAbonnementsAlerte()
                is Reponse.Refus -> erreurAbonnement = r.message
                is Reponse.Injoignable -> erreurAbonnement = "Pas de réseau : vous êtes toujours abonné."
            }
        }
    }

    fun changerMotDePasse(ancien: String?, nouveau: String, confirmation: String, reussi: () -> Unit) {
        val erreurs = validerMotDePasse(ancien, nouveau, confirmation)
        if (erreurs.isNotEmpty()) { formulaireMotDePasse = EtatFormulaire(champs = erreurs); return }
        formulaireMotDePasse = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            formulaireMotDePasse = when (val r = app.api.changerMotDePasse(ancien, nouveau)) {
                is Reponse.Ok -> {
                    message = "Mot de passe enregistré."
                    compte.value?.id?.let { app.benevole.chargerLaFiche(it) }
                    reussi(); EtatFormulaire()
                }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message, champs = r.champs)
                is Reponse.Injoignable -> EtatFormulaire(erreur = "Pas de réseau : votre mot de passe n'a pas changé.")
            }
        }
    }

    /**
     * Dépose une pièce. Elle part tout de suite ou pas du tout : une pièce d'identité n'attend
     * pas sur un téléphone, même chiffrée, qu'un réseau revienne.
     */
    fun deposerDocument(idCatalogue: String, octets: ByteArray, nomFichier: String, typeMime: String, dateObtention: String?, reussi: () -> Unit) {
        val id = compte.value?.id ?: return
        if (octets.size > 10 * 1024 * 1024) { depotDocument = EtatFormulaire(erreur = "Ce fichier dépasse 10 Mo. Photographiez le document, ou réduisez le fichier."); return }
        depotDocument = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            depotDocument = when (val r = app.benevole.deposerJustificatif(id, idCatalogue, octets, nomFichier, typeMime, dateObtention)) {
                is Reponse.Ok -> { message = "Document déposé. Votre encadrement va le vérifier."; reussi(); EtatFormulaire() }
                is Reponse.Refus -> EtatFormulaire(erreur = r.message, champs = r.champs)
                is Reponse.Injoignable -> EtatFormulaire(erreur = "Pas de réseau : le document n'est pas parti, et rien n'en est gardé sur ce téléphone. Réessayez dès que vous captez.")
            }
        }
    }

    // --- QR codes de mobilisation ------------------------------------------------------------

    /** Ouvert depuis l'écran de connexion aussi : lire un QR code ne demande pas de compte. */
    fun ouvrirScanner() {
        if (ecran !in setOf(Ecran.SCANNER, Ecran.VERDICT)) retourDuScanner = ecran
        erreurScanner = null
        ecran = Ecran.SCANNER
    }

    fun ouvrirMobilisations() {
        retourDuScanner = ecran
        ecran = Ecran.MOBILISATIONS
        // Ce qui est gardé s'affiche tout de suite ; le serveur dit ensuite si rien n'a été révoqué.
        viewModelScope.launch { compte.value?.id?.let { app.benevole.chargerLesMobilisations(it) } }
    }

    fun fermerScanner() { ecran = retourDuScanner }

    /**
     * Un QR code vient d'être lu — par la caméra de l'application, ou par celle du téléphone
     * qui nous a passé l'adresse. On n'ouvre jamais ce qu'il contient : on en tire le jeton.
     */
    fun qrLu(texte: String) {
        if (verificationEnCours) return
        val jeton = jetonDeMobilisation(texte)
        if (jeton == null) {
            // Dit sur l'écran du scanner, qui continue de lire : un autre QR code traînait dans le champ.
            erreurScanner = "Ce QR code n'est pas une attestation de mobilisation."
            return
        }
        if (ecran !in setOf(Ecran.SCANNER, Ecran.VERDICT)) retourDuScanner = ecran
        verdict = null
        erreurScanner = null
        verificationEnCours = true
        ecran = Ecran.VERDICT
        viewModelScope.launch {
            when (val r = app.api.verifierMobilisation(jeton)) {
                is Reponse.Ok -> verdict = r.valeur
                is Reponse.Refus -> erreurScanner = r.message
                is Reponse.Injoignable -> erreurScanner = "Pas de réseau : la vérification demande le serveur. Ce QR code n'est donc ni confirmé ni infirmé."
            }
            verificationEnCours = false
        }
    }

    // --- Un dossier : commentaires et photos -----------------------------------------------------

    fun ouvrirDossier(id: String) {
        if (ecran != Ecran.DOSSIER) retourDuDossier = ecran
        dossierOuvert = id
        ecran = Ecran.DOSSIER
        viewModelScope.launch {
            app.dossiers.restaurer(id)                  // ce qu'on en savait, tout de suite
            app.lien.echange(app.dossiers.rafraichir(id) !is Reponse.Injoignable)
        }
    }

    fun fermerDossier() { ecran = retourDuDossier }

    fun commenter(dossier: Dossier, texte: String) {
        if (texte.isBlank()) return
        viewModelScope.launch {
            app.dossiers.commenter(dossier, texte)       // sur disque avant tout envoi
            verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
            app.dossiers.rafraichir(dossier.id)
        }
    }

    /**
     * L'appareil photo vient de rendre la main. La photo est réduite, datée, située, scellée
     * par son empreinte, chiffrée — puis seulement mise en file. Sans position, elle part
     * quand même : une photo sans lieu vaut mieux que pas de photo, et l'écran dit qu'il manque.
     */
    // ── Évaluation des dégâts à pied (personnel municipal et élus) ─────────────────────────

    val secteurDegats = app.degats.secteur
    val typesBien = app.degats.types
    var tournee by mutableStateOf<DepotDegats.Tournee?>(null); private set
    var tourneeEnCours by mutableStateOf(false); private set
    var embarquementEnCours by mutableStateOf(false); private set

    fun ouvrirDegats() {
        aller(Ecran.DEGATS)
        viewModelScope.launch { app.degats.chargerTypes() }
    }

    fun chargerTournee(crise: String, ici: Releve) {
        tourneeEnCours = true
        viewModelScope.launch {
            tournee = app.degats.tournee(crise, ici.latitude, ici.longitude)
            tourneeEnCours = false
        }
    }

    /** `rayonM` : 1 à 20 km ; `toutLaCommune` : tout le territoire communal (23/11/2026). */
    fun embarquerSecteur(crise: String, ici: Releve, rayonM: Int = 1000, toutLaCommune: Boolean = false) {
        embarquementEnCours = true
        viewModelScope.launch {
            message = when (val r = app.degats.embarquer(crise, ici.latitude, ici.longitude, rayonM, toutLaCommune)) {
                is Reponse.Ok -> "Secteur embarqué : ${r.valeur.adresses.size} adresses, ${r.valeur.biens.size} biens déjà vus" +
                    (if (r.valeur.tronque) " (incomplet : réduisez le rayon)" else "") +
                    ". Appuyez maintenant sur « Commencer la tournée »."
                is Reponse.Refus -> r.message
                is Reponse.Injoignable -> "Pas de réseau : le secteur n'a pas pu être embarqué."
            }
            embarquementEnCours = false
        }
    }

    fun effacerSecteurDegats() { viewModelScope.launch { app.degats.effacerSecteur() } }

    /**
     * Un constat fini : il part en file avec ses photos (chacune réduite, datée, située, scellée,
     * chiffrée), dans cet ordre — le serveur joint les photos au bien du constat.
     */
    fun constater(constat: Constat, libelle: String, photos: List<java.io.File>, position: Releve?, apres: () -> Unit) {
        photoEnCours = true
        viewModelScope.launch {
            app.degats.constater(constat, libelle)
            for (prise in photos) {
                val prete = Photographe.preparer(prise, position, "", BuildConfig.VERSION_NAME)
                if (prete == null) message = "Une photo n'a pas pu être lue : elle n'est pas jointe."
                else app.degats.ajouterPhoto(constat.id, prete.first, prete.second, "Photo — $libelle")
            }
            photoEnCours = false
            verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
            if (file.value.any { it.genre == ActionEnAttente.GENRE_CONSTAT && it.cible == constat.id }) {
                message = "Constat gardé sur ce téléphone : il partira dès que le réseau reviendra."
            }
            apres()
        }
    }

    fun ajouterPhoto(dossier: Dossier, prise: java.io.File, position: Releve?, commentaire: String) {
        photoEnCours = true
        viewModelScope.launch {
            val prete = Photographe.preparer(prise, position, commentaire, BuildConfig.VERSION_NAME)
            if (prete == null) message = "Cette photo n'a pas pu être lue. Reprenez-la."
            else {
                app.dossiers.ajouterPhoto(dossier, prete.first, prete.second)
                photoEnCours = false
                verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
                if (file.value.any { it.genre == ActionEnAttente.GENRE_PHOTO && it.cible == dossier.id && it.etat == EtatAction.EN_ATTENTE }) {
                    message = "Photo gardée sur ce téléphone : elle partira dès que le réseau reviendra."
                }
            }
            photoEnCours = false
        }
    }

    /** Charge la vignette d'une photo du serveur, une fois. Chaque lecture est journalisée là-bas. */
    fun chargerVignette(idPhoto: String) {
        if (idPhoto in vignettes) return
        viewModelScope.launch {
            (app.api.octetsDePhoto(idPhoto) as? Reponse.Ok)?.let { r ->
                Photographe.vignette(r.valeur)?.let { vignettes[idPhoto] = it.asImageBitmap() }
            }
        }
    }

    /** La vignette d'une photo qui attend encore sur ce téléphone. */
    fun chargerVignetteEnAttente(action: ActionEnAttente) {
        if (action.id in vignettes) return
        viewModelScope.launch {
            val photo = app.dossiers.lirePhotoEnAttente(action) ?: return@launch
            app.dossiers.octetsEnAttente(photo)?.let { octets -> Photographe.vignette(octets)?.let { vignettes[action.id] = it.asImageBitmap() } }
        }
    }

    fun photoEnAttente(action: ActionEnAttente) = app.dossiers.lirePhotoEnAttente(action)

    private fun chargerEcran(charger: suspend () -> Reponse<Unit>) {
        chargement = true
        horsLigne = false
        viewModelScope.launch {
            when (val r = charger()) {
                is Reponse.Ok -> Unit
                is Reponse.Refus -> message = r.message
                is Reponse.Injoignable -> horsLigne = true
            }
            chargement = false
        }
    }

    // --- Équipes et messagerie -----------------------------------------------------------

    fun ouvrirMessagerie(equipe: Equipe) {
        app.alertes.retirerConversation(LiaisonRadio.idNotificationEquipe(equipe.id))
        marquerEquipeLue(equipe.id)
        equipeOuverte = equipe.id
        ecran = Ecran.MESSAGERIE
    }

    /** Relit le fil ouvert. Appelé en boucle par l'écran tant qu'il est affiché. */
    /** Quitter une équipe (23/11/2026) : ses missions et ses dossiers ne sont plus sur ce
     * téléphone, mais rien n'est supprimé sur le serveur. */
    fun quitterEquipe(equipe: Equipe) {
        viewModelScope.launch {
            message = when (val r = app.api.quitterEquipe(equipe.id)) {
                is Reponse.Ok -> {
                    app.equipes.rafraichir(); app.depot.rafraichir()
                    if (equipeOuverte == equipe.id) ecran = Ecran.EQUIPES
                    "Vous avez quitté « ${equipe.nom} ». L'équipe et ses missions restent."
                }
                is Reponse.Refus -> r.message
                is Reponse.Injoignable -> "Il faut le réseau pour quitter une équipe."
            }
        }
    }

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

    // --- Mise à jour de l'application (20/11/2026) ------------------------------------------

    /** La mise à jour à proposer, ou null : lue dans /mobile/version.json du site. */
    var miseAJour by mutableStateOf<fr.assistacrise.mobile.domaine.MiseAJourProposee?>(null)
        private set

    private var miseAJourVerifieeLe = 0L

    /** Au retour du réseau, une fois par heure au plus : un petit fichier, rien d'autre. */
    fun verifierLaMiseAJour(force: Boolean = false) {
        val maintenant = System.currentTimeMillis()
        if (!force && maintenant - miseAJourVerifieeLe < 3600_000L) return
        miseAJourVerifieeLe = maintenant
        viewModelScope.launch {
            val publiee = app.versionPubliee() ?: return@launch
            val report = app.magasin.lire(FICHIER_REPORT)?.split("|")
            val reporteeLe = report?.takeIf { it.firstOrNull() == publiee.version }?.getOrNull(1)?.toLongOrNull()
            miseAJour = fr.assistacrise.mobile.domaine.MisesAJour.aProposer(
                publiee, BuildConfig.VERSION_CODE, BuildConfig.CLE_APPLICATION, BuildConfig.URL_SITE,
                reporteeLe, System.currentTimeMillis(),
            )
        }
    }

    /** « Plus tard » : reproposée dans un jour (une heure si elle est obligatoire). */
    fun reporterLaMiseAJour() {
        val proposee = miseAJour ?: return
        miseAJour = null
        viewModelScope.launch { app.magasin.ecrire(FICHIER_REPORT, "${proposee.versionPubliee}|${System.currentTimeMillis()}") }
    }

    /** « Mettre à jour » : le téléchargement est confié au navigateur, qui ouvre l'installation. */
    fun miseAJourLancee() { miseAJour = null }

    // --- Radio ----------------------------------------------------------------------------

    fun chercherDesRadios() = app.radio.chercher()
    fun arreterLaRecherche() = app.radio.arreterLaRecherche()
    fun connecterLaRadio(radio: LiaisonRadio.RadioTrouvee) = app.radio.connecter(radio)
    /** Une radio jointe par le réseau (TCP/IP). Rend le motif d'un refus, ou null. */
    fun connecterLaRadioParLeReseau(protocole: fr.assistacrise.mobile.lien.Protocole, adresse: String): String? =
        app.radio.connecterParLeReseau(protocole, adresse)
    fun deconnecterLaRadio(protocole: fr.assistacrise.mobile.lien.Protocole) = app.radio.deconnecter(protocole)

    /** Le canal de cette équipe sur cette radio, s'il y est configuré. */
    fun canalRadioDe(equipe: Equipe, protocole: fr.assistacrise.mobile.lien.Protocole) = app.radio.pour(protocole).canalPour(equipe)

    // --- Alignement sur le canal de la crise (23/11/2026) -------------------------------------

    var alignementEnCours by mutableStateOf(false); private set

    /** Le canal de la crise est-il sur cette radio ? */
    fun canalDeCriseSurLaRadio(cc: fr.assistacrise.mobile.domaine.CanalCrise, protocole: fr.assistacrise.mobile.lien.Protocole) =
        app.radio.pour(protocole).piloteCourant?.canalNomme(cc.nomPour(protocole == fr.assistacrise.mobile.lien.Protocole.MESHCORE))

    /**
     * Écrit sur la radio les canaux du plan de la crise qui lui manquent (Fr_Balise, Fr_EMCOM, canal
     * de la crise), dans des emplacements libres, sans toucher aux autres. Il faut le réseau pour
     * lire le plan (les clés publiques des canaux communautaires).
     */
    fun alignerRadio(protocole: fr.assistacrise.mobile.lien.Protocole, crise: String) {
        if (alignementEnCours) return
        viewModelScope.launch {
            alignementEnCours = true
            try {
                val plan = when (val r = app.api.planRadio(crise)) {
                    is Reponse.Ok -> r.valeur
                    is Reponse.Refus -> { message = "Plan radio refusé : ${r.message}"; return@launch }
                    is Reponse.Injoignable -> { message = "Il faut le réseau pour lire le plan radio de la crise."; return@launch }
                }
                val liaison = app.radio.pour(protocole)
                val pilote = liaison.piloteCourant?.takeIf { it.prete } ?: run { message = "Radio ${protocole.libelle} non connectée."; return@launch }
                val absents = plan.absents(protocole == fr.assistacrise.mobile.lien.Protocole.MESHCORE, pilote.canaux.map { it.nom })
                if (absents.isEmpty()) { message = "Radio ${protocole.libelle} déjà alignée sur la crise."; return@launch }
                var ecrits = 0
                var sansPlace = 0
                when (pilote) {
                    is fr.assistacrise.mobile.lien.PiloteMeshtastic -> {
                        liaison.relireAvance(); kotlinx.coroutines.delay(2_000)
                        val roles = pilote.avance.canauxMeshtastic.mapValues { it.value.role }.toMutableMap()
                        for (nom in absents) {
                            val c = plan.meshtastic.first { it.nom == nom }
                            val i = fr.assistacrise.mobile.domaine.PlanRadio.emplacementLibreMeshtastic(roles) ?: run { sansPlace++; null } ?: continue
                            val canal = fr.assistacrise.mobile.lien.meshtastic.CanalMeshtastic(i, c.nom, role = 2, psk = c.pskHex.hexEnOctets())
                            if (liaison.envoyerAdmin(pilote.adminGroupe(listOf(fr.assistacrise.mobile.lien.meshtastic.AdminMeshtastic.ecrireCanal(canal))))) {
                                roles[i] = 2; ecrits++
                            }
                        }
                    }
                    is fr.assistacrise.mobile.lien.PiloteMeshCore -> {
                        val occupes = pilote.canaux.map { it.index }.toMutableSet()
                        for (nom in absents) {
                            val c = plan.meshcore.first { it.nom == nom }
                            val i = fr.assistacrise.mobile.domaine.PlanRadio.emplacementLibreMeshCore(occupes) ?: run { sansPlace++; null } ?: continue
                            val trames = listOf(fr.assistacrise.mobile.lien.meshcore.AdminMeshCore.ecrireCanal(i, c.nom, c.cleHex.hexEnOctets()),
                                                fr.assistacrise.mobile.lien.meshcore.MeshCore.demanderCanal(i))
                            if (liaison.envoyerAdmin(trames)) { occupes += i; ecrits++ }
                        }
                    }
                    else -> {}
                }
                kotlinx.coroutines.delay(1_500); liaison.relireAvance()
                message = buildString {
                    append(if (ecrits > 0) "$ecrits canal(aux) ajouté(s) à la radio ${protocole.libelle}." else "Aucun canal ajouté.")
                    if (sansPlace > 0) append(" Plus d'emplacement libre pour $sansPlace : libérez-en un (Radio avancée).")
                }
            } finally {
                alignementEnCours = false
            }
        }
    }

    private fun String.hexEnOctets(): ByteArray = chunked(2).mapNotNull { it.toIntOrNull(16)?.toByte() }.toByteArray()

    // --- Mode citoyen ---------------------------------------------------------------------

    /** `lieu` : l'endroit touché sur la carte. Sans lui, le dépôt porte la position du moment. */
    fun ouvrirDepot(genre: GenreDepot, crise: Crise, lieu: Releve? = null) {
        retourDuDepot = if (ecran == Ecran.DEPOT) retourDuDepot else ecran
        depotOuvert = genre to crise
        aller(Ecran.DEPOT)
        lieuChoisi = lieu
        photoDuDepot = null
    }

    fun fermerDepot() { aller(retourDuDepot) }

    /** La photo jointe au dépôt en cours : préparée, pas encore gardée. En mémoire seulement. */
    var photoDuDepot by mutableStateOf<Pair<ByteArray, ImageBitmap>?>(null); private set

    /**
     * Photo d'une demande, d'un signalement ou d'une offre. Contrairement à une photo de
     * dossier, **la position n'y est pas inscrite** : ces dépôts sont visibles bien au-delà
     * d'une équipe, et le lieu voyage déjà dans le formulaire, où le serveur le protège. Une
     * position cachée dans l'image y échapperait.
     */
    fun joindrePhotoAuDepot(prise: java.io.File) {
        photoEnCours = true
        viewModelScope.launch {
            val prete = Photographe.preparer(prise, null, "", BuildConfig.VERSION_NAME)
            val image = prete?.let { Photographe.vignette(it.first) }
            if (prete == null || image == null) message = "Cette photo n'a pas pu être lue. Reprenez-la."
            else photoDuDepot = prete.first to image.asImageBitmap()
            photoEnCours = false
        }
    }

    fun retirerPhotoDuDepot() { photoDuDepot = null }

    fun deposer(saisie: Depot) {
        val erreurs = validerDepot(saisie)
        if (erreurs.isNotEmpty()) {
            depot = EtatFormulaire(erreur = "Corrigez les champs signalés.", champs = erreurs)
            return
        }
        depot = EtatFormulaire(enCours = true)
        viewModelScope.launch {
            val clePhoto = photoDuDepot?.let { app.dossiers.garderOctets(it.first) }   // chiffrée, avant la file
            app.citoyen.deposer(saisie, clePhoto)       // sur disque avant tout envoi
            photoDuDepot = null
            val avant = file.value.size
            verrouSynchro.withLock { app.synchro.envoyerLaFile(force = true) }
            val parti = file.value.size < avant
            // On dit la vérité sur ce qui s'est passé : « envoyé » n'est pas « enregistré ».
            message = if (parti) "Envoyé. Merci." else "Enregistré sur ce téléphone : cela partira dès que le réseau reviendra."
            aller(retourDuDepot)
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
            else { app.suivi.arreterALaMain(equipes.value); ServiceTerrain.actualiser(app) }
        }
    }

    fun arreterLeSuivi() {
        viewModelScope.launch {
            app.suivi.arreterALaMain(equipes.value)
            ServiceTerrain.actualiser(app)
        }
    }

    fun reprendreLeSuivi() {
        viewModelScope.launch { app.suivi.reprendre(); piloterLeSuivi(equipes.value) }
    }

    /** `connues` : mes équipes telles que le serveur vient de les donner, ou `null` s'il n'a pas répondu.
     * La décision est dans `ChefDeMission`, la même application fermée (22/11/2026). */
    private suspend fun piloterLeSuivi(connues: List<Equipe>?) {
        message = when (app.chef.piloter(connues)) {
            ChefDeMission.Evenement.FIN_D_ENGAGEMENT -> "Fin d'engagement : le suivi de position est arrêté."
            ChefDeMission.Evenement.PLAFOND -> "Le suivi de position s'est arrêté après douze heures."
            ChefDeMission.Evenement.DEMARRE, ChefDeMission.Evenement.SERVICE_REFUSE ->
                "Votre équipe est engagée : votre position est partagée."
            else -> message
        }
        // Application à l'écran : Android autorise ici le démarrage refusé en arrière-plan.
        ServiceTerrain.actualiser(app)
    }

    companion object {
        private const val FICHIER_REPORT = "mise-a-jour-reportee"

        val Fabrique: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                ModeleApplication(this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as Application)
            }
        }
    }
}
