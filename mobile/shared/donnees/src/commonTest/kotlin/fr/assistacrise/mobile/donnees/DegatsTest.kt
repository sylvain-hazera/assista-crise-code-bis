package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Constat
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

private const val SECTEUR_JSON = """{"crise":"c1","latitude":44.87,"longitude":-1.2,"rayon_m":1000,"genere_le":"2026-11-20T08:00:00Z",
 "adresses":[["a1","1 Rue des Pins, 33680 Le Porge",44.87,-1.2],["a3","3 Rue des Pins, 33680 Le Porge",44.87,-1.2003]],
 "biens":[{"id":"h1","ban_id":"a1","adresse":"1 Rue des Pins","latitude":44.87,"longitude":-1.2,"statut_evaluation":"DETRUITE","type_bien":null,"position_corrigee":false}],
 "dossiers":[{"id":"d1","numero":"DOS-1","titre":"Dégâts","statut":"NOUVEAU","habitation":"h1"}],"cercles":[]}"""

private class BancDegats(var empreinteServeur: String = "abc") {
    val demandes = mutableListOf<HttpRequestData>()
    var panne = false
    val magasin = MagasinEnMemoire()
    val session = Session(magasin)
    val file = FileAttente(magasin) { 1_000_000L }
    val api = ClientApi(HttpClient(MockEngine { demande ->
        demandes += demande
        val chemin = demande.url.encodedPath.removePrefix("/api/")
        val entete = headersOf(HttpHeaders.ContentType, "application/json")
        when {
            panne -> respondError(HttpStatusCode.BadGateway)
            chemin == "habitations/secteur/" -> respond(SECTEUR_JSON, HttpStatusCode.OK, entete)
            chemin == "types-bien/" -> respond("""[{"id":"t1","nom":"Véhicule","a_une_adresse":false}]""", HttpStatusCode.OK, entete)
            chemin == "habitations/tournee/" -> respond("""{"points":[{"ban_id":"a3","libelle":"3 Rue des Pins","latitude":44.87,"longitude":-1.2003,"distance_m":12.0}]}""", HttpStatusCode.OK, entete)
            chemin == "habitations/constat/" -> respond("""{"id":"h9","constat":"k1"}""", HttpStatusCode.Created, entete)
            chemin == "habitations/constat-photo/" -> respond("""{"id":"p1","empreinte":"$empreinteServeur","habitation":"h9"}""", HttpStatusCode.Created, entete)
            else -> respond("{}", HttpStatusCode.OK, entete)
        }
    }), "https://exemple.test/api", session)
    private var n = 0
    val degats = DepotDegats(api, magasin, file) { "cle${n++}" }
    val synchro = Synchronisation(api, file, DepotMissions(api, magasin, file), DepotEquipes(api, magasin, file), degats = degats)

    suspend fun connecte() = apply { session.ouvrir("A", "R", Compte(id = "u1")) }
    fun envoisVers(chemin: String) = demandes.filter { it.method == HttpMethod.Post && it.url.encodedPath.endsWith(chemin) }
}

private fun constat(id: String = "k1", banId: String? = "a3") =
    Constat(id = id, crise = "c1", banId = banId, statutEvaluation = "DEGATS_FORTS", constateLe = "2026-11-20T09:00:00Z")

class EvaluationAPiedTest {
    @Test fun embarquerLeSecteurLitLesAdressesCompactesEtLeGardeChiffre() = runTest {
        val banc = BancDegats().connecte()
        val secteur = (banc.degats.embarquer("c1", 44.87, -1.2) as Reponse.Ok).valeur
        assertEquals(listOf("a1", "a3"), secteur.adresses.map { it.banId })
        assertEquals("3 Rue des Pins, 33680 Le Porge", secteur.adresses[1].libelle)
        assertEquals("h1", secteur.dossiers.single().habitation)
        assertEquals("Véhicule", banc.degats.types.value.single().nom)
        // Relu du magasin par un dépôt neuf (redémarrage du téléphone).
        val relu = DepotDegats(banc.api, banc.magasin, banc.file) { "x" }.also { it.restaurer() }
        assertEquals(2, relu.secteur.value?.adresses?.size)
    }

    @Test fun sansReseauLaTourneeSeCalculeSurLeSecteur() = runTest {
        val banc = BancDegats().connecte()
        assertEquals(false, banc.degats.tournee("c1", 44.87, -1.2).horsLigne)
        banc.degats.embarquer("c1", 44.87, -1.2)
        banc.panne = true
        val tournee = banc.degats.tournee("c1", 44.87, -1.2002)
        assertTrue(tournee.horsLigne)
        assertEquals(setOf("a1", "a3"), tournee.points.mapNotNull { it.banId }.toSet())
        // Une autre crise : rien d'embarqué pour elle, on le dit.
        assertNotNull(banc.degats.tournee("c2", 44.87, -1.2).refus)
    }

    @Test fun leConstatEtSaPhotoPartentDansLOrdreEtLeSecteurSEfface() = runTest {
        val banc = BancDegats(empreinteServeur = "ABC").connecte()
        banc.degats.embarquer("c1", 44.87, -1.2)
        banc.panne = true
        banc.degats.constater(constat(), "Évaluation : 3 Rue des Pins")
        banc.degats.ajouterPhoto("k1", byteArrayOf(1, 2, 3), PhotoEnAttente(cle = "", empreinte = "abc", priseLe = 5), "Photo")
        banc.synchro.envoyerLaFile(force = true)
        assertEquals(listOf(ActionEnAttente.GENRE_CONSTAT, ActionEnAttente.GENRE_PHOTO_CONSTAT), banc.file.actions.value.map { it.genre })
        assertTrue(banc.degats.tournee("c1", 44.87, -1.2003).points.first { it.banId == "a3" }.enAttente)
        assertNotNull(banc.degats.secteur.value)                              // rien n'est parti : il reste

        banc.panne = false
        banc.demandes.clear()                                                  // la tentative pendant la panne ne compte pas
        banc.synchro.envoyerLaFile(force = true)
        assertTrue(banc.file.actions.value.isEmpty())
        assertEquals(1, banc.envoisVers("habitations/constat/").size)
        assertEquals(1, banc.envoisVers("habitations/constat-photo/").size)
        assertNull(banc.degats.secteur.value)                                 // tout est parti : effacé
        assertNull(banc.magasin.lire("degats-secteur"))
    }

    @Test fun uneEmpreinteDifferenteGardeLaPhotoRefuseeEtVisible() = runTest {
        val banc = BancDegats(empreinteServeur = "autre").connecte()
        banc.degats.constater(constat(), "Évaluation")
        banc.degats.ajouterPhoto("k1", byteArrayOf(9), PhotoEnAttente(cle = "", empreinte = "abc", priseLe = 5), "Photo")
        banc.synchro.envoyerLaFile(force = true)
        val restante = banc.file.actions.value.single()
        assertEquals(ActionEnAttente.GENRE_PHOTO_CONSTAT, restante.genre)
        assertTrue(restante.erreur!!.contains("empreinte"))
    }
}
