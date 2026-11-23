package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Alerte
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Creneau
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.Etape
import fr.assistacrise.mobile.domaine.Grille
import fr.assistacrise.mobile.domaine.JourDeGrille
import fr.assistacrise.mobile.domaine.alertesNouvelles
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

private const val CAMPAGNE = """{"id":"c1","periode_debut":"2026-11-20","periode_fin":"2026-11-22","cloturee":false,"repondu":false,"creneaux_declares":0}"""
private fun notification(id: String, suite: String = "") =
    """{"id":"$id","genre":"CAMPAGNE","titre":"Réserve : êtes-vous disponible ?","corps":"Vigilance orange.","institution_nom":"Réserve","campagne":$CAMPAGNE$suite}"""

/**
 * Un faux serveur à réponses par chemin. `panne = true` : il ne répond plus (502), ce que
 * l'application doit traiter comme une absence de réponse.
 */
private class BancBenevole(
    // Un compte neuf : aucune notification, aucune mission, aucune équipe.
    private val reponses: MutableMap<String, String> = mutableMapOf("mes-notifications/" to "[]", "missions/" to "[]", "teams/mes-equipes/" to "[]"),
) {
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
            else -> respond(reponses[chemin] ?: "{}", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }
    }), "https://exemple.test/api", session)
    val notifications = DepotNotifications(api, magasin) { "installation-de-test-0001" }
    val missions = DepotMissions(api, magasin, file)
    val equipes = DepotEquipes(api, magasin, file)
    val benevole = DepotBenevole(api, magasin)
    val veille = Veille(magasin, notifications, equipes, missions) { relire ->
        if (relire) benevole.chargerLesDossiers(equipes.equipes.value.map { it.id }.toSet())
        benevole.dossiers.value
    }

    suspend fun connecte() = apply { session.ouvrir("A", "R", Compte(id = "u1")) }
    fun repond(chemin: String, corps: String) { reponses[chemin] = corps }
    fun envois(chemin: String) = demandes.filter { it.method == HttpMethod.Post && it.url.encodedPath.endsWith(chemin) }
        .map { Json.parseToJsonElement((it.body as TextContent).text).jsonObject }
}

class NotificationsTest {
    @Test fun lireLaListeNAccuseRien() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        banc.notifications.rafraichir()
        assertEquals(1, banc.notifications.notifications.value.size)
        assertTrue(banc.envois("accuser/").isEmpty())
        assertEquals(1, banc.notifications.nonVues())
    }

    @Test fun unAccuseDonneSansReseauPartAuRetour() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        banc.notifications.rafraichir()

        banc.panne = true
        banc.notifications.noter(Etape.LUE, listOf("n1"))
        // Il est sur disque : une application tuée entre-temps ne l'oublie pas.
        val relance = DepotNotifications(banc.api, banc.magasin) { "x" }.also { it.restaurer() }
        banc.panne = false
        assertTrue(relance.envoyerLesAccuses())

        val parti = banc.envois("accuser/").last()
        assertEquals("LUE", parti.getValue("etape").jsonPrimitive.content)
        assertEquals(listOf("n1"), parti.getValue("ids").jsonArray.map { it.jsonPrimitive.content })
        // Et il ne repart pas une seconde fois.
        val avant = banc.envois("accuser/").size
        relance.envoyerLesAccuses()
        assertEquals(avant, banc.envois("accuser/").size)
    }

    @Test fun onNAccusePasCeQueLeServeurSaitDeja() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-notifications/", "[${notification("n1", ""","date_remise":"2026-11-14T10:00:00Z"""")}]")
        banc.notifications.rafraichir()
        banc.notifications.noter(Etape.REMISE, listOf("n1"))
        assertTrue(banc.envois("accuser/").isEmpty())
    }

    @Test fun lIdentifiantDInstallationSurvitALaDeconnexion() = runTest {
        val banc = BancBenevole().connecte()
        val avant = banc.notifications.installation()
        banc.notifications.toutEffacer()
        assertEquals(avant, banc.notifications.installation())
        assertTrue(banc.demandes.any { it.method == HttpMethod.Delete && it.url.encodedPath.endsWith("mon-appareil/") })
    }

    @Test fun uneCampagneSansReponseAttendUneReponse() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        banc.notifications.rafraichir()
        val n = banc.notifications.notifications.value.single()
        assertTrue(n.attendUneReponse)
        assertFalse(n.campagne!!.aReponduNon)
        assertTrue(n.campagne!!.copy(repondu = true).aReponduNon)
    }
}

