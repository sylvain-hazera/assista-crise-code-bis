package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.EtiquetteTerrain
import fr.assistacrise.mobile.domaine.TypeMessageTerrain
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

private const val COMPTE_T = """{"id":"9c1e0b44-0000-0000-0000-000000000000","email":"c@exemple.fr","first_name":"Léa","last_name":"Martin","type":"UTIL_SIMPLE"}"""

/** Messages de terrain en un geste (22/11/2026) : file, repli radio, journal. */
class TerrainTest {
    private class Banc(var code: HttpStatusCode) {
        val demandes = mutableListOf<HttpRequestData>()
        val magasin = MagasinEnMemoire()
        val session = Session(magasin)
        val file = FileAttente(magasin) { 1_000_000L }
        val api = ClientApi(HttpClient(MockEngine { d ->
            demandes += d
            val chemin = d.url.encodedPath
            when {
                chemin.endsWith("token/") -> respond("""{"access":"A1","refresh":"R1","user":$COMPTE_T}""", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
                chemin.endsWith("mes-equipes/") -> respond("""[{"id":"t1","name":"Alpha","canal_meshcore_nom":"#alpha"}]""", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
                d.method == HttpMethod.Post && chemin.endsWith("messages-terrain/") ->
                    if (code == HttpStatusCode.OK) respond("{}", HttpStatusCode.Created, headersOf(HttpHeaders.ContentType, "application/json")) else respond("", code)
                else -> respond("[]", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            }
        }), "https://exemple.test/api", session)
        val missions = DepotMissions(api, magasin, file)
        val equipes = DepotEquipes(api, magasin, file)
        val terrain = DepotTerrain(magasin, file, { session.compte.value?.id }, { 1_000_000L }, { "2026-11-22T10:00:00Z" })
        val radio = mutableListOf<String>()
        val synchro = Synchronisation(api, file, missions, equipes, radio = EmetteurRadio { _, texte -> radio += texte; "MESHCORE" }, terrain = terrain)
    }

    @Test fun lEtiquetteEstLisibleEtTientDansUneTrame() {
        val e = EtiquetteTerrain.ecrire(TypeMessageTerrain.PREMIERS_SECOURS, "3f2a9c11-aaaa", "9c1e0b44-bbbb", "a1b2c3", "chute, cheville")
        assertEquals("⚑PS 3f2a9c.9c1e0b.a1b2c3 Demande de premiers secours : chute, cheville", e)
        val long = EtiquetteTerrain.ecrire(TypeMessageTerrain.SITUATION, null, "9c1e0b", "a1b2c3", "é".repeat(200))
        assertTrue(long.startsWith("⚑SIT ------.9c1e0b.a1b2c3") && long.endsWith("…") && long.encodeToByteArray().size <= EtiquetteTerrain.OCTETS_MAX)
    }

    @Test fun lesSecoursExigentUnMotif() = runTest {
        val banc = Banc(HttpStatusCode.OK)
        assertFailsWith<IllegalArgumentException> { banc.terrain.envoyer(TypeMessageTerrain.PREMIERS_SECOURS, "m1", "t1", "  ") }
    }

    @Test fun avecReseauLeMessagePartParLesDonnees() = runTest {
        val banc = Banc(HttpStatusCode.OK)
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        banc.terrain.envoyer(TypeMessageTerrain.RENFORT, "m1", "t1", nombre = 3)
        banc.synchro.envoyerLaFile(force = true)
        val corps = Json.parseToJsonElement((banc.demandes.last().body as TextContent).text).jsonObject
        assertEquals("RENFORT", corps.getValue("type").jsonPrimitive.content)
        assertEquals("3", corps.getValue("nombre").jsonPrimitive.content)
        assertTrue("equipe" !in corps)
        assertEquals(DepotTerrain.RECU, banc.terrain.journal.value.single().etat)
        assertTrue(banc.radio.isEmpty())
    }

    @Test fun sansReseauLEtiquettePartParRadioUneSeuleFoisPuisAuServeur() = runTest {
        val banc = Banc(HttpStatusCode.OK)
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        banc.code = HttpStatusCode.ServiceUnavailable
        banc.terrain.envoyer(TypeMessageTerrain.ARRIVE, "3f2a9c11", "t1")
        banc.synchro.envoyerLaFile(force = true)
        banc.synchro.envoyerLaFile(force = true)
        assertEquals(1, banc.radio.size)
        assertTrue(banc.radio.single().startsWith("⚑ARR 3f2a9c.9c1e0b."))
        assertEquals(DepotTerrain.RADIO, banc.terrain.journal.value.single().etat)
        banc.code = HttpStatusCode.OK
        banc.synchro.envoyerLaFile(force = true)
        assertEquals(DepotTerrain.RECU, banc.terrain.journal.value.single().etat)
        assertTrue(banc.file.actions.value.isEmpty())
    }
}
