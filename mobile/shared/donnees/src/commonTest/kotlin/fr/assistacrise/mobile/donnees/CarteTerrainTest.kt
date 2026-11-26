package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Compte
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
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Heures en ms, sur une journée d'essai : « 10:00 » → 10 h. */
private fun h(x: Int) = x * 3_600_000L
private fun iso(heure: Int) = "J$heure"

/** La carte du terrain (27/11/2026) : marqueurs du central, manifestation du jour, présences. */
class CarteTerrainTest {
    private val demandes = mutableListOf<HttpRequestData>()
    private val magasin = MagasinEnMemoire()
    private val session = Session(magasin)
    private var maintenant = h(11)
    private val api = ClientApi(HttpClient(MockEngine { demande ->
        demandes += demande
        val chemin = demande.url.encodedPath.removePrefix("/api/")
        val entete = headersOf(HttpHeaders.ContentType, "application/json")
        when {
            chemin == "marqueurs-terrain/" && demande.method == HttpMethod.Get -> respond("""[{"id":"k1","emoji":"⛔","genre":"ROUTE_COUPEE",
                "route":true,"latitude":44.85,"longitude":-0.57,"auteur_nom":"Léa","cree_le":"2026-11-27T10:00:00Z"}]""", HttpStatusCode.OK, entete)
            chemin == "marqueurs-terrain/" -> respond("""{"id":"k2","emoji":"🔥","latitude":44.86,"longitude":-0.57}""", HttpStatusCode.Created, entete)
            chemin == "marqueurs-terrain/k1/" -> respond("""{"id":"k3","emoji":"🚧","route":true,"latitude":44.85,"longitude":-0.57}""", HttpStatusCode.OK, entete)
            chemin == "carte-terrain/perimetre/" -> respond("""{"raison":"engagement","crises":[{"id":"c1234567-x","nom":"Crue",
                "latitude":44.84,"longitude":-0.58,"zone":{"type":"Polygon","coordinates":[[[-0.6,44.8],[-0.5,44.8],[-0.5,44.9],[-0.6,44.8]]]}}]}""",
                HttpStatusCode.OK, entete)
            chemin == "manifestations/" -> respond("""{"manifestations":[
                {"id":"m1","titre":"Course","debut":"${iso(9)}","fin":"${iso(13)}","je_suis_inscrit":true},
                {"id":"m2","titre":"Autre jour","debut":"${iso(60)}","fin":"${iso(64)}","je_suis_inscrit":true},
                {"id":"m3","titre":"Pas inscrit","debut":"${iso(9)}","fin":"${iso(13)}","je_suis_inscrit":false}],
                "associations_organisees":[]}""", HttpStatusCode.OK, entete)
            chemin == "manifestations/m1/" -> respond("""{"id":"m1","titre":"Course","debut":"${iso(9)}","fin":"${iso(13)}","je_suis_inscrit":true,
                "postes":[{"id":"p1","intitule":"PC","debut":"${iso(9)}","fin":"${iso(12)}","mon_statut":"PRESENT",
                           "type_point_libelle":"PC de manifestation","latitude":44.9,"longitude":-0.5},
                          {"id":"p2","intitule":"Carrefour","debut":"${iso(9)}","fin":"${iso(13)}","mon_statut":null,
                           "type_point_libelle":"Point de signalisation","latitude":44.91,"longitude":-0.51}]}""", HttpStatusCode.OK, entete)
            chemin == "manifestations/m2/" -> respond("""{"id":"m2","titre":"Autre jour","debut":"${iso(60)}","fin":"${iso(64)}","je_suis_inscrit":true,
                "postes":[{"id":"p3","intitule":"Départ","debut":"${iso(60)}","fin":"${iso(64)}","mon_statut":"INSCRIT"}]}""", HttpStatusCode.OK, entete)
            else -> respond("{}", HttpStatusCode.OK, entete)
        }
    }), "https://exemple.test/api", session)
    private val depot = DepotCarteTerrain(api, magasin, { it.removePrefix("J").toIntOrNull()?.let(::h) }, { maintenant })