class VeilleTest {
    private val message = """{"messages":[{"event_id":"e1","texte":"Rendez-vous au PC","expediteur_nom":"Alex","horodatage":5}]}"""

    @Test fun lePremierReleveNeFaitRienSonner() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        banc.repond("missions/", """[{"id":"m1","titre":"Pompage"}]""")
        assertEquals(emptyList(), banc.veille.relever { true })
    }

    @Test fun ceQuiArriveEnsuiteSonneUneSeuleFois() = runTest {
        val banc = BancBenevole().connecte()
        banc.veille.relever { true }
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        banc.repond("missions/", """[{"id":"m1","titre":"Pompage"}]""")
        banc.repond("teams/mes-equipes/", """[{"id":"t1","name":"Équipe Nord"}]""")
        banc.repond("teams/t1/messagerie-unifiee/", message)

        val sonnees = banc.veille.relever { true }!!
        assertEquals(setOf(Alerte.Genre.NOTIFICATION, Alerte.Genre.MISSION, Alerte.Genre.MESSAGE), sonnees.map { it.genre }.toSet())
        assertEquals("Équipe Nord", sonnees.first { it.genre == Alerte.Genre.MESSAGE }.titre)
        assertEquals(emptyList(), banc.veille.relever { true })
    }

    @Test fun unDossierNouvellementConfieAMonEquipeSonne() = runTest {
        // 23/11/2026 : « ils attribueront des missions » -- un dossier confié sonne, comme une mission.
        val banc = BancBenevole().connecte()
        banc.repond("teams/mes-equipes/", """[{"id":"t1","name":"Équipe Nord"}]""")
        banc.repond("dossiers/", "[]")
        banc.veille.relever { true }
        banc.repond("dossiers/", """[{"id":"d9","titre":"Cave inondée","commune":"Rive-de-Gier","equipe":"t1","equipe_nom":"Équipe Nord","priorite":"URGENTE","statut":"AFFECTE"}]""")
        val sonnees = banc.veille.relever { true }!!
        val dossier = sonnees.single { it.genre == Alerte.Genre.DOSSIER }
        assertEquals("d9", dossier.cible)
        assertTrue(dossier.urgent)
        assertEquals(emptyList(), banc.veille.relever { true })
    }

    @Test fun uneNotificationAfficheeEstAccuseeRemise() = runTest {
        val banc = BancBenevole().connecte()
        banc.veille.relever { true }
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        banc.veille.relever { true }
        assertEquals("REMISE", banc.envois("accuser/").single().getValue("etape").jsonPrimitive.content)
    }

    @Test fun siLeSystemeRefuseDAfficherRienNEstAccuseEtOnRetentera() = runTest {
        val banc = BancBenevole().connecte()
        banc.veille.relever { true }
        banc.repond("mes-notifications/", "[${notification("n1")}]")
        assertEquals(emptyList(), banc.veille.relever { false })
        assertTrue(banc.envois("accuser/").isEmpty())
        assertEquals(1, banc.veille.relever { true }!!.size)
    }

    @Test fun mesPropresMessagesNeSonnentPas() = runTest {
        val banc = BancBenevole().connecte()
        banc.veille.relever { true }
        banc.repond("teams/mes-equipes/", """[{"id":"t1","name":"Équipe Nord"}]""")
        banc.repond("teams/t1/messagerie-unifiee/", """{"messages":[{"event_id":"e1","texte":"Bien reçu","moi":true,"horodatage":5}]}""")
        assertEquals(emptyList(), banc.veille.relever { true })
    }

    @Test fun sansServeurLeReleveLeDit() = runTest {
        val banc = BancBenevole().connecte()
        banc.panne = true
        assertNull(banc.veille.relever { true })
    }

    @Test fun laRegleDeNouveaute() {
        val a = Alerte("a", Alerte.Genre.MISSION, "", "")
        assertEquals(emptyList(), alertesNouvelles(listOf(a), null))
        assertEquals(listOf(a), alertesNouvelles(listOf(a), emptySet()))
        assertEquals(emptyList(), alertesNouvelles(listOf(a), setOf("a")))
    }
}

class BenevoleTest {
    private val grille = """{"ressources":[{"institution_nom":"Réserve"}],"jours":[{"date":"2026-11-20","creneaux":{"MATIN":false,"MIDI":false,"SOIR":false,"NUIT":false}}],"campagne":{"id":"c1","intitule":"Vigilance","institution_nom":"Réserve","periode_debut":"2026-11-20","periode_fin":"2026-11-20"}}"""

