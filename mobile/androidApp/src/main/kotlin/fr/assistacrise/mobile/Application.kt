package fr.assistacrise.mobile

import fr.assistacrise.mobile.donnees.ClientApi
import fr.assistacrise.mobile.donnees.DepotCitoyen
import fr.assistacrise.mobile.donnees.DepotEquipes
import fr.assistacrise.mobile.donnees.DepotMissions
import fr.assistacrise.mobile.donnees.DepotSuivi
import fr.assistacrise.mobile.donnees.FileAttente
import fr.assistacrise.mobile.donnees.Session
import fr.assistacrise.mobile.donnees.Synchronisation
import fr.assistacrise.mobile.lien.IndicateurLien
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import java.io.File

/**
 * Les pièces de l'application, assemblées une fois. Pas de bibliothèque d'injection : il y
 * a une dizaine d'objets, et les voir câblés à la main sur une page vaut mieux qu'une magie de plus.
 */
class Application : android.app.Application() {
    val magasin by lazy { MagasinChiffre(File(filesDir, "magasin")) }
    val session by lazy { Session(magasin) }
    val file by lazy { FileAttente(magasin) { System.currentTimeMillis() } }
    val api by lazy {
        val http = HttpClient(OkHttp) {
            install(HttpTimeout) {
                connectTimeoutMillis = 10_000
                requestTimeoutMillis = 20_000
                socketTimeoutMillis = 20_000
            }
        }
        ClientApi(http, BuildConfig.URL_API, session)
    }
    val depot by lazy { DepotMissions(api, magasin, file) }
    val equipes by lazy { DepotEquipes(api, magasin, file) }
    val suivi by lazy { DepotSuivi(magasin, file) { System.currentTimeMillis() } }
    val citoyen by lazy { DepotCitoyen(api, magasin, file) }
    val radio by lazy { LiaisonRadio(this) }
    val synchro by lazy { Synchronisation(api, file, depot, equipes, radio) }
    val lien by lazy { IndicateurLien() }
    val reseau by lazy { ObservateurReseau(this) }
}
