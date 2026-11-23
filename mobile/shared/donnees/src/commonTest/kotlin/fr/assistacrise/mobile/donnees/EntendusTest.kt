package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Ce que la radio du téléphone a entendu remonte au serveur au retour du réseau (23/11/2026). */
class EntendusTest {
    private val json = headersOf(HttpHeaders.ContentType, "application/json")
    private val compte = """{"access":"A1","refresh":"R1","user":{"id":"u1","email":"c@exemple.fr","first_name":"L","last_name":"M","type":"UTIL_SIMPLE"}}"""

    private suspend fun banc(code: HttpStatusCode, demandes: MutableList<HttpRequestData>): Pair<Synchronisation, FileAttente> {
        val magasin = MagasinEnMemoire()
        val session = Session(magasin)
        val file = FileAttente(magasin) { 1_000_000L }
        val api = ClientApi(HttpClient(MockEngine { d ->
            demandes += d
            when {
                d.url.encodedPath.endsWith("token/") -> respond(compte, HttpStatusCode.OK, json)
                d.url.encodedPath.endsWith("radio/entendus/") -> respond("""{"acceptes":["a1"]}""", code, json)
                else -> respond("[]", HttpStatusCode.OK, json)
            }
        }), "https://exemple.test/api", session)
        api.connecter("c@exemple.fr", "secret")
        val synchro = Synchronisation(api, file, DepotMissions(api, magasin, file), DepotEquipes(api, magasin, file), appareil = "Android Pixel")
        file.ajouter(ActionEnAttente.GENRE_ENTENDU_RADIO, "a1",
            """{"identifiant":"a1","protocole":"MESHTASTIC","canal":"CriseGier","texte":"@ALPHA mur fissuré"}""", "Message radio entendu")
        return synchro to file
    }

    @Test fun ilPartAuServeurEtQuitteLaFile() = runTest {
        val demandes = mutableListOf<HttpRequestData>()
        val (synchro, file) = banc(HttpStatusCode.OK, demandes)
        synchro.envoyerLaFile(force = true)
        val envoi = demandes.single { it.url.encodedPath.endsWith("radio/entendus/") }
        val corps = (envoi.body as TextContent).text
        assertTrue("\"appareil\":\"Android Pixel\"" in corps && "@ALPHA mur fissuré" in corps)
        assertEquals(0, file.actions.value.size)
    }

    @Test fun unServeurPasEncoreAJourNeLeFaitPasPerdre() = runTest {
        val (synchro, file) = banc(HttpStatusCode.NotFound, mutableListOf())
        synchro.envoyerLaFile(force = true)
        assertEquals(1, file.actions.value.size)
        assertEquals(fr.assistacrise.mobile.domaine.EtatAction.EN_ATTENTE, file.actions.value.single().etat)
    }
}
