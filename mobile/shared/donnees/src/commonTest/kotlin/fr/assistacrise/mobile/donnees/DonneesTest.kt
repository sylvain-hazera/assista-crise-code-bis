package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.sha256Hex
import fr.assistacrise.mobile.domaine.filDeMessages
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
    val equipes = DepotEquipes(api, magasin, file)
    /** Ce que la radio a émis, par équipe. `radioPresente = false` : pas de radio connectée. */
    val emisParRadio = mutableListOf<Pair<String, String>>()
    var radioPresente = false
    /** Ce que rend la radio quand elle émet : deux radios sur le téléphone rendent « MESHTASTIC,MESHCORE ». */
    var protocolesEmis = "MESHCORE"
    val synchro = Synchronisation(api, file, depot, equipes, radio = EmetteurRadio { equipe, texte ->
        if (radioPresente && equipe.canalMeshCore != null) { emisParRadio += equipe.nom to texte; protocolesEmis } else null
    })

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

    // --- Connexion en étapes et frein (15/11/2026) ----------------------------------------

    @Test fun lAdresseDitSIlFautUnCodeAvantLeMotDePasse() = runTest {
        val protege = Banc { json("""{"etape":"code"}""") }
        assertEquals(true, (protege.api.debutConnexion(" c@exemple.fr ") as Reponse.Ok).valeur)
        assertEquals("POST connexion/debut/", protege.chemins().single())
        assertEquals("c@exemple.fr", protege.demandes.single().corps().getValue("email").jsonPrimitive.content)

        val simple = Banc { json("""{"etape":"mot_de_passe"}""") }
        assertEquals(false, (simple.api.debutConnexion("c@exemple.fr") as Reponse.Ok).valeur)
    }

    @Test fun unServeurQuiIgnoreLesEtapesMeneAuMotDePasse() = runTest {
        val ancien = Banc { json("""{"detail":"Not found."}""", HttpStatusCode.NotFound) }
        assertEquals(false, (ancien.api.debutConnexion("c@exemple.fr") as Reponse.Ok).valeur)
    }

    @Test fun leJetonDuCodeAccompagneLeMotDePasse() = runTest {
        val banc = Banc { demande ->
            if (demande.url.encodedPath.endsWith("connexion/code/")) json("""{"jeton_etape":"J1"}""")
            else json("""{"access":"A1","refresh":"R1","user":$COMPTE,"appareil":"APPAREIL-1"}""")
        }
        val jeton = (banc.api.verifierCode("c@exemple.fr", " 123456 ") as Reponse.Ok).valeur
        assertEquals("123456", banc.demandes[0].corps().getValue("code").jsonPrimitive.content)
        assertIs<Reponse.Ok<*>>(banc.api.connecter("c@exemple.fr", "secret", jeton))
        assertEquals("J1", banc.demandes[1].corps().getValue("jeton_etape").jsonPrimitive.content)
    }

    @Test fun leTelephoneEstReconnuAuxConnexionsSuivantesMemeApresDeconnexion() = runTest {
        val banc = Banc { demande ->
            if (demande.url.encodedPath.endsWith("token/blacklist/")) json("{}")
            else json("""{"access":"A1","refresh":"R1","user":$COMPTE,"appareil":"APPAREIL-1"}""")
        }
        banc.api.connecter("c@exemple.fr", "secret")
        assertEquals("", banc.demandes[0].corps().getValue("appareil").jsonPrimitive.content)
        banc.api.deconnecter()
        banc.api.connecter("c@exemple.fr", "secret")
        assertEquals("APPAREIL-1", banc.demandes.last().corps().getValue("appareil").jsonPrimitive.content)
    }

    @Test fun renvoyerLeCodeRendLaPhraseDuServeur() = runTest {
        val banc = Banc { json("""{"detail":"Si un compte protégé existe à cette adresse, un code vient de lui être envoyé par e-mail."}""") }
        val r = banc.api.renvoyerCode(" c@exemple.fr ")
        assertEquals("POST connexion/envoyer-code/", banc.chemins().single())
        assertEquals("c@exemple.fr", banc.demandes.single().corps().getValue("email").jsonPrimitive.content)
        assertTrue((r as Reponse.Ok).valeur.contains("vient de lui être envoyé"))
    }

    @Test fun unCodeFauxEstDitSimplement() = runTest {
        val banc = Banc { json("""{"detail":"Code incorrect."}""", HttpStatusCode.Unauthorized) }
        val r = banc.api.verifierCode("c@exemple.fr", "000000")
        assertIs<Reponse.Refus>(r)
        assertEquals("Code incorrect.", r.message)
    }

    @Test fun tropDEssaisEstUnRefusQuiDitCombienAttendre() = runTest {
        val banc = Banc {
            json("""{"code":"TROP_D_ESSAIS","detail":"Trop d'essais. Réessayez dans 30 secondes.","attendre":"30"}""", HttpStatusCode.TooManyRequests)
        }
        val r = banc.api.connecter("c@exemple.fr", "faux")
        assertIs<Reponse.Refus>(r)
        assertEquals("Trop d'essais. Réessayez dans 30 secondes.", r.message)
    }

    @Test fun unCompteQuiDoitActiverSonCodeEstRenvoyeVersLeSite() = runTest {
        val banc = Banc {
            json("""{"code":"SECOND_FACTEUR_A_ACTIVER","detail":"Activez-le.","jeton_enrolement":"J"}""", HttpStatusCode.Forbidden)
        }
        val r = banc.api.connecter("c@exemple.fr", "secret")
        assertIs<Reponse.Refus>(r)
        assertTrue(r.message.contains("sur le site"))
        assertNull(banc.session.compte.value)
    }

    @Test fun lInscriptionEnvoieCeQueLeServeurAttend() = runTest {
        val banc = Banc { json("""{"id":"u9"}""", HttpStatusCode.Created) }
        val r = banc.api.inscrire(Inscription("Camille", "Durand", "c@exemple.fr", "0612345678", "71000", "Abcdef1!", true, true))
        assertIs<Reponse.Ok<*>>(r)
        // Le défi anti-robot est demandé d'abord ; ce serveur-ci n'en fournit pas, l'envoi part sans.
        assertEquals(listOf("GET inscription/defi/", "POST register/"), banc.chemins())
        val corps = banc.demandes.last().corps()
        assertEquals("UTIL_SIMPLE", corps.getValue("type").jsonPrimitive.content)
        assertEquals("c@exemple.fr", corps.getValue("username").jsonPrimitive.content)
        assertEquals("true", corps.getValue("souhaite_rejoindre_reserve").jsonPrimitive.content)
        assertNull(corps["defi"])
        assertNull(banc.demandes.last().jeton())
    }

    @Test fun lInscriptionResoutLeDefiDuServeurEtLeJointAuFormulaire() = runTest {
        // Le défi que rendrait le serveur pour le nombre 137 : l'empreinte de « sel137 ».
        val defi = """{"sel":"sel","empreinte":"${sha256Hex("sel137")}","maximum":500,"emis":10,"expire":20,"niveau":"NORMAL","signature":"sig"}"""
        val banc = Banc { demande ->
            if (demande.url.encodedPath.endsWith("inscription/defi/")) json(defi) else json("""{"id":"u9"}""", HttpStatusCode.Created)
        }
        val r = banc.api.inscrire(Inscription("Camille", "Durand", "c@exemple.fr", "0612345678", "71000", "Abcdef1!", true, true))
        assertIs<Reponse.Ok<*>>(r)
        val joint = banc.demandes.last().corps().getValue("defi").jsonObject
        assertEquals("137", joint.getValue("nombre").jsonPrimitive.content)
        assertEquals("sig", joint.getValue("signature").jsonPrimitive.content)
        assertEquals("sel", joint.getValue("sel").jsonPrimitive.content)
    }

    @Test fun unDefiJugeInsuffisantEstRefaitSansRienRedemanderALaPersonne() = runTest {
        var envois = 0
        val banc = Banc { demande ->
            when {
                demande.url.encodedPath.endsWith("inscription/defi/") ->
                    json("""{"sel":"s","empreinte":"${sha256Hex("s3")}","maximum":50,"emis":1,"expire":2,"niveau":"ELEVE","signature":"sig"}""")
                ++envois == 1 -> json("""{"code":"DEFI_REQUIS","detail":"Vérification requise."}""", HttpStatusCode.fromValue(428))
                else -> json("""{"id":"u9"}""", HttpStatusCode.Created)
            }
        }
        val r = banc.api.inscrire(Inscription("Camille", "Durand", "c@exemple.fr", "0612345678", "71000", "Abcdef1!", true, true))
        assertIs<Reponse.Ok<*>>(r)
        assertEquals(listOf("GET inscription/defi/", "POST register/", "GET inscription/defi/", "POST register/"), banc.chemins())
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
        val banc = Banc { throw IllegalStateException("pas de réseau") }
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
        assertEquals(0, banc.synchro.envoyerLaFile())
        val enAttente = banc.file.actions.value.single()
        assertEquals(1, enAttente.tentatives)
        assertTrue(superposerLaFile(listOf(mission), banc.file.actions.value).single().nonConfirme)

        // Le téléphone redémarre entre-temps : la file est relue du disque.
        val apresRedemarrage = FileAttente(banc.magasin) { banc.maintenant }.also { it.restaurer() }
        assertEquals(enAttente.id, apresRedemarrage.actions.value.single().id)

        // Le réseau revient.
        code = HttpStatusCode.OK
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        assertTrue(banc.file.actions.value.isEmpty())
        assertEquals(StatutMission.EN_COURS, banc.depot.missions.value.single().statut)
    }

    @Test fun leReculEspaceLesEssaisSansForcage() = runTest {
        val banc = bancConnecte { HttpStatusCode.ServiceUnavailable }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.depot.declarerStatut(mission, StatutMission.EN_COURS)
        banc.synchro.envoyerLaFile()
        val appels = banc.demandes.size
        banc.synchro.envoyerLaFile()                       // trop tôt : aucun appel
        assertEquals(appels, banc.demandes.size)
        banc.maintenant += FileAttente.RECUL_INITIAL_MS  // le délai est passé
        banc.synchro.envoyerLaFile()
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

        assertEquals(1, banc.synchro.envoyerLaFile())
        val restante = banc.file.actions.value.single()
        assertEquals(EtatAction.REFUSEE, restante.etat)
        assertEquals("Interdit.", restante.erreur)

        // Un refus n'est jamais retenté : il faut l'écarter à la main.
        val appels = banc.demandes.size
        banc.synchro.envoyerLaFile(force = true)
        assertEquals(appels, banc.demandes.size)
        banc.file.retirer(restante.id)
        assertTrue(banc.file.actions.value.isEmpty())
    }

    @Test fun lesActionsPartentDansLOrdreEtSArretentALaPremiereCoupure() = runTest {
        val codes = ArrayDeque(listOf(HttpStatusCode.OK, HttpStatusCode.ServiceUnavailable))
        val banc = bancConnecte { codes.removeFirstOrNull() ?: HttpStatusCode.ServiceUnavailable }
        banc.api.connecter("c@exemple.fr", "secret")
        for (n in 1..3) banc.depot.declarerStatut(mission.copy(id = "m$n"), StatutMission.EN_COURS)
        banc.synchro.envoyerLaFile()
        assertEquals(listOf("m2", "m3"), banc.file.actions.value.map { it.cible })
        assertEquals(listOf(1, 0), banc.file.actions.value.map { it.tentatives })
    }

    @Test fun uneActionQuiEchoueSansFinNeBloquePasLesSuivantesIndefiniment() = runTest {
        // m1 fait planter le serveur à chaque fois ; m2 passerait très bien.
        val banc = Banc { demande ->
            when {
                demande.url.encodedPath.endsWith("token/") -> json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
                demande.url.encodedPath.contains("m1") -> respond("", HttpStatusCode.InternalServerError)
                demande.method == HttpMethod.Patch -> json("""{"id":"m2"}""")
                else -> json("[]")
            }
        }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.depot.declarerStatut(mission.copy(id = "m1"), StatutMission.EN_COURS)
        banc.depot.declarerStatut(mission.copy(id = "m2"), StatutMission.EN_COURS)
        // Les premiers échecs bloquent la suite : l'ordre compte, et c'est peut-être le réseau.
        repeat(FileAttente.ESSAIS_BLOQUANTS) { assertEquals(0, banc.synchro.envoyerLaFile(force = true)) }
        assertEquals(2, banc.file.actions.value.size)
        // Au-delà, on la laisse de côté sans l'abandonner : m2 part, m1 reste et sera retentée.
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        assertEquals(listOf("m1"), banc.file.actions.value.map { it.cible })
    }
}

