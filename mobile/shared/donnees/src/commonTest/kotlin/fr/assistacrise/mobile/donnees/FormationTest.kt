package fr.assistacrise.mobile.donnees

import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** La bascule « Formation » de l'application, comme celle du site (22/11/2026). */
class FormationTest {
    private fun compte(demo: String?) =
        """{"id":"u1","email":"c@exemple.fr","type":"UTIL_SIMPLE"${demo?.let { ",\"demo_role\":\"$it\"" } ?: ""}}"""

    private class Banc(val compteJson: String) {
        val demandes = mutableListOf<HttpRequestData>()
        val magasin = MagasinEnMemoire()
        val session = Session(magasin)
        val api = ClientApi(HttpClient(MockEngine { d ->
            demandes += d
            if (d.url.encodedPath.endsWith("token/")) respond("""{"access":"A1","refresh":"R1","user":$compteJson}""", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            else respond("[]", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }), "https://exemple.test/api", session)
    }

    @Test fun laZonePartAvecChaqueRequete() = runTest {
        val banc = Banc(compte("SECOURS"))
        banc.api.connecter("c@exemple.fr", "secret")
        assertTrue(banc.session.compte.value!!.peutSeFormer)
        banc.api.missions()
        assertEquals("PROD", banc.demandes.last().headers["X-Environment"])
        banc.session.changerDEnvironnement(Session.DEMO)
        banc.api.missions()
        assertEquals("DEMO", banc.demandes.last().headers["X-Environment"])
        // Gardée d'un lancement à l'autre.
        val relance = Session(banc.magasin).also { it.restaurer() }
        assertTrue(relance.enFormation)
    }

    @Test fun pasDeFormationPourUnCompteSansDemonstration() = runTest {
        val banc = Banc(compte(null))
        banc.api.connecter("c@exemple.fr", "secret")
        assertFalse(banc.session.compte.value!!.peutSeFormer)
        banc.session.changerDEnvironnement(Session.DEMO)
        val relance = Session(banc.magasin).also { it.restaurer() }
        assertFalse(relance.enFormation)
    }

    @Test fun seDeconnecterRevientAuxDonneesReelles() = runTest {
        val banc = Banc(compte("SECOURS"))
        banc.api.connecter("c@exemple.fr", "secret")
        banc.session.changerDEnvironnement(Session.DEMO)
        banc.session.fermer()
        assertFalse(banc.session.enFormation)
    }
}
