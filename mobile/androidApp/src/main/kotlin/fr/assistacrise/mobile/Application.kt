package fr.assistacrise.mobile

import kotlinx.coroutines.launch

import fr.assistacrise.mobile.donnees.ClientApi
import fr.assistacrise.mobile.donnees.DepotBenevole
import fr.assistacrise.mobile.donnees.DepotCitoyen
import fr.assistacrise.mobile.donnees.DepotDegats
import fr.assistacrise.mobile.donnees.DepotDossiers
import fr.assistacrise.mobile.donnees.DepotNotifications
import fr.assistacrise.mobile.donnees.Veille
import fr.assistacrise.mobile.donnees.DepotEquipes
import fr.assistacrise.mobile.donnees.DepotMissions
import fr.assistacrise.mobile.donnees.DepotSuivi
import fr.assistacrise.mobile.donnees.DepotTerrain
import fr.assistacrise.mobile.donnees.FileAttente
import fr.assistacrise.mobile.donnees.Session
import fr.assistacrise.mobile.donnees.Synchronisation
import fr.assistacrise.mobile.lien.IndicateurLien
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.get
import io.ktor.client.statement.bodyAsText
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File
import java.util.UUID

/**
 * Les pièces de l'application, assemblées une fois. Pas de bibliothèque d'injection : il y
 * a une dizaine d'objets, et les voir câblés à la main sur une page vaut mieux qu'une magie de plus.
 */