class MessagerieTest {
    private val fil = """{"messages":[{"event_id":"e1","source":"matrix","texte":"Bien reçu","horodatage":1000,"expediteur_nom":"Alex","moi":false,"urgent":false},{"event_id":"e2","source":"meshcore","texte":"En route","horodatage":2000,"expediteur_nom":"Camille","moi":true}]}"""

    private fun banc(ecriture: () -> HttpStatusCode) = Banc { demande ->
        val chemin = demande.url.encodedPath
        when {
            chemin.endsWith("token/") -> json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
            chemin.endsWith("mes-equipes/") -> json("""[{"id":"t1","name":"Alpha","engagement_debut":"2026-11-14T10:00:00Z","mission_active_titre":"Reconnaissance","canal_meshcore_nom":"#alpha"},{"id":"t2","name":"Bravo","engagement_debut":null}]""")
            demande.method == HttpMethod.Post -> if (ecriture() == HttpStatusCode.OK) json(fil) else respond("", ecriture())
            else -> json(fil)
        }
    }

    @Test fun lesEquipesEtLeurFilSontLisiblesApresRedemarrage() = runTest {
        val banc = banc { HttpStatusCode.OK }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        banc.equipes.rafraichirFil("t1")
        assertEquals(listOf(true, false), banc.equipes.equipes.value.map { it.engagee })

        val relance = DepotEquipes(banc.api, banc.magasin, banc.file).also { it.restaurer() }
        assertEquals("Alpha", relance.equipes.value.first().nom)
        val messages = filDeMessages(relance.fils.value.getValue("t1"), emptyList(), "t1")
        assertEquals(listOf(false, true), messages.map { it.parRadio })
    }

