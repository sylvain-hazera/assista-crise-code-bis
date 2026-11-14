package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.Inscription
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.StatutMission
import fr.assistacrise.mobile.domaine.superposerLaFile
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
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
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

private const val URL = "https://exemple.test/api"
private const val COMPTE = """{"id":"u1","email":"c@exemple.fr","first_name":"Camille","last_name":"Durand","type":"SECOURS","institution_id":"i1","institution_nom":"Réserve","champ_inconnu":42}"""

/** Un faux serveur : chaque test dit quoi répondre, et relit ce qui a été demandé. */
private class Banc(repondre: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData) {
    val demandes = mutableListOf<HttpRequestData>()
    val magasin = MagasinEnMemoire()
    val session = Session(magasin)
    var maintenant = 1_000_000L
    val file = FileAttente(magasin) { maintenant }
    val api = ClientApi(HttpClient(MockEngine { demande -> demandes += demande; repondre(demande) }), URL, session)
    val depot = DepotMissions(api, magasin, file)

    fun chemins() = demandes.map { "${it.method.value} ${it.url.encodedPath.removePrefix("/api/")}" }
}

private fun MockRequestHandleScope.json(texte: String, code: HttpStatusCode = HttpStatusCode.OK) =
    respond(texte, code, headersOf(HttpHeaders.ContentType, "application/json"))

private fun HttpRequestData.corps() = Json.parseToJsonElement((body as TextContent).text).jsonObject

private fun HttpRequestData.jeton() = headers[HttpHeaders.Authorization]

class ClientApiTest {
    @Test fun laConnexionOuvreUneSessionQuiSurvitAuRedemarrage() = runTest {
        val banc = Banc { json("""{"access":"A1","refresh":"R1","user":$COMPTE}""") }
        val r = banc.api.connecter(" c@exemple.fr ", "secret")
        assertIs<Reponse.Ok<*>>(r)
        assertEquals("c@exemple.fr", banc.demandes.single().corps().getValue("email").jsonPrimitive.content)
        assertEquals("Camille Durand", banc.session.compte.value?.nomComplet)

        val relance = Session(banc.magasin).also { it.restaurer() }
        assertEquals("u1", relance.compte.value?.id)
    }

    @Test fun unMauvaisMotDePasseEstDitEnFrancais() = runTest {
        val banc = Banc { json("""{"detail":"No active account found with the given credentials"}""", HttpStatusCode.Unauthorized) }
        val r = banc.api.connecter("c@exemple.fr", "faux")
        assertIs<Reponse.Refus>(r)
        assertTrue(r.message.startsWith("Adresse ou mot de passe incorrect"))
        assertNull(banc.session.compte.value)
    }

    @Test fun lInscriptionEnvoieCeQueLeServeurAttend() = runTest {
        val banc = Banc { json("""{"id":"u9"}""", HttpStatusCode.Created) }
        val r = banc.api.inscrire(Inscription("Camille", "Durand", "c@exemple.fr", "0612345678", "71000", "Abcdef1!", true, true))
        assertIs<Reponse.Ok<*>>(r)
        val corps = banc.demandes.single().corps()
        assertEquals("POST register/", banc.chemins().single())
        assertEquals("UTIL_SIMPLE", corps.getValue("type").jsonPrimitive.content)
        assertEquals("c@exemple.fr", corps.getValue("username").jsonPrimitive.content)
        assertEquals("true", corps.getValue("souhaite_rejoindre_reserve").jsonPrimitive.content)
        assertNull(banc.demandes.single().jeton())
    }

    @Test fun lesErreursDeChampDuServeurSontRenduesParChamp() = runTest {
        val banc = Banc { json("""{"email":["Un compte existe déjà avec cette adresse."]}""", HttpStatusCode.BadRequest) }
        val r = banc.api.inscrire(Inscription())
        assertIs<Reponse.Refus>(r)
        assertEquals("Un compte existe déjà avec cette adresse.", r.champs["email"])
    }

    @Test fun unJetonPerimeEstRafraichiUneFoisPuisLAppelRejoue() = runTest {
        val banc = Banc { demande ->
            when {
                demande.url.encodedPath.endsWith("token/") -> json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
                demande.url.encodedPath.endsWith("token/refresh/") -> json("""{"access":"A2","refresh":"R2"}""")
                demande.jeton() == "Bearer A1" -> json("""{"detail":"Token expiré"}""", HttpStatusCode.Unauthorized)
                else -> json("""[{"id":"m1","titre":"Reconnaissance","statut":"EN_COURS","equipes_noms":["Alpha"]}]""")
            }
        }
        banc.api.connecter("c@exemple.fr", "secret")
        val r = banc.api.missions()
        assertIs<Reponse.Ok<List<Mission>>>(r)
        assertEquals(StatutMission.EN_COURS, r.valeur.single().statut)
        assertEquals(listOf("POST token/", "GET missions/", "POST token/refresh/", "GET missions/"), banc.chemins())
        // Le jeton de rafraîchissement a tourné : c'est le nouveau qui est gardé.
        assertEquals("R2", banc.demandes[2].let { banc.session.jetonRafraichissement })
    }

    @Test fun unRafraichissementRefuseFermeLaSession() = runTest {
        val banc = Banc { demande ->
            if (demande.url.encodedPath.endsWith("token/")) json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
            else json("""{"detail":"non"}""", HttpStatusCode.Unauthorized)
        }
        banc.api.connecter("c@exemple.fr", "secret")
        val r = banc.api.missions()
        assertIs<Reponse.Refus>(r)
        assertEquals(ClientApi.SESSION_EXPIREE, r.message)
        assertNull(banc.session.compte.value)
        assertNull(banc.magasin.contenu["session"])
    }

