package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

/** Ce qui est terminé et transmis quitte le téléphone (23/11/2026). */
class PurgeTest {
    private val json = headersOf(HttpHeaders.ContentType, "application/json")
    private val compte = """{"access":"A1","refresh":"R1","user":{"id":"u1","email":"c@exemple.fr","first_name":"L","last_name":"M","type":"UTIL_SIMPLE"}}"""

    @Test fun uneMissionTermineeSEffaceSaufSiUneActionAttendEncore() = runTest {
        val magasin = MagasinEnMemoire()
        val session = Session(magasin)
        val file = FileAttente(magasin) { 1_000_000L }
        val api = ClientApi(HttpClient(MockEngine { d ->
            if (d.url.encodedPath.endsWith("token/")) respond(compte, HttpStatusCode.OK, json) else respond("""[{"id":"m1","titre":"En cours","statut":"EN_COURS"},{"id":"m2","titre":"Finie","statut":"TERMINEE"},
                       {"id":"m3","titre":"Finie, rapport à envoyer","statut":"TERMINEE"}]""", HttpStatusCode.OK, json)
        }), "https://exemple.test/api", session)
        api.connecter("c@exemple.fr", "secret")
        val missions = DepotMissions(api, magasin, file)
        file.ajouter(ActionEnAttente.GENRE_STATUT_MISSION, "m3", "TERMINEE", "« Finie » : terminée")
        missions.rafraichir()
        assertEquals(listOf("m1", "m3"), missions.missions.value.map { it.id })
        // Relue depuis le disque : la mission finie n'y est plus.
        val relu = DepotMissions(api, magasin, file).also { it.restaurer() }
        assertEquals(listOf("m1", "m3"), relu.missions.value.map { it.id })
    }

    @Test fun unDossierClosNeResteNiDansLaListeNiEnCache() = runTest {
        val magasin = MagasinEnMemoire()
        val api = ClientApi(HttpClient(MockEngine { d ->
            if (d.url.encodedPath.endsWith("token/")) respond(compte, HttpStatusCode.OK, json) else respond("""[{"id":"d1","equipe":"t1","statut":"AFFECTE"},{"id":"d2","equipe":"t1","statut":"CLOTURE"},
                       {"id":"d3","equipe":"t1","statut":"RESOLU"}]""", HttpStatusCode.OK, json)
        }), "https://exemple.test/api", Session(magasin))
        api.connecter("c@exemple.fr", "secret")
        val benevole = DepotBenevole(api, magasin)
        benevole.chargerLesDossiers(setOf("t1"))
        assertEquals(listOf("d1"), benevole.dossiers.value.map { it.id })
    }

    @Test fun seulesLesMissionsDeMesEquipesRestent() = runTest {
        val magasin = MagasinEnMemoire()
        val session = Session(magasin)
        val file = FileAttente(magasin) { 1_000_000L }
        val api = ClientApi(HttpClient(MockEngine { d ->
            if (d.url.encodedPath.endsWith("token/")) respond(compte, HttpStatusCode.OK, json)
            else respond("""[{"id":"m1","titre":"La mienne","statut":"EN_COURS","equipe_ids":["t1"]},
                             {"id":"m2","titre":"Celle d'une autre institution","statut":"EN_COURS","equipe_ids":["t9"]}]""", HttpStatusCode.OK, json)
        }), "https://exemple.test/api", session)
        api.connecter("c@exemple.fr", "secret")
        val missions = DepotMissions(api, magasin, file) { setOf("t1") }
        missions.rafraichir()
        assertEquals(listOf("m1"), missions.missions.value.map { it.id })
        // Équipes pas encore connues : rien n'est retiré.
        val sansEquipes = DepotMissions(api, magasin, file)
        sansEquipes.rafraichir()
        assertEquals(listOf("m1", "m2"), sansEquipes.missions.value.map { it.id })
    }
}