    @Test fun unMessageEcritHorsLigneAttendDansLeFilPuisPart() = runTest {
        var code = HttpStatusCode.ServiceUnavailable
        val banc = banc { code }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        val alpha = banc.equipes.equipes.value.first()
        banc.equipes.ecrire(alpha, "  Nous sommes sur place  ")
        banc.synchro.envoyerLaFile()

        val attente = filDeMessages(emptyList(), banc.file.actions.value, "t1").single()
        assertEquals("Nous sommes sur place", attente.texte)
        assertTrue(attente.enAttente && attente.moi)
        // Il n'apparaît pas dans le fil d'une autre équipe.
        assertTrue(filDeMessages(emptyList(), banc.file.actions.value, "t2").isEmpty())

        code = HttpStatusCode.OK
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        assertTrue(banc.file.actions.value.isEmpty())
        assertEquals(2, banc.equipes.fils.value.getValue("t1").size)
        assertEquals("Nous sommes sur place", banc.demandes.last().corps().getValue("texte").jsonPrimitive.content)
    }
}

class CoupureReseauTest {
    private val fil = """{"messages":[{"event_id":"e9","source":"meshcore","texte":"Alex: Bien reçu","horodatage":5000,"expediteur_nom":"Alex"}]}"""

    private fun banc(code: () -> HttpStatusCode) = Banc { demande ->
        val chemin = demande.url.encodedPath
        when {
            chemin.endsWith("token/") -> json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
            chemin.endsWith("mes-equipes/") -> json("""[{"id":"t1","name":"Alpha","canal_meshcore_nom":"#alpha"},{"id":"t2","name":"Bravo"}]""")
            code() == HttpStatusCode.OK -> json(fil)
            else -> respond("", code())
        }
    }