    @Test fun unePanneDuServeurNEstPasUnRefus() = runTest {
        val banc = Banc { respond("<html>502</html>", HttpStatusCode.BadGateway) }
        assertIs<Reponse.Injoignable>(banc.api.connecter("c@exemple.fr", "secret"))
    }

    @Test fun uneCoupureReseauNEstPasUnRefus() = runTest {
        val banc = Banc { throw java.io.IOException("pas de réseau") }
        assertIs<Reponse.Injoignable>(banc.api.connecter("c@exemple.fr", "secret"))
    }

    @Test fun unStatutInconnuNeFaitPasEchouerLaListe() = runTest {
        val banc = Banc { demande ->
            if (demande.url.encodedPath.endsWith("token/")) json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
            else json("""{"results":[{"id":"m1","titre":"T","statut":"SUSPENDUE"}]}""")
        }
        banc.api.connecter("c@exemple.fr", "secret")
        val r = banc.api.missions()
        assertIs<Reponse.Ok<List<Mission>>>(r)
        assertEquals("m1", r.valeur.single().id)
    }
}

class FileAttenteTest {
    private val mission = Mission(id = "m1", titre = "Reconnaissance")

    private fun bancConnecte(statutMissions: () -> HttpStatusCode) = Banc { demande ->
        when {
            demande.url.encodedPath.endsWith("token/") -> json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
            demande.method == HttpMethod.Patch -> when (val code = statutMissions()) {
                HttpStatusCode.OK -> json("""{"id":"m1"}""")
                HttpStatusCode.Forbidden -> json("""{"detail":"Interdit."}""", code)
                else -> respond("", code)
            }
            else -> json("""[{"id":"m1","titre":"Reconnaissance","statut":"EN_COURS"}]""")
        }
    }

    @Test fun unChangementDeclareHorsLigneAttendPuisPartAuRetourDuReseau() = runTest {
        var code = HttpStatusCode.ServiceUnavailable
        val banc = bancConnecte { code }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.depot.declarerStatut(mission, StatutMission.EN_COURS)

        // Hors ligne : rien ne part, rien ne se perd, et l'écran le sait.
        assertEquals(0, banc.depot.envoyerLaFile())
        val enAttente = banc.file.actions.value.single()
        assertEquals(1, enAttente.tentatives)
        assertTrue(superposerLaFile(listOf(mission), banc.file.actions.value).single().nonConfirme)

        // Le téléphone redémarre entre-temps : la file est relue du disque.
        val apresRedemarrage = FileAttente(banc.magasin) { banc.maintenant }.also { it.restaurer() }
        assertEquals(enAttente.id, apresRedemarrage.actions.value.single().id)

        // Le réseau revient.
        code = HttpStatusCode.OK
        assertEquals(1, banc.depot.envoyerLaFile(force = true))
        assertTrue(banc.file.actions.value.isEmpty())
        assertEquals(StatutMission.EN_COURS, banc.depot.missions.value.single().statut)
    }

    @Test fun leReculEspaceLesEssaisSansForcage() = runTest {
        val banc = bancConnecte { HttpStatusCode.ServiceUnavailable }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.depot.declarerStatut(mission, StatutMission.EN_COURS)
        banc.depot.envoyerLaFile()
        val appels = banc.demandes.size
        banc.depot.envoyerLaFile()                       // trop tôt : aucun appel
        assertEquals(appels, banc.demandes.size)
        banc.maintenant += FileAttente.RECUL_INITIAL_MS  // le délai est passé
        banc.depot.envoyerLaFile()
        assertEquals(appels + 1, banc.demandes.size)
        assertEquals(5_000L, FileAttente.recul(1))
        assertEquals(10_000L, FileAttente.recul(2))
        assertEquals(FileAttente.RECUL_MAX_MS, FileAttente.recul(30))
    }

    @Test fun unRefusResteVisibleEtNeBloquePasLaSuite() = runTest {
        val codes = ArrayDeque(listOf(HttpStatusCode.Forbidden, HttpStatusCode.OK))
        val banc = bancConnecte { codes.removeFirst() }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.depot.declarerStatut(mission, StatutMission.EN_COURS)
        banc.depot.declarerStatut(mission.copy(id = "m2", titre = "Ravitaillement"), StatutMission.EN_COURS)

        assertEquals(1, banc.depot.envoyerLaFile())
        val restante = banc.file.actions.value.single()
        assertEquals(EtatAction.REFUSEE, restante.etat)
        assertEquals("Interdit.", restante.erreur)

        // Un refus n'est jamais retenté : il faut l'écarter à la main.
        val appels = banc.demandes.size
        banc.depot.envoyerLaFile(force = true)
        assertEquals(appels, banc.demandes.size)
        banc.file.retirer(restante.id)
        assertTrue(banc.file.actions.value.isEmpty())
    }

    @Test fun lesActionsPartentDansLOrdreEtSArretentALaPremiereCoupure() = runTest {
        val codes = ArrayDeque(listOf(HttpStatusCode.OK, HttpStatusCode.ServiceUnavailable))
        val banc = bancConnecte { codes.removeFirstOrNull() ?: HttpStatusCode.ServiceUnavailable }
        banc.api.connecter("c@exemple.fr", "secret")
        for (n in 1..3) banc.depot.declarerStatut(mission.copy(id = "m$n"), StatutMission.EN_COURS)
        banc.depot.envoyerLaFile()
        assertEquals(listOf("m2", "m3"), banc.file.actions.value.map { it.cible })
        assertEquals(listOf(1, 0), banc.file.actions.value.map { it.tentatives })
    }
}