    @Test fun uneCaseCocheeDepuisUneCampagneLuiEstRattachee() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-disponibilites/", grille)
        banc.benevole.chargerLaGrille("c1")
        assertTrue(banc.demandes.last().url.encodedQuery.contains("campagne=c1"))

        assertIs<Reponse.Ok<Unit>>(banc.benevole.declarer("2026-11-20", Creneau.MATIN, true))

        val envoi = banc.envois("mes-disponibilites/").single()
        assertEquals("c1", envoi.getValue("campagne").jsonPrimitive.content)
        assertEquals("MATIN", envoi.getValue("creneau").jsonPrimitive.content)
        assertTrue(banc.benevole.grille.value!!.jours.single().coche(Creneau.MATIN))
    }

    @Test fun sansServeurLaCaseNeChangePas() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-disponibilites/", grille)
        banc.benevole.chargerLaGrille(null)
        banc.panne = true
        assertIs<Reponse.Injoignable>(banc.benevole.declarer("2026-11-20", Creneau.MATIN, true))
        assertFalse(banc.benevole.grille.value!!.jours.single().coche(Creneau.MATIN))
    }

    @Test fun touteLaJourneeCocheLesQuatreCreneaux() {
        val g = Grille(jours = listOf(JourDeGrille("2026-11-20"))).avec("2026-11-20", null, true)
        assertTrue(g.jours.single().complet)
        assertTrue(g.avec("2026-11-20", null, false).jours.single().vide)
    }

    @Test fun direNonAppelleLeServeurEtRelitLaGrille() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-disponibilites/", grille)
        banc.benevole.chargerLaGrille("c1")
        val avant = banc.demandes.size
        assertIs<Reponse.Ok<Unit>>(banc.benevole.repondreIndisponible("c1"))
        assertEquals("c1", banc.envois("indisponible/").single().getValue("campagne").jsonPrimitive.content)
        assertEquals(avant + 2, banc.demandes.size)
    }

    @Test fun seulsLesDossiersDeMesEquipesSontGardesLUrgentDAbord() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("dossiers/", """[
            {"id":"d1","titre":"Cave inondée","equipe":"t1","priorite":"NORMALE","statut":"AFFECTE"},
            {"id":"d2","titre":"Personne isolée","equipe":"t1","priorite":"URGENTE","statut":"AFFECTE"},
            {"id":"d3","titre":"Ailleurs","equipe":"t9","priorite":"URGENTE","statut":"AFFECTE"},
            {"id":"d4","titre":"Fini","equipe":"t1","priorite":"URGENTE","statut":"CLOTURE"}]""")
        banc.benevole.chargerLesDossiers(setOf("t1"))
        // Le dossier clos (d4) ne reste pas sur le téléphone (23/11/2026).
        assertEquals(listOf("d2", "d1"), banc.benevole.dossiers.value.map(Dossier::id))
    }

    @Test fun laFicheNEnvoieJamaisLeSecteur() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("ma-fiche-benevole/", """{"adresse":"1 rue des Lilas","departement_code":"33"}""")
        banc.benevole.chargerLaFiche("u1")
        banc.benevole.enregistrerLaFiche(banc.benevole.fiche.value!!.copy(ville = " Bordeaux "))
        val envoi = banc.demandes.last { it.method == HttpMethod.Patch }
        val corps = Json.parseToJsonElement((envoi.body as TextContent).text).jsonObject
        assertFalse("departement_code" in corps)
        assertEquals("Bordeaux", corps.getValue("ville").jsonPrimitive.content)
    }

    @Test fun laFicheRelitSesCompetencesEtLesRenvoieParIdentifiant() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("competences/", """[{"id":"t","nom":"Technique","parent":null,"active":true},{"id":"p","nom":"Pompage","parent":"t","active":true}]""")
        banc.repond("ma-fiche-benevole/", """{"adresse":"1 rue des Lilas","competences_detail":[{"id":"p","nom":"Pompage","parent":"t"}]}""")
        banc.benevole.chargerLaFiche("u1")
        assertEquals(listOf("Pompage"), banc.benevole.fiche.value!!.competences.map { it.nom })
        assertEquals(2, banc.benevole.competences.value.size)
        val fiche = banc.benevole.fiche.value!!
        banc.benevole.enregistrerLaFiche(fiche.copy(competences = fiche.competences + banc.benevole.competences.value.first()))
        val envoi = banc.demandes.last { it.method == HttpMethod.Patch }
        val corps = Json.parseToJsonElement((envoi.body as TextContent).text).jsonObject
        assertEquals(listOf("p", "t"), corps.getValue("competences").jsonArray.map { it.jsonPrimitive.content })
    }
}

