package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import fr.assistacrise.mobile.domaine.SignalementPei
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
import kotlin.test.assertTrue

private const val POINTS_JSON = """{"emprise_connue":true,"tronque":false,"total":2,"resultats":[
 {"id":1,"source":"OSM","ref":"9","type_pei":"PI","type_libelle":"Poteau d'incendie","etat":"INCONNU","latitude":45.44,"longitude":4.387,"attribution":"© contributeurs OpenStreetMap (ODbL)"},
 {"id":2,"source":"SDIS","ref":"42-1","type_pei":"CI","type_libelle":"Citerne ou réserve","etat":"INDISPONIBLE","latitude":45.45,"longitude":4.39,"volume":120.0}]}"""

/** Le banc : un serveur simulé qui connaît (ou pas encore) les points d'eau. */
private class BancPointsEau(var serveurAJour: Boolean = true) {
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
            chemin.startsWith("points-eau") && !serveurAJour -> respondError(HttpStatusCode.NotFound)
            chemin == "points-eau/" -> respond(POINTS_JSON, HttpStatusCode.OK, entete)
            chemin == "points-eau/signalements/" && demande.method == HttpMethod.Get ->
                respond("""[{"id":"s1","genre":"INDISPONIBLE","genre_libelle":"Indisponible","statut":"VALIDE","statut_libelle":"Validé","pei":1}]""", HttpStatusCode.OK, entete)
            chemin == "points-eau/signalements/" -> respond("""{"id":"s1"}""", HttpStatusCode.Created, entete)
            chemin == "points-eau/signalements/photo/" -> respond("""{"id":"d1","sha256":"abc"}""", HttpStatusCode.Created, entete)
            else -> respond("{}", HttpStatusCode.OK, entete)
        }
    }), "https://exemple.test/api", session)
    private var n = 0
    val pointsEau = DepotPointsEau(api, magasin, file) { "cle${n++}" }
    val synchro = Synchronisation(api, file, DepotMissions(api, magasin, file), DepotEquipes(api, magasin, file), pointsEau = pointsEau)

    suspend fun connecte() = apply { session.ouvrir("A", "R", Compte(id = "u1")) }
    fun envoisVers(chemin: String) = demandes.filter { it.method == HttpMethod.Post && it.url.encodedPath.endsWith(chemin) }
}

private val crise = Crise(id = "c1", nom = "Feu de la Loire", latitude = 45.44, longitude = 4.387)
private fun signalement(id: String = "s1") =
    SignalementPei(id = id, genre = "INDISPONIBLE", pei = 1, latitude = 45.44, longitude = 4.387, observeLe = "2026-11-24T09:00:00Z")

class PointsEauTest {
    @Test fun lesPointsAutourDesCrisesSontGardesPourLaCarteHorsReseau() = runTest {
        val banc = BancPointsEau().connecte()
        assertTrue(banc.pointsEau.rafraichir(listOf(crise, crise.copy(id = "c2", ouverte = false))) is Reponse.Ok)
        assertEquals(listOf(1L, 2L), banc.pointsEau.points.value.map { it.id })
        assertEquals(1, banc.demandes.count { it.url.encodedPath.endsWith("points-eau/") })   // la crise close n'est pas lue
        assertEquals("Validé", banc.pointsEau.suivi.value.single().statutLibelle)
        // Sans réseau, la copie reste ; relue par un dépôt neuf (redémarrage du téléphone).
        banc.panne = true
        assertTrue(banc.pointsEau.rafraichir(listOf(crise)) is Reponse.Injoignable)
        val relu = DepotPointsEau(banc.api, banc.magasin, banc.file) { "x" }.also { it.restaurer() }
        assertEquals(2, relu.points.value.size)
        assertEquals("INDISPONIBLE", relu.points.value[1].etat)
    }

    @Test fun unSignalementEtSaPhotoPartentDansLOrdreEtLaPhotoQuitteLeTelephone() = runTest {
        val banc = BancPointsEau().connecte()
        banc.pointsEau.signaler(signalement(), "Point d'eau — Indisponible")
        banc.pointsEau.ajouterPhoto("s1", byteArrayOf(1, 2, 3), PhotoEnAttente(cle = "", empreinte = "abc"), "Photo")
        assertEquals(1, banc.pointsEau.enFile().size)
        assertEquals(2, banc.synchro.envoyerLaFile(force = true))
        assertEquals(1, banc.envoisVers("points-eau/signalements/").size)
        assertEquals(1, banc.envoisVers("points-eau/signalements/photo/").size)
        assertTrue(banc.file.actions.value.isEmpty())
        assertEquals(null, banc.magasin.lire("photo-cle0"))
    }

    @Test fun unServeurPasEncoreAJourGardeLaFile() = runTest {
        val banc = BancPointsEau(serveurAJour = false).connecte()
        banc.pointsEau.signaler(signalement(), "Point d'eau — Indisponible")
        assertEquals(0, banc.synchro.envoyerLaFile(force = true))
        assertEquals(listOf(ActionEnAttente.GENRE_SIGNALEMENT_PEI), banc.file.actions.value.map { it.genre })
        // Le serveur se met à jour : le signalement part.
        banc.serveurAJour = true
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
    }
}