    @Test fun sansReseauLeMessagePartParLaRadioUneSeuleFoisPuisEstRemisAuServeur() = runTest {
        var code = HttpStatusCode.OK
        val banc = banc { code }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        code = HttpStatusCode.ServiceUnavailable
        banc.radioPresente = true
        banc.equipes.ecrire(banc.equipes.equipes.value.first(), "Nous sommes sur place")

        banc.synchro.envoyerLaFile(force = true)
        assertEquals(listOf("Alpha" to "Nous sommes sur place"), banc.emisParRadio)
        val action = banc.file.actions.value.single()
        assertTrue(action.parRadio && action.etat == EtatAction.EN_ATTENTE)
        val bulle = filDeMessages(emptyList(), banc.file.actions.value, "t1").single()
        assertTrue(bulle.parRadio && bulle.enAttente)

        // Nouveaux essais sans réseau : la radio n'émet pas une seconde fois.
        banc.synchro.envoyerLaFile(force = true)
        assertEquals(1, banc.emisParRadio.size)

        // Le réseau revient : le serveur reçoit le message, prévenu qu'il a déjà été émis.
        code = HttpStatusCode.OK
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        assertEquals("MESHCORE", banc.demandes.last().corps().getValue("deja_emis_radio").jsonPrimitive.content)
        assertTrue(banc.file.actions.value.isEmpty())
    }