class MobilisationTest {
    private val jeton = "aB3-xY_9aB3-xY_9aB3-xY_9aB3-xY_9aB3-xY_9abc"

    @Test fun leJetonSeLitDansToutesLesFormesDAttestation() {
        assertEquals(jeton, fr.assistacrise.mobile.domaine.jetonDeMobilisation("https://app.reserve-resilience.org/verifier-mobilisation/$jeton"))
        assertEquals(jeton, fr.assistacrise.mobile.domaine.jetonDeMobilisation(" https://autre-domaine.fr/api/verifier-mobilisation/$jeton/ "))
        assertEquals(jeton, fr.assistacrise.mobile.domaine.jetonDeMobilisation("https://x.fr/verifier-mobilisation/$jeton/donnees/?a=1"))
    }

    @Test fun unQrCodeQuelconqueNEstPasUneAttestation() {
        assertNull(fr.assistacrise.mobile.domaine.jetonDeMobilisation("https://exemple.fr/promo"))
        assertNull(fr.assistacrise.mobile.domaine.jetonDeMobilisation("https://x.fr/verifier-mobilisation/"))
        assertNull(fr.assistacrise.mobile.domaine.jetonDeMobilisation("https://x.fr/verifier-mobilisation/<script>alert(1)</script>aaaaaaaaaaaa"))
    }

    @Test fun sansCompteLaVerificationPartSansJeton() = runTest {
        val banc = BancBenevole()
        banc.repond("verifier-mobilisation/$jeton/donnees/", """{"valide":true,"connue":true,"motif":"Attestation valide.","complet":false,"reference":"AB12CD34","crise":"Crue"}""")
        val r = banc.api.verifierMobilisation(jeton)
        assertIs<Reponse.Ok<fr.assistacrise.mobile.domaine.Verdict>>(r)
        assertTrue(r.valeur.valide)
        assertNull(r.valeur.destinataire)
        assertNull(banc.demandes.single().headers[HttpHeaders.Authorization])
    }

    @Test fun connecteLaVerificationPorteLeCompteEtRendLeNom() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("verifier-mobilisation/$jeton/donnees/", """{"valide":false,"connue":true,"motif":"Cette attestation a été révoquée.","complet":true,"destinataire":"Camille Durand","lieu":"PC de crise"}""")
        val r = banc.api.verifierMobilisation(jeton) as Reponse.Ok
        assertFalse(r.valeur.valide)
        assertEquals("Camille Durand", r.valeur.destinataire)
        assertEquals("Bearer A", banc.demandes.single().headers[HttpHeaders.Authorization])
    }

    @Test fun seulesMesMobilisationsSePresententEtRestentLisiblesSansReseau() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("mes-mobilisations/", """[
            {"id":"11111111-aaaa","cible_utilisateur":"u1","statut":"REVOQUEE","jeton_verification":"$jeton"},
            {"id":"22222222-bbbb","cible_utilisateur":"u1","statut":"ACTIVE","jeton_verification":"$jeton","crise_nom":"Crue"},
            {"id":"33333333-cccc","cible_utilisateur":"u9","statut":"ACTIVE","jeton_verification":"$jeton"}]""")
        banc.benevole.chargerLesMobilisations("u1")
        assertEquals(listOf("22222222", "11111111"), banc.benevole.mobilisations.value.map { it.reference })
        assertEquals("https://x.fr/verifier-mobilisation/$jeton", banc.benevole.mobilisations.value.first().adresseDeVerification("https://x.fr/"))

        val relance = DepotBenevole(banc.api, banc.magasin).also { it.restaurer() }
        assertEquals(2, relance.mobilisations.value.size)
    }
}