class Application : android.app.Application() {
    val magasin by lazy { MagasinChiffre(File(filesDir, "magasin")) }
    val session by lazy { Session(magasin) }
    val file by lazy { FileAttente(magasin) { System.currentTimeMillis() } }
    val http by lazy {
        HttpClient(OkHttp) {
            // Garde-fou (23/11/2026) : la configuration réseau permet le http en clair pour joindre
            // le satellite du site ; ici, on le refuse pour toute adresse qui n'est pas locale
            // (IP privée, nom en .local, ou machine de développement). Le reste est https.
            engine {
                addInterceptor { chaine ->
                    val url = chaine.request().url
                    if (url.scheme == "http" && !adresseLocale(url.host)) {
                        throw java.io.IOException("Connexion en clair refusée vers ${url.host} : https obligatoire hors du réseau local.")
                    }
                    chaine.proceed(chaine.request())
                }
            }
            install(HttpTimeout) {
                connectTimeoutMillis = 10_000
                requestTimeoutMillis = 20_000
                socketTimeoutMillis = 20_000
            }
        }
    }
    /** Le central, ou le satellite du site quand le central ne répond plus (23/11/2026). */
    val serveur by lazy { fr.assistacrise.mobile.donnees.Serveur(magasin, BuildConfig.URL_SITE) }
    val api: ClientApi by lazy {
        ClientApi(http, { serveur.urlApi() }, session).also { client ->
            client.surJoignabilite = { repondu -> if (bascule.noter(repondu)) lancerLaRecherche() }
        }
    }
    val bascule: fr.assistacrise.mobile.donnees.BasculeServeur by lazy {
        fr.assistacrise.mobile.donnees.BasculeServeur(serveur, session, { api.sonde(it) }, { DecouverteSatellite(this).decouvrir() })
    }
    private val porteeBascule = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.IO)
    @Volatile private var rechercheEnCours = false

    override fun onCreate() {
        super.onCreate()
        alertes.mesNoms = ::mesNoms
        surveillerPourNotifier()
    }

    /** Les noms sous lesquels on peut me mentionner : mon prénom, mon nom complet, le nom (long et
     * court) de chacun de mes nœuds radio (23/11/2026). */
    fun mesNoms(): Set<String> = buildSet {
        session.compte.value?.let { c ->
            if (c.prenom.isNotBlank()) add(c.prenom)
            add(listOf(c.prenom, c.nom).filter { it.isNotBlank() }.joinToString(" "))
        }
        radio.toutes.forEach { l ->
            val p = l.piloteCourant ?: return@forEach
            p.identite?.let(::add)
            val a = p.avance
            a.monNoeud?.let { a.noeuds[it] }?.let { n -> add(n.nomLong); add(n.nomCourt) }
            a.moi?.nom?.let(::add)
        }
    }.filter { it.trim().length >= 2 }.toSet()

    /**
     * Notifications d'état (23/11/2026, POC hors réseau) : au retour du réseau, « vos envois en
     * attente sont partis » ; un envoi refusé par le serveur ; la radio perdue puis retrouvée.
     * Rien quand l'application est à l'écran pour l'envoi : le bandeau de l'écran le dit déjà.
     */
    private fun surveillerPourNotifier() {
        porteeBascule.launch {
            var attente = -1
            var refusees = -1
            file.actions.collect { actions ->
                val n = actions.count { it.etat == fr.assistacrise.mobile.domaine.EtatAction.EN_ATTENTE &&
                    it.genre != fr.assistacrise.mobile.domaine.ActionEnAttente.GENRE_ENTENDU_RADIO }
                val r = actions.count { it.etat == fr.assistacrise.mobile.domaine.EtatAction.REFUSEE }
                if (attente > 0 && n == 0 && !premierPlan) {
                    alertes.etat("envois-partis", "Synchronisation faite",
                        "Les $attente envoi(s) qui attendaient le réseau sont arrivés au serveur.")
                }
                if (refusees >= 0 && r > refusees) {
                    alertes.etat("envois-refuses", "${r} envoi(s) refusé(s) par le serveur",
                        "Ouvrez l'application (Compte) pour voir lesquels et pourquoi.")
                }
                attente = n; refusees = r
            }
        }
        porteeBascule.launch {
            val prete = mutableMapOf<Int, Boolean>()
            radio.etats.collect { etats ->
                etats.forEachIndexed { i, e ->
                    val liaison = radio.toutes[i]
                    val maintenant = e.phase == LiaisonRadio.Phase.PRETE
                    val avant = prete[i]
                    val id = "radio-perdue-${liaison.emplacement.name}"
                    if (avant == true && !maintenant && liaison.choisie()) {
                        alertes.etat(id, "Radio ${liaison.emplacement.libelle} perdue",
                            "La liaison avec la radio est coupée : reconnexion automatique en cours. Vérifiez qu'elle est allumée et à portée.")
                    } else if (maintenant && avant == false) {
                        alertes.retirerEtat(id)
                    }
                    prete[i] = maintenant
                }
            }
        }
    }

    /** Le central ne répond plus : chercher le satellite (une seule recherche à la fois). */
    fun lancerLaRecherche() {
        if (rechercheEnCours) return
        rechercheEnCours = true
        porteeBascule.launch { try { bascule.chercherEtBasculer() } finally { rechercheEnCours = false } }
    }

    /** La version publiée sur le site (/mobile/version.json), ou null hors réseau. */
    suspend fun versionPubliee(): fr.assistacrise.mobile.domaine.VersionPubliee? = runCatching {
        val texte = http.get("${BuildConfig.URL_SITE}/mobile/version.json").bodyAsText()
        kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
            .decodeFromString(fr.assistacrise.mobile.domaine.VersionPubliee.serializer(), texte)
    }.getOrNull()
    val depot by lazy { DepotMissions(api, magasin, file) { if (equipes.connues) equipes.equipes.value.map { it.id }.toSet() else null } }
    val equipes by lazy { DepotEquipes(api, magasin, file) }
    val suivi by lazy { DepotSuivi(magasin, file) { System.currentTimeMillis() } }
    val citoyen by lazy { DepotCitoyen(api, magasin, file) }
    val radio by lazy { Radios(this) }
    val dossiers by lazy { DepotDossiers(api, magasin, file) { UUID.randomUUID().toString() } }
    val degats by lazy { DepotDegats(api, magasin, file) { UUID.randomUUID().toString() } }
    val terrain by lazy {
        DepotTerrain(magasin, file, { session.compte.value?.id }, { System.currentTimeMillis() },
            { java.time.Instant.now().toString() })
    }
    val points by lazy { fr.assistacrise.mobile.donnees.DepotPoints(api, magasin) }
    val pointsEau by lazy { fr.assistacrise.mobile.donnees.DepotPointsEau(api, magasin, file) { UUID.randomUUID().toString() } }
    val cartes by lazy { CartesHorsLigne(this) }
    val synchro by lazy { Synchronisation(api, file, depot, equipes, dossiers, radio, degats, terrain, "Android ${android.os.Build.MODEL}", pointsEau) }
    val lien by lazy { IndicateurLien() }
    val reseau by lazy { ObservateurReseau(this) }
    val notifications by lazy { DepotNotifications(api, magasin) { UUID.randomUUID().toString() } }
    val benevole by lazy { DepotBenevole(api, magasin) }
    val veille by lazy {
        Veille(magasin, notifications, equipes, depot) { relire ->
            if (relire && equipes.equipes.value.isNotEmpty()) benevole.chargerLesDossiers(equipes.equipes.value.map { it.id }.toSet())
            benevole.dossiers.value
        }
    }
    val alertes by lazy { Alertes(this) }
    val chef by lazy { ChefDeMission(this) }
    /** La carte du terrain hors réseau (27/11/2026) : marqueurs du central, manifestations du jour. */
    val carteTerrain by lazy {
        fr.assistacrise.mobile.donnees.DepotCarteTerrain(api, magasin, { fr.assistacrise.mobile.ui.instantDe(it) }, { System.currentTimeMillis() })
    }

    /**
     * Mes présences en manifestation, vues comme des engagements (27/11/2026, décision de Sylvain :
     * la position est partagée du pointage « présent » à la fin du créneau). Le suivi les traite
     * comme l'engagement d'une équipe : même consentement, même avertissement, arrêt à la fin.
     */
    fun engagementsDeManifestation(): List<fr.assistacrise.mobile.domaine.Equipe> =
        carteTerrain.presencesEnCours().map { (m, p, _) ->
            fr.assistacrise.mobile.domaine.Equipe(id = "manif:${p.id}", nom = "Manifestation « ${m.titre} »", engagementDebut = p.debut)
        }

    /** Les engagements que le suivi considère : mes équipes, plus mes présences en manifestation.
     * `connues` à null (pas de réseau) : on ne sait rien des équipes, sauf qu'un créneau de
     * manifestation terminé arrête le suivi sans attendre le réseau. */
    fun engagementsPourLeSuivi(connues: List<fr.assistacrise.mobile.domaine.Equipe>?): List<fr.assistacrise.mobile.domaine.Equipe>? = when {
        connues != null -> connues + engagementsDeManifestation()
        carteTerrain.presenceTermineeRecemment() && equipes.equipes.value.none { it.engagee } -> engagementsDeManifestation()
        else -> null
    }
    val messagerieRadio by lazy { MessagerieRadio(this) }

    /** L'application est-elle à l'écran, et quel fil y est ouvert ? Ce qu'on lit déjà ne sonne pas. */
    @Volatile var premierPlan = false
    @Volatile var equipeAffichee: String? = null

    private val verrouRestauration = Mutex()
    private var restaure = false

    /**
     * Relit du disque ce que le lancement précédent a laissé. Une seule fois par processus,
     * qui que ce soit qui le demande en premier — l'écran, ou la tâche de fond réveillée
     * alors que l'application est fermée. Relire deux fois écraserait l'état en mémoire.
     */
    suspend fun restaurer() = verrouRestauration.withLock {
        if (restaure) return@withLock
        serveur.restaurer()
        // Sur un satellite au dernier lancement : sa session à lui, pas celle du central.
        if (serveur.satellite.value != null) session.basculerEspace(satellite = true) else session.restaurer()
        bascule.reprendre()
        file.restaurer()
        depot.restaurer()
        equipes.restaurer()
        suivi.restaurer()
        citoyen.restaurer()
        degats.restaurer()
        notifications.restaurer()
        benevole.restaurer()
        terrain.restaurer()
        points.restaurer()
        pointsEau.restaurer()
        carteTerrain.restaurer()
        messagerieRadio.restaurer()
        restaure = true
    }
}

/** Une adresse du réseau local : IP privée (RFC 1918), nom en .local, ou la machine de développement. */
internal fun adresseLocale(hote: String): Boolean {
    val h = hote.lowercase()
    if (h == "localhost" || h == "10.0.2.2" || h.endsWith(".local")) return true
    val o = h.split('.').mapNotNull { it.toIntOrNull() }
    if (o.size != 4 || h.count { it == '.' } != 3) return false
    return o[0] == 10 || (o[0] == 192 && o[1] == 168) || (o[0] == 172 && o[1] in 16..31)
}
