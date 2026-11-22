package fr.assistacrise.mobile

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
            install(HttpTimeout) {
                connectTimeoutMillis = 10_000
                requestTimeoutMillis = 20_000
                socketTimeoutMillis = 20_000
            }
        }
    }
    val api by lazy { ClientApi(http, BuildConfig.URL_API, session) }

    /** La version publiée sur le site (/mobile/version.json), ou null hors réseau. */
    suspend fun versionPubliee(): fr.assistacrise.mobile.domaine.VersionPubliee? = runCatching {
        val texte = http.get("${BuildConfig.URL_SITE}/mobile/version.json").bodyAsText()
        kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
            .decodeFromString(fr.assistacrise.mobile.domaine.VersionPubliee.serializer(), texte)
    }.getOrNull()
    val depot by lazy { DepotMissions(api, magasin, file) }
    val equipes by lazy { DepotEquipes(api, magasin, file) }
    val suivi by lazy { DepotSuivi(magasin, file) { System.currentTimeMillis() } }
    val citoyen by lazy { DepotCitoyen(api, magasin, file) }
    val radio by lazy { LiaisonRadio(this) }
    val dossiers by lazy { DepotDossiers(api, magasin, file) { UUID.randomUUID().toString() } }
    val degats by lazy { DepotDegats(api, magasin, file) { UUID.randomUUID().toString() } }
    val terrain by lazy {
        DepotTerrain(magasin, file, { session.compte.value?.id }, { System.currentTimeMillis() },
            { java.time.Instant.now().toString() })
    }
    val points by lazy { fr.assistacrise.mobile.donnees.DepotPoints(api, magasin) }
    val cartes by lazy { CartesHorsLigne(this) }
    val synchro by lazy { Synchronisation(api, file, depot, equipes, dossiers, radio, degats, terrain) }
    val lien by lazy { IndicateurLien() }
    val reseau by lazy { ObservateurReseau(this) }
    val notifications by lazy { DepotNotifications(api, magasin) { UUID.randomUUID().toString() } }
    val benevole by lazy { DepotBenevole(api, magasin) }
    val veille by lazy { Veille(magasin, notifications, equipes, depot) }
    val alertes by lazy { Alertes(this) }
    val chef by lazy { ChefDeMission(this) }
    val messagerieRadio by lazy { MessagerieRadio(this) }

    private val verrouRestauration = Mutex()
    private var restaure = false

    /**
     * Relit du disque ce que le lancement précédent a laissé. Une seule fois par processus,
     * qui que ce soit qui le demande en premier — l'écran, ou la tâche de fond réveillée
     * alors que l'application est fermée. Relire deux fois écraserait l'état en mémoire.
     */
    suspend fun restaurer() = verrouRestauration.withLock {
        if (restaure) return@withLock
        session.restaurer()
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
        messagerieRadio.restaurer()
        restaure = true
    }
}