class MonCompteTest {
    @Test fun leProfilModifieEstCeluiQueLaSessionGarde() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("me/", """{"id":"u1","first_name":"Camille","last_name":"Martin","phone_number":"0611111111"}""")
        val r = banc.api.modifierProfil(fr.assistacrise.mobile.domaine.Profil(" Camille ", "Martin", "0611111111"))
        assertIs<Reponse.Ok<Compte>>(r)
        assertEquals("Camille Martin", banc.session.compte.value?.nomComplet)
        assertEquals(HttpMethod.Patch, banc.demandes.single().method)
    }

    @Test fun changerDeMotDePasseDemandeLAncienSaufPourUnCompteQuiNEnAPas() = runTest {
        val banc = BancBenevole().connecte()
        banc.api.changerMotDePasse("ancien", "nouveau-secret")
        banc.api.changerMotDePasse(null, "nouveau-secret")
        assertEquals(listOf("change-password/", "definir-mon-mot-de-passe/"), banc.demandes.map { it.url.encodedPath.removePrefix("/api/") })
        assertEquals("nouveau-secret", banc.envois("definir-mon-mot-de-passe/").single().getValue("nouveau_mot_de_passe").jsonPrimitive.content)
    }

    @Test fun lesReglesDuMotDePasseSontDitesAvantLEnvoi() {
        val v = { a: String?, n: String, c: String -> fr.assistacrise.mobile.domaine.validerMotDePasse(a, n, c) }
        assertTrue("new_password" in v("a", "court", "court"))
        assertTrue("confirmation" in v("a", "assez-long", "autre-chose"))
        assertTrue("old_password" in v("", "assez-long", "assez-long"))
        assertTrue(v(null, "assez-long", "assez-long").isEmpty())
    }

    @Test fun redeposerUnePieceRefuseeLaRemplaceAuLieuDeDeclarerDeuxFois() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("qualifications-membres/", """[{"id":"q1","qualification":"cat1","statut":"REFUSEE","motif_refus":"Illisible"}]""")
        banc.repond("qualifications/", """[{"id":"cat1","nom":"Permis B","conservation":{"regime":"VERIFIER_DETRUIRE"}},{"id":"cat2","nom":"PSE1","actif":false}]""")
        banc.benevole.chargerMesDocuments("u1")
        assertEquals(listOf("Permis B"), banc.benevole.catalogue.value.map { it.nom })
        assertTrue(banc.benevole.catalogue.value.single().conservation!!.phrase.contains("détruit"))

        banc.benevole.deposerJustificatif("u1", "cat1", byteArrayOf(1, 2), "permis.jpg", "image/jpeg", null)
        val envoi = banc.demandes.first { it.method == HttpMethod.Patch }
        assertTrue(envoi.url.encodedPath.endsWith("qualifications-membres/q1/"))

        banc.benevole.deposerJustificatif("u1", "cat9", byteArrayOf(1, 2), "pse.pdf", "application/pdf", "2024-05-01")
        assertTrue(banc.demandes.any { it.method == HttpMethod.Post && it.url.encodedPath.endsWith("qualifications-membres/") })
    }
}

/** Recevoir les alertes de sa commune : on cherche, on s'abonne, on se désabonne — pour soi-même. */
class AbonnementAlerteTest {

    @Test fun chercherSaCommunePuisSAbonnerEtSeDesabonner() = runTest {
        val banc = BancBenevole().connecte()
        banc.repond("alertes-population/collectivites/", """[{"id":"i1","nom":"Mairie de Saint-Chamond"}]""")
        banc.repond("alertes-population/abonnement/", """[{"institution":"i1","institution_nom":"Mairie de Saint-Chamond"}]""")

        val trouvees = assertIs<Reponse.Ok<List<fr.assistacrise.mobile.domaine.Collectivite>>>(banc.api.collectivitesPourAlerte("Saint Cha")).valeur
        assertEquals("Mairie de Saint-Chamond", trouvees.single().nom)
        // L'espace du nom saisi ne casse pas l'adresse.
        assertEquals("Saint Cha", banc.demandes.last().url.parameters["q"])

        assertIs<Reponse.Ok<Unit>>(banc.api.sAbonnerAuxAlertes("i1"))
        assertEquals("i1", banc.envois("alertes-population/abonnement/").single()["institution"]!!.jsonPrimitive.content)

        val abonnements = assertIs<Reponse.Ok<List<fr.assistacrise.mobile.domaine.AbonnementAlerte>>>(banc.api.mesAbonnementsAlerte()).valeur
        assertEquals("i1", abonnements.single().id)
        assertEquals("Mairie de Saint-Chamond", abonnements.single().nom)

        assertIs<Reponse.Ok<Unit>>(banc.api.seDesabonnerDesAlertes("i1"))
        val retrait = banc.demandes.last()
        assertEquals(HttpMethod.Delete, retrait.method)
        assertEquals("i1", retrait.url.parameters["institution"])
    }
}