    @Test fun deuxRadiosLeServeurApprendQueLeMessageEstPartiSurLesDeuxReseaux() = runTest {
        var code = HttpStatusCode.OK
        val banc = banc { code }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        code = HttpStatusCode.ServiceUnavailable
        banc.radioPresente = true
        banc.protocolesEmis = "MESHTASTIC,MESHCORE"
        banc.equipes.ecrire(banc.equipes.equipes.value.first(), "Deux reseaux")
        banc.synchro.envoyerLaFile(force = true)
        code = HttpStatusCode.OK
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        assertEquals("MESHTASTIC,MESHCORE", banc.demandes.last().corps().getValue("deja_emis_radio").jsonPrimitive.content)
    }

    @Test fun uneEquipeSansCanalOuUnTelephoneSansRadioAttendSimplementLeReseau() = runTest {
        var code = HttpStatusCode.OK
        val banc = banc { code }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.rafraichir()
        code = HttpStatusCode.ServiceUnavailable
        banc.equipes.ecrire(banc.equipes.equipes.value.first(), "Sans radio")       // pas de radio connectée
        banc.radioPresente = true
        banc.equipes.ecrire(banc.equipes.equipes.value.last(), "Sans canal")        // Bravo n'a pas de canal
        repeat(5) { banc.synchro.envoyerLaFile(force = true) }
        assertEquals(listOf("Alpha" to "Sans radio"), banc.emisParRadio)            // le premier, une fois la radio là
        assertEquals(listOf(true, false), banc.file.actions.value.map { it.parRadio })
    }

    @Test fun unMessageEntenduParLaRadioEntreDansLeFilPuisCedeLaPlaceACeluiDuServeur() = runTest {
        var code = HttpStatusCode.ServiceUnavailable
        val banc = banc { code }
        banc.api.connecter("c@exemple.fr", "secret")
        banc.equipes.entenduParRadio("t1", "Alex: Bien reçu", 1000)
        banc.equipes.entenduParRadio("t1", "Alex: Bien reçu", 4000)                 // le même, par un second relais
        banc.equipes.entenduParRadio("t1", "Dominique: Jamais relayé", 2000)
        val entendus = banc.equipes.fils.value.getValue("t1")
        assertEquals(listOf("Alex" to "Bien reçu", "Dominique" to "Jamais relayé"), entendus.map { it.auteur to it.texte })
        assertTrue(filDeMessages(entendus, emptyList(), "t1").all { it.parRadio })

        // Le réseau revient : le serveur rend « Bien reçu » ; l'autre, qu'aucune passerelle
        // n'a relayé, reste dans le fil du téléphone.
        code = HttpStatusCode.OK
        banc.equipes.rafraichirFil("t1")
        assertEquals(listOf("Jamais relayé", "Bien reçu"), banc.equipes.fils.value.getValue("t1").map { it.texte.removePrefix("Alex: ") })
    }
}