    @Test fun marqueursEtManifestationDuJourGardesPourLeHorsReseau() = runTest {
        session.ouvrir("A", "R", Compte(id = "u1"))
        assertTrue(depot.rafraichir() is Reponse.Ok)
        assertEquals(listOf("k1"), depot.marqueurs.value.map { it.id })
        assertEquals(listOf("m1"), depot.manifestations.value.map { it.id })     // ni l'autre jour, ni sans inscription
        assertEquals(2, depot.manifestations.value.single().postes.size)
        // Relu du magasin, sans réseau.
        val autre = DepotCarteTerrain(api, magasin, { it.removePrefix("J").toIntOrNull()?.let(::h) }, { maintenant })
        autre.restaurer()
        assertEquals(listOf("k1"), autre.marqueurs.value.map { it.id })
        assertEquals(listOf("m1"), autre.manifestations.value.map { it.id })
    }

    @Test fun manifestationsAVenirGardeesPourLeHorsReseau() = runTest {
        session.ouvrir("A", "R", Compte(id = "u1"))
        depot.rafraichir()
        // Inscrit, du jour à J+30 ; celle du jour reste seule dans les manifestations du jour.
        assertEquals(listOf("m1", "m2"), depot.aVenir.value.map { it.id })
        assertEquals(listOf("m1"), depot.manifestations.value.map { it.id })
        assertEquals(3, depot.liste.value.size)
        val autre = DepotCarteTerrain(api, magasin, { it.removePrefix("J").toIntOrNull()?.let(::h) }, { maintenant })
        autre.restaurer()
        assertEquals("Départ", autre.detailGarde("m2")?.postes?.single()?.intitule)
        assertEquals(3, autre.liste.value.size)
    }

    @Test fun perimetreEtZoneDuHorsLigne() = runTest {
        session.ouvrir("A", "R", Compte(id = "u1"))
        depot.rafraichir()
        assertEquals("engagement", depot.perimetre.value.raison)
        val lieux = depot.lieuxDeLaZone()
        // Les sommets du contour de la crise (pas son centre), puis les postes placés de la manifestation.
        assertTrue((44.8 to -0.6) in lieux && (44.9 to -0.5) in lieux && (44.91 to -0.51) in lieux)
        assertTrue((44.84 to -0.58) !in lieux)
        assertEquals("cc1234567-mm1", depot.cleDeLaZone())
        val autre = DepotCarteTerrain(api, magasin, { it.removePrefix("J").toIntOrNull()?.let(::h) }, { maintenant })
        autre.restaurer()
        assertEquals("cc1234567-mm1", autre.cleDeLaZone())
    }

    @Test fun presenceDuPointageALaFinDuCreneau() = runTest {
        session.ouvrir("A", "R", Compte(id = "u1"))
        depot.rafraichir()
        assertEquals(listOf("p1"), depot.presencesEnCours().map { it.second.id })
        maintenant = h(12) + 60_000            // le créneau du PC est fini
        assertTrue(depot.presencesEnCours().isEmpty())
        assertTrue(depot.presenceTermineeRecemment())
    }

    @Test fun poserEtChangerUneRoute() = runTest {
        session.ouvrir("A", "R", Compte(id = "u1"))
        val m = fr.assistacrise.mobile.domaine.MarqueursRadio.Marqueur("🔥", 44.86, -0.57, "fumée")
        val r = api.poserMarqueur(m, crise = "c1", manifestation = null, dejaParRadio = "MESHCORE")
        assertEquals("k2", (r as Reponse.Ok).valeur.id)
        val corps = (demandes.last().body as TextContent).text
        assertTrue("\"deja_par_radio\":\"MESHCORE\"" in corps && "\"crise\":\"c1\"" in corps && "\"source\":\"APPLICATION\"" in corps)
        val e = api.etatRoute("k1", "ROUTE_UNE_VOIE", null)
        assertEquals("🚧", (e as Reponse.Ok).valeur.emoji)
        assertEquals(HttpMethod.Patch, demandes.last().method)
    }
}
