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
    private fun mission(id: String, vararg equipes: String) = fr.assistacrise.mobile.domaine.MissionAffichee(fr.assistacrise.mobile.domaine.Mission(id = id, titre = id, equipes = equipes.toList()), false)
    private fun equipe(id: String, active: String? = null) = fr.assistacrise.mobile.domaine.Equipe(id = id, nom = id, missionActive = active)

    @Test fun unDossierSansMissionEcriteEstDansLaMissionEnCoursDeSonEquipe() {
        val r = fr.assistacrise.mobile.domaine.rangerParEquipe(
            listOf(equipe("t1", active = "m1")), listOf(mission("m1", "t1")),
            listOf(Dossier(id = "a", equipe = "t1", mission = null), Dossier(id = "b", equipe = "t1", mission = "m1")),
        ).single()
        assertEquals(listOf("a", "b"), r.missions.single().dossiers.map(Dossier::id))
        assertTrue(r.sansMission.isEmpty())
    }

    @Test fun laMissionEcriteSurLeDossierLEmporteEtLaMissionEnCoursVientEnTete() {
        val r = fr.assistacrise.mobile.domaine.rangerParEquipe(
            listOf(equipe("t1", active = "m2")), listOf(mission("m1", "t1"), mission("m2", "t1")),
            listOf(Dossier(id = "a", equipe = "t1", mission = "m1"), Dossier(id = "b", equipe = "t1")),
        ).single()
        assertEquals(listOf("m2", "m1"), r.missions.map { it.mission.mission.id })
        assertEquals(listOf("b"), r.missions.first().dossiers.map(Dossier::id))
    }

    @Test fun sansMissionMarqueeEnCoursLaSeuleMissionDeLEquipeSert() {
        val r = fr.assistacrise.mobile.domaine.rangerParEquipe(listOf(equipe("t1")), listOf(mission("m1", "t1")), listOf(Dossier(id = "a", equipe = "t1"))).single()
        assertEquals(listOf("a"), r.missions.single().dossiers.map(Dossier::id))
        // Deux missions possibles : on ne devine pas, le dossier est montré à part.
        val ambigu = fr.assistacrise.mobile.domaine.rangerParEquipe(listOf(equipe("t1")), listOf(mission("m1", "t1"), mission("m2", "t1")), listOf(Dossier(id = "a", equipe = "t1"))).single()
        assertEquals(listOf("a"), ambigu.sansMission.map(Dossier::id))
    }

    @Test fun uneEquipeSansMissionMontreSesDossiersCommeUneAnomalie() {
        val r = fr.assistacrise.mobile.domaine.rangerParEquipe(listOf(equipe("t1")), emptyList(), listOf(Dossier(id = "a", equipe = "t1"))).single()
        assertTrue(r.missions.isEmpty())
        assertEquals(listOf("a"), r.sansMission.map(Dossier::id))
    }

    @Test fun uneMissionPartageeMontreAChaqueEquipeSesSeulsDossiers() {
        val r = fr.assistacrise.mobile.domaine.rangerParEquipe(
            listOf(equipe("t1", "m1"), equipe("t2", "m1")), listOf(mission("m1", "t1", "t2")),
            listOf(Dossier(id = "a", equipe = "t1"), Dossier(id = "b", equipe = "t2")),
        )
        assertEquals(listOf(listOf("a"), listOf("b")), r.map { it.missions.single().dossiers.map(Dossier::id) })
    }

    @Test fun lesMissionsHorsDeMesEquipesRestentVisibles() {
        val r = fr.assistacrise.mobile.domaine.rangerParEquipe(listOf(equipe("t1", "m1")), listOf(mission("m1", "t1"), mission("m9", "t9")), emptyList())
        assertNull(r.last().equipe)
        assertEquals(listOf("m9"), r.last().missions.map { it.mission.mission.id })
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

class PrecisionsTest {
    private val hebergement = fr.assistacrise.mobile.domaine.Precisions.pour(GenreDepot.OFFRE, "Hébergement")

    @Test fun unHebergementSeDecritCommeSurLeSite() {
        val cles = hebergement.map { it.cle }
        assertTrue(cles.containsAll(listOf("hebergement_duree", "type_loyer", "capacite_adultes", "pmr_compatible", "accueil_sinistres", "renouvelable")))
        assertTrue(fr.assistacrise.mobile.domaine.Precisions.pour(GenreDepot.SIGNALEMENT, "Hébergement").isEmpty())
        assertTrue("zone_recherche_rayon_km" in fr.assistacrise.mobile.domaine.Precisions.pour(GenreDepot.DEMANDE, "hébergement").map { it.cle })
    }

    @Test fun unChampConditionnelNeSeMontreNiNePartSansSaCondition() {
        val p = fr.assistacrise.mobile.domaine.Precisions
        assertTrue("acces_etage" !in p.visibles(hebergement, mapOf("niveau_logement" to "PLAIN_PIED")).map { it.cle })
        assertTrue("acces_etage" in p.visibles(hebergement, mapOf("niveau_logement" to "ETAGE")).map { it.cle })
        // Saisi puis rendu sans objet : il ne part pas.
        val envoi = p.aEnvoyer(hebergement, mapOf("niveau_logement" to "PLAIN_PIED", "acces_etage" to "ESCALIER", "capacite_adultes" to "3", "nombre_pieces" to "abc"))
        assertTrue("acces_etage" !in envoi)
        assertEquals("3", envoi["capacite_adultes"])
        assertTrue("nombre_pieces" !in envoi)
        // Un oui/non part toujours, avec sa valeur par défaut s'il n'a pas été touché.
        assertEquals("true", envoi["accueil_sinistres"])
        assertEquals("false", envoi["jardin"])
    }

    @Test fun lesPrecisionsPartentDansLeCorps() {
        val corps = DepotCitoyen.corps(Depot(
            GenreDepot.OFFRE, Crise("c1"), Deposant("Camille", "Durand", "c@exemple.fr", "0600000000"),
            titre = "Chambre libre", type = TypeDepot("t1", "Hébergement"), precisions = mapOf("capacite_adultes" to "2"),
        ))
        assertEquals("2", corps.getValue("capacite_adultes").jsonPrimitive.content)
    }
}

class PhotoDeDepotTest {
    @Test fun unDepotAvecPhotoPartEnFormulaireSansLaNoteDeFile() = runTest {
        val banc = BancDossiers().connecte()
        val citoyen = DepotCitoyen(banc.api, banc.magasin, banc.file)
        val cle = banc.dossiers.garderOctets(OCTETS)
        citoyen.deposer(Depot(GenreDepot.SIGNALEMENT, Crise("c1"), Deposant("C", "D", "c@exemple.fr", "06"), titre = "Route coupée", type = TypeDepot("t1", "Danger"), position = Releve(44.8, -0.5, 0, 0f)), cle)

        banc.synchro.envoyerLaFile(force = true)

        assertTrue(banc.file.actions.value.isEmpty())
        val envoi = banc.demandes.last { it.url.encodedPath.endsWith("informations/") }
        assertIs<MultiPartFormDataContent>(envoi.body)
        assertNull(banc.magasin.contenu[cle])
    }

    @Test fun sansPhotoLeDepotResteEnJson() = runTest {
        val banc = BancDossiers().connecte()
        DepotCitoyen(banc.api, banc.magasin, banc.file).deposer(Depot(GenreDepot.DEMANDE, Crise("c1"), Deposant("C", "D", "c@exemple.fr", "06"), titre = "Eau potable", type = TypeDepot("t1", "Eau")))
        banc.synchro.envoyerLaFile(force = true)
        assertIs<io.ktor.http.content.TextContent>(banc.demandes.last { it.url.encodedPath.endsWith("demandes/") }.body)
    }
}