class SuiviTest {
    private val engagee = fr.assistacrise.mobile.domaine.Equipe(id = "t1", nom = "Alpha", engagementDebut = "2026-11-14T10:00:00Z")
    private val auRepos = engagee.copy(engagementDebut = null)
    private fun releve(lat: Double, instant: Long) = fr.assistacrise.mobile.domaine.Releve(lat, 4.83, instant)

    private fun banc() = Banc { demande ->
        if (demande.url.encodedPath.endsWith("token/")) json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
        else json("""{"id":"p"}""")
    }
    private fun suivi(banc: Banc) = DepotSuivi(banc.magasin, banc.file) { banc.maintenant }

    @Test fun rienNeDemarreSansConsentementNiSansEngagementConfirme() = runTest {
        val banc = banc(); val suivi = suivi(banc)
        assertTrue(!suivi.demarrerSiBesoin(listOf(engagee)))            // pas de consentement
        suivi.consentir(true)
        assertTrue(!suivi.demarrerSiBesoin(listOf(auRepos)))            // équipe au repos
        assertTrue(suivi.demarrerSiBesoin(listOf(engagee)))
        assertTrue(!suivi.demarrerSiBesoin(listOf(engagee)))            // déjà actif
    }

    @Test fun lArretNeDependJamaisDuServeur() = runTest {
        val banc = banc(); val suivi = suivi(banc)
        suivi.consentir(true); suivi.demarrerSiBesoin(listOf(engagee))
        // Pas de nouvelles du serveur : le suivi continue…
        assertNull(suivi.arreterSiBesoin(null))
        // …jusqu'au plafond, qui joue sans réseau.
        banc.maintenant += fr.assistacrise.mobile.domaine.ReglesSuivi.PLAFOND_MS
        assertEquals(fr.assistacrise.mobile.domaine.MotifArret.PLAFOND, suivi.arreterSiBesoin(null))
        assertTrue(!suivi.etat.value.actif)
    }

    @Test fun laFinDEngagementArreteEtLeSuivantRelance() = runTest {
        val banc = banc(); val suivi = suivi(banc)
        suivi.consentir(true); suivi.demarrerSiBesoin(listOf(engagee))
        assertEquals(fr.assistacrise.mobile.domaine.MotifArret.FIN_D_ENGAGEMENT, suivi.arreterSiBesoin(listOf(auRepos)))
        assertTrue(suivi.demarrerSiBesoin(listOf(engagee.copy(engagementDebut = "2026-11-15T08:00:00Z"))))
    }

    @Test fun unArretALaMainTientPourCetEngagementSeulement() = runTest {
        val banc = banc(); val suivi = suivi(banc)
        suivi.consentir(true); suivi.demarrerSiBesoin(listOf(engagee))
        suivi.arreterALaMain(listOf(engagee))
        assertTrue(!suivi.demarrerSiBesoin(listOf(engagee)))            // on ne piège personne
        assertTrue(suivi.demarrerSiBesoin(listOf(engagee.copy(engagementDebut = "2026-11-15T08:00:00Z"))))
    }

    @Test fun lEtatSurvitAuRedemarrageDuService() = runTest {
        val banc = banc(); val suivi = suivi(banc)
        suivi.consentir(true); suivi.demarrerSiBesoin(listOf(engagee))
        val relance = suivi(banc).also { it.restaurer() }
        assertEquals(banc.maintenant, relance.etat.value.depuis)
    }

    @Test fun laCadenceSuitLeDeplacementEtSeuleLaDernierePositionAttend() = runTest {
        val banc = banc(); val suivi = suivi(banc)
        banc.api.connecter("c@exemple.fr", "secret")
        suivi.consentir(true); suivi.demarrerSiBesoin(listOf(engagee))
        assertTrue(suivi.relever(releve(45.7500, 0)))                  // premier relevé
        assertTrue(!suivi.relever(releve(45.7600, 10_000)))            // trop tôt, même loin
        assertTrue(!suivi.relever(releve(45.7501, 60_000)))            // 11 m : immobile
        assertTrue(suivi.relever(releve(45.7510, 60_000)))             // 111 m : en mouvement
        assertTrue(suivi.relever(releve(45.7510, 60_000 + 5 * 60_000)))// immobile, mais 5 min
        // Trois relevés retenus, une seule action en file : la dernière.
        assertEquals(1, banc.file.actions.value.size)
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        val corps = banc.demandes.last().corps()
        assertEquals("45.751", corps.getValue("latitude").jsonPrimitive.content)
    }
}

