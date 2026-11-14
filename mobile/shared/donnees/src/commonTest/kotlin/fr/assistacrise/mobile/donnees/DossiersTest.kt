package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Commentaire
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.Deposant
import fr.assistacrise.mobile.domaine.Depot
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.GenreDepot
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import fr.assistacrise.mobile.domaine.Releve
import fr.assistacrise.mobile.domaine.TypeDepot
import fr.assistacrise.mobile.domaine.filDuDossier
import fr.assistacrise.mobile.domaine.rangerParMission
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.forms.MultiPartFormDataContent
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

private val DOSSIER = Dossier(id = "d1", titre = "Cave inondée", equipe = "t1", mission = "m1")
private val OCTETS = byteArrayOf(-1, -40, -1, -32, 1, 2, 3)

private class BancDossiers(var empreinteServeur: String = "abc123") {
    val demandes = mutableListOf<HttpRequestData>()
    var panne = false
    val magasin = MagasinEnMemoire()
    val session = Session(magasin)
    val file = FileAttente(magasin) { 1_000_000L }
    val api = ClientApi(HttpClient(MockEngine { demande ->
        demandes += demande
        val chemin = demande.url.encodedPath.removePrefix("/api/")
        when {
            panne -> respondError(HttpStatusCode.BadGateway)
            chemin == "documents/" && demande.method == HttpMethod.Post ->
                respond("""{"id":"p1","sha256":"$empreinteServeur","latitude":44.84,"longitude":-0.57}""", HttpStatusCode.Created, headersOf(HttpHeaders.ContentType, "application/json"))
            chemin == "documents/" || chemin == "dossier-commentaires/" && demande.method == HttpMethod.Get ->
                respond("[]", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            else -> respond("{}", HttpStatusCode.Created, headersOf(HttpHeaders.ContentType, "application/json"))
        }
    }), "https://exemple.test/api", session)
    private var n = 0
    val dossiers = DepotDossiers(api, magasin, file) { "cle${n++}" }
    val synchro = Synchronisation(api, file, DepotMissions(api, magasin, file), DepotEquipes(api, magasin, file), dossiers)

    suspend fun connecte() = apply { session.ouvrir("A", "R", Compte(id = "u1")) }
    fun photosEnvoyees() = demandes.filter { it.method == HttpMethod.Post && it.url.encodedPath.endsWith("documents/") }
}

class PhotosDeTerrainTest {
    private val photo = PhotoEnAttente(cle = "", empreinte = "ABC123", commentaire = "40 cm d'eau", priseLe = 5, latitude = 44.84, longitude = -0.57)

    @Test fun unePhotoPriseSansReseauAttendChiffreePuisPart() = runTest {
        val banc = BancDossiers().connecte()
        banc.panne = true
        banc.dossiers.ajouterPhoto(DOSSIER, OCTETS, photo)
        banc.synchro.envoyerLaFile(force = true)
        val enAttente = banc.file.actions.value.single()
        assertEquals(ActionEnAttente.GENRE_PHOTO, enAttente.genre)
        // Les octets sont dans le magasin (chiffré sur le téléphone), pas dans la file.
        assertTrue(OCTETS.contentEquals(banc.dossiers.octetsEnAttente(banc.dossiers.lirePhotoEnAttente(enAttente)!!)))

        banc.panne = false
        banc.synchro.envoyerLaFile(force = true)

        assertTrue(banc.file.actions.value.isEmpty())
        assertIs<MultiPartFormDataContent>(banc.photosEnvoyees().last().body)
        // Une fois arrivée, plus aucun octet ne reste sur le téléphone.
        assertNull(banc.magasin.contenu["photo-cle0"])
    }

    @Test fun lEmpreinteDuServeurEstCompareeACelleDuTelephone() = runTest {
        val banc = BancDossiers(empreinteServeur = "autre-chose").connecte()
        banc.dossiers.ajouterPhoto(DOSSIER, OCTETS, photo)
        banc.synchro.envoyerLaFile(force = true)
        val refusee = banc.file.actions.value.single()
        assertEquals(EtatAction.REFUSEE, refusee.etat)
        assertTrue(refusee.erreur!!.contains("empreinte"))
    }

    @Test fun laCasseDeLEmpreinteNeCompteePas() = runTest {
        val banc = BancDossiers(empreinteServeur = "abc123").connecte()
        banc.dossiers.ajouterPhoto(DOSSIER, OCTETS, photo)   // « ABC123 » côté téléphone
        banc.synchro.envoyerLaFile(force = true)
        assertTrue(banc.file.actions.value.isEmpty())
    }

    @Test fun ecarterUnePhotoEffaceSesOctets() = runTest {
        val banc = BancDossiers().connecte()
        banc.panne = true
        banc.dossiers.ajouterPhoto(DOSSIER, OCTETS, photo)
        val action = banc.file.actions.value.single()
        banc.dossiers.oublierLesOctets(action)
        assertNull(banc.magasin.contenu["photo-cle0"])
    }
}

class CommentairesDeTerrainTest {
    @Test fun unCommentaireEcritSansReseauResteVisibleEtPartAuRetour() = runTest {
        val banc = BancDossiers().connecte()
        banc.panne = true
        banc.dossiers.commenter(DOSSIER, " Pompe en place. ")
        banc.synchro.envoyerLaFile(force = true)

        val fil = filDuDossier(listOf(Commentaire("c0", "Arrivés sur place", "Alex", null)), banc.file.actions.value, "d1") { null }
        assertEquals(listOf("Arrivés sur place", "Pompe en place."), fil.map { it.texte })
        assertTrue(fil.last().enAttente)

        banc.panne = false
        banc.synchro.envoyerLaFile(force = true)
        assertTrue(banc.file.actions.value.isEmpty())
        val envoi = banc.demandes.last { it.method == HttpMethod.Post && it.url.encodedPath.endsWith("dossier-commentaires/") }
        assertNotNull(envoi)
    }

    @Test fun leFilDUnDossierNeMontrePasLesCommentairesEnAttenteDUnAutre() = runTest {
        val banc = BancDossiers().connecte()
        banc.panne = true
        banc.dossiers.commenter(DOSSIER.copy(id = "d2"), "ailleurs")
        assertTrue(filDuDossier(emptyList(), banc.file.actions.value, "d1") { null }.isEmpty())
    }
}

class RangementTest {
    @Test fun lesDossiersSontRangesSousLeurMission() {
        val a = Dossier(id = "a", mission = "m1"); val b = Dossier(id = "b", mission = null); val c = Dossier(id = "c", mission = "m-inconnue")
        val r = rangerParMission(listOf(a, b, c), setOf("m1"))
        assertEquals(listOf("a"), r.parMission.getValue("m1").map(Dossier::id))
        // Une mission que je ne vois pas : le dossier n'est pas perdu, il est avec les autres.
        assertEquals(listOf("b", "c"), r.sansMission.map(Dossier::id))
    }

    @Test fun uneOffreDAideChoisieSurLaCartePartAvecSonLieu() {
        val corps = DepotCitoyen.corps(Depot(
            GenreDepot.OFFRE, Crise("c1"), Deposant("Camille", "Durand", "c@exemple.fr", "0600000000"),
            titre = "Groupe électrogène", type = TypeDepot("t1", "Matériel"), position = Releve(44.84, -0.57, 0, 0f),
        ))
        assertEquals("t1", corps.getValue("offer_type").jsonPrimitive.content)
        assertEquals("SRID=4326;POINT(-0.57 44.84)", corps.getValue("location").jsonPrimitive.content)
        assertEquals("offres/", GenreDepot.OFFRE.chemin)
    }
}
