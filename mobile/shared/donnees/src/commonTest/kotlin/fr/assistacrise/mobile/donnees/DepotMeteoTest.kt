package fr.assistacrise.mobile.donnees

import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Couches météo de la carte (27/11/2026) : les données publiques du serveur, sans jeton. */
class DepotMeteoTest {
    private val demandes = mutableListOf<HttpRequestData>()
    private var panne = false
    private var basculeAppelee = false
    private val png = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47)
    private val session = Session(MagasinEnMemoire())
    private val api = ClientApi(HttpClient(MockEngine { d ->
        demandes += d
        val chemin = d.url.encodedPath.removePrefix("/api/")
        val json = headersOf(HttpHeaders.ContentType, "application/json")
        when {
            panne -> throw java.io.IOException("pas de réseau")
            chemin == "orages/radar/" -> respond("""{"source":"Météo-France","heure":"2026-11-27T21:35:00+00:00","zone":"METROPOLE",
                "coins":[[-5.0,51.0],[9.0,51.0],[9.0,41.0],[-5.0,41.0]],"legende":[]}""", HttpStatusCode.OK, json)
            chemin == "orages/radar/image/" -> respond(png, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "image/png"))
            chemin == "rafales-prevues/" -> respond("""{"source":"Météo-France (AROME)","coins":[[-6.0,52.0],[10.0,52.0],[10.0,41.0],[-6.0,41.0]],
                "echeances":["T10","T11","T12"],"legende":[]}""", HttpStatusCode.OK, json)
            chemin == "rafales-prevues/image/" -> if (d.url.parameters["echeance"] == "T11") respond(png, HttpStatusCode.OK) else respondError(HttpStatusCode.NotFound)
            chemin == "orages/" -> respond("""{"source":"Météo-France","cellules":[{"identifiant":"c1",
                "contour":{"type":"Polygon","coordinates":[[[0,45],[1,45],[1,46],[0,45]]]},
                "couloir":{"type":"Polygon","coordinates":[[[1,45],[2,45],[2,46],[1,45]]]},
                "releves":{"intensite_max_mmh":42.5,"libelle":"orage fort"}}]}""", HttpStatusCode.OK, json)
            chemin == "foudre/" -> respond("""{"source":"EUMETSAT","type":"FeatureCollection","features":[
                {"type":"Feature","geometry":{"type":"Point","coordinates":[0.5,45.5]},"properties":{"age_min":3}}]}""", HttpStatusCode.OK, json)
            else -> respondError(HttpStatusCode.NotFound)
        }
    }), "https://exemple.test/api", session).also { it.surJoignabilite = { basculeAppelee = true } }
    // Échéances d'essai : « T11 » = 11 h.
    private var maintenant = 11 * 3_600_000L - 60_000
    private val depot = DepotMeteo(api, { it.removePrefix("T").toLongOrNull()?.times(3_600_000L) }, { maintenant })
    private val france = DepotMeteo.Emprise.de(-5.0, 41.0, 10.0, 51.5)!!

    @Test fun lesQuatreCouchesSansJeton() = runTest {
        val r = depot.lire(DepotMeteo.Couche.entries.toSet(), france)
        assertContentEquals(png, r.pluie!!.octets)
        assertEquals(-5.0 to 51.0, r.pluie!!.coins.first())
        // Le quart d'heure en cours, pas la première échéance.
        assertEquals("T11", r.rafales!!.heure)
        assertEquals(1, r.nombreCellules)
        assertTrue("\"nature\":\"couloir\"" in r.orages!! && "\"mmh\":42.5" in r.orages!!)
        assertEquals(1, r.nombreEclairs)
        assertEquals(listOf("Météo-France", "Météo-France (AROME)", "EUMETSAT"), r.sources)
        assertTrue(r.manques.isEmpty())
        assertTrue(demandes.none { it.headers[HttpHeaders.Authorization] != null })
        // Le « + » du fuseau est encodé dans l'adresse de l'image.
        assertTrue(demandes.any { it.url.encodedPath.endsWith("orages/radar/image/") && it.url.parameters["heure"] == "2026-11-27T21:35:00+00:00" })
        assertTrue(demandes.first { it.url.encodedPath.endsWith("orages/") }.url.parameters["bbox"] == "-5.0,41.0,10.0,51.5")
    }

    @Test fun uneImageDejaRecueNEstPasRelue() = runTest {
        depot.lire(setOf(DepotMeteo.Couche.PLUIE), france)
        demandes.clear()
        depot.lire(setOf(DepotMeteo.Couche.PLUIE), france)
        assertTrue(demandes.none { it.url.encodedPath.endsWith("image/") })
    }

    @Test fun sansReseauRienNestAfficheEtOnNeBasculePas() = runTest {
        panne = true
        val r = depot.lire(setOf(DepotMeteo.Couche.PLUIE, DepotMeteo.Couche.ECLAIRS), france)
        assertTrue(r.injoignable)
        assertNull(r.pluie); assertNull(r.eclairs)
        assertEquals(listOf("pluie du radar", "éclairs"), r.manques)
        assertTrue(!basculeAppelee)
    }

    @Test fun rienDemandeRienLu() = runTest {
        depot.lire(emptySet(), france)
        assertTrue(demandes.isEmpty())
        assertNull(DepotMeteo.Emprise.de(10.0, 41.0, 5.0, 51.0))
    }
}