class CitoyenTest {
    private val crise = fr.assistacrise.mobile.domaine.Crise(id = "c1", nom = "Crue de la Saône", suivie = true)
    private val moi = fr.assistacrise.mobile.domaine.Deposant("Camille", "Durand", "c@exemple.fr", "0612345678")
    private val ici = fr.assistacrise.mobile.domaine.Releve(45.75, 4.85, 0)
    private fun depot(genre: fr.assistacrise.mobile.domaine.GenreDepot) = fr.assistacrise.mobile.domaine.Depot(
        genre, crise, moi, titre = "Route coupée", type = fr.assistacrise.mobile.domaine.TypeDepot("t1", "Danger imminent"), position = ici,
    )

    @Test fun unSignalementSansPositionEstRefuseAvantDePartir() {
        val sans = depot(fr.assistacrise.mobile.domaine.GenreDepot.SIGNALEMENT).copy(position = null)
        assertTrue(fr.assistacrise.mobile.domaine.ChampsDepot.POSITION in fr.assistacrise.mobile.domaine.validerDepot(sans))
        // Une demande, elle, peut se passer de lieu.
        val demande = depot(fr.assistacrise.mobile.domaine.GenreDepot.DEMANDE).copy(position = null)
        assertTrue(fr.assistacrise.mobile.domaine.validerDepot(demande).isEmpty())
    }

    @Test fun laPositionPartEnTexteLongitudeDAbord() {
        val corps = DepotCitoyen.corps(depot(fr.assistacrise.mobile.domaine.GenreDepot.SIGNALEMENT))
        assertEquals("SRID=4326;POINT(4.85 45.75)", corps.getValue("location").jsonPrimitive.content)
        assertEquals("t1", corps.getValue("information_type").jsonPrimitive.content)
        assertEquals("Camille", corps.getValue("first_name_information").jsonPrimitive.content)
    }

    @Test fun uneCriseSansResponsableNAcceptePasDeDepot() {
        assertTrue(crise.accepteLesDepots)
        assertTrue(!crise.copy(suivie = false).accepteLesDepots)
        assertTrue(!crise.copy(ouverte = false).accepteLesDepots)
    }

    @Test fun unDepotFaitHorsLigneArriveTelQuelAuRetourDuReseau() = runTest {
        var code = HttpStatusCode.ServiceUnavailable
        val banc = Banc { demande ->
            when {
                demande.url.encodedPath.endsWith("token/") -> json("""{"access":"A1","refresh":"R1","user":$COMPTE}""")
                code == HttpStatusCode.OK -> json("""{"id":"d1"}""", HttpStatusCode.Created)
                else -> respond("", code)
            }
        }
        val citoyen = DepotCitoyen(banc.api, banc.magasin, banc.file)
        banc.api.connecter("c@exemple.fr", "secret")
        citoyen.deposer(depot(fr.assistacrise.mobile.domaine.GenreDepot.SECURITE).copy(adultes = 2, enfants = 1))
        assertEquals(0, banc.synchro.envoyerLaFile())
        assertEquals("Déclaration « en sécurité » — Crue de la Saône", banc.file.actions.value.single().libelle)

        code = HttpStatusCode.OK
        assertEquals(1, banc.synchro.envoyerLaFile(force = true))
        val envoi = banc.demandes.last()
        assertEquals("/api/declarations-securite/", envoi.url.encodedPath)
        assertEquals("2", envoi.corps().getValue("nombre_adultes").jsonPrimitive.content)
        assertEquals("c1", envoi.corps().getValue("crise").jsonPrimitive.content)
    }
}
