package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Champs
import fr.assistacrise.mobile.domaine.Commentaire
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Photo
import fr.assistacrise.mobile.domaine.Profil
import fr.assistacrise.mobile.domaine.TitreDuCatalogue
import fr.assistacrise.mobile.domaine.Creneau
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.Etape
import fr.assistacrise.mobile.domaine.Fiche
import fr.assistacrise.mobile.domaine.Grille
import fr.assistacrise.mobile.domaine.Notification
import fr.assistacrise.mobile.domaine.Titre
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.MessageEquipe
import fr.assistacrise.mobile.domaine.PositionMembre
import fr.assistacrise.mobile.domaine.Inscription
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.Mobilisation
import fr.assistacrise.mobile.domaine.Verdict
import fr.assistacrise.mobile.domaine.StatutMission
import io.ktor.client.HttpClient
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.forms.MultiPartFormDataContent
import io.ktor.client.request.forms.formData
import io.ktor.client.statement.readRawBytes
import io.ktor.http.Headers
import io.ktor.http.content.PartData
import io.ktor.client.request.header
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.contentType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/**
 * Ce qu'un appel peut donner. Trois issues, et la distinction entre les deux dernières est
 * ce sur quoi repose la file d'attente : un `Refus` est une réponse (inutile de réessayer),
 * `Injoignable` est une absence de réponse (on réessaiera).
 */
sealed class Reponse<out T> {
    data class Ok<T>(val valeur: T) : Reponse<T>()

    /** Le serveur a répondu non. `champs` : erreurs par nom de champ de l'API. */
    data class Refus(val code: Int, val message: String, val champs: Map<String, String> = emptyMap()) : Reponse<Nothing>()

    /** Pas de réponse exploitable : pas de réseau, délai dépassé, serveur en panne. */
    data class Injoignable(val message: String) : Reponse<Nothing>()
}

/**
 * Le seul endroit qui parle au serveur. `http` est fourni par la plateforme (OkHttp sur
 * Android, un faux dans les tests) ; `urlApi` se termine par `/api`.
 */
class ClientApi(
    private val http: HttpClient,
    private val urlApi: String,
    private val session: Session,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val verrouRafraichissement = Mutex()

    // --- Sans compte ---------------------------------------------------------------------

    /**
     * Première étape de la connexion : ce que demander après l'adresse. `true` = le compte
     * est protégé par un code de sécurité, à donner AVANT le mot de passe (tant qu'il ne l'a
     * pas été, le serveur ne regarde pas le mot de passe).
     *
     * Un serveur qui ne connaît pas cette étape (satellite resté sur une version plus
     * ancienne) répond 404 : on demande alors le mot de passe, comme avant.
     */
    suspend fun debutConnexion(email: String): Reponse<Boolean> {
        val corps = buildJsonObject { put("email", email.trim()) }
        return when (val r = appeler(HttpMethod.Post, "connexion/debut/", corps, jeton = null)) {
            is Reponse.Ok -> Reponse.Ok((r.valeur.jsonObject["etape"] as? JsonPrimitive)?.content == "code")
            is Reponse.Refus -> if (r.code == 404) Reponse.Ok(false) else r
            is Reponse.Injoignable -> r
        }
    }

    /** Deuxième étape des comptes protégés. Rend le jeton à joindre au mot de passe. */
    suspend fun verifierCode(email: String, code: String): Reponse<String> {
        val corps = buildJsonObject {
            put("email", email.trim()); put("code", code.trim()); put("appareil", session.appareil())
        }
        return when (val r = appeler(HttpMethod.Post, "connexion/code/", corps, jeton = null)) {
            is Reponse.Ok -> Reponse.Ok(r.valeur.jsonObject.texte("jeton_etape"))
            is Reponse.Refus -> if (r.code == 401) r.copy(message = "Code incorrect.") else r
            is Reponse.Injoignable -> r
        }
    }

    suspend fun connecter(email: String, motDePasse: String, jetonEtape: String = ""): Reponse<Compte> {
        val corps = buildJsonObject {
            put("email", email.trim()); put("password", motDePasse)
            put("jeton_etape", jetonEtape); put("appareil", session.appareil())
        }
        return when (val r = appeler(HttpMethod.Post, "token/", corps, jeton = null)) {
            is Reponse.Ok -> {
                val o = r.valeur.jsonObject
                val compte = json.decodeFromJsonElement(Compte.serializer(), o.getValue("user"))
                (o["appareil"] as? JsonPrimitive)?.content?.let { session.retenirAppareil(it) }
                session.ouvrir(o.texte("access"), o.texte("refresh"), compte)
                Reponse.Ok(compte)
            }
            is Reponse.Refus -> when {
                // SimpleJWT répond 401 en anglais, sans distinguer mauvais mot de passe et
                // compte inactif. On le dit en français, en couvrant les deux cas.
                r.code == 401 -> r.copy(
                    message = "Adresse ou mot de passe incorrect. Si votre compte attend une " +
                        "validation, il ne peut pas encore se connecter.",
                )
                // Compte à responsabilités dont le délai d'activation est passé : le code se
                // met en place sur le site, où l'on peut scanner un QR code avec ce téléphone.
                r.champs["code"] == SECOND_FACTEUR_A_ACTIVER -> r.copy(
                    message = "Votre compte doit être protégé par un code de sécurité. Activez-le " +
                        "sur le site (connectez-vous-y, il vous guidera), puis revenez ici.",
                )
                else -> r
            }
            is Reponse.Injoignable -> r
        }
    }

    /** Crée un compte de particulier. Le serveur envoie ensuite un e-mail de bienvenue. */
    suspend fun inscrire(i: Inscription): Reponse<Unit> {
        val corps = buildJsonObject {
            put("username", i.email.trim())
            put(Champs.EMAIL, i.email.trim())
            put(Champs.MOT_DE_PASSE, i.motDePasse)
            put("type", Compte.TYPE_UTILISATEUR_SIMPLE)
            put(Champs.PRENOM, i.prenom.trim())
            put(Champs.NOM, i.nom.trim())
            put(Champs.TELEPHONE, i.telephone.trim())
            put(Champs.CODE_POSTAL, i.codePostal.trim())
            // N'a d'effet que sur un domaine d'association qui tient une réserve : le
            // serveur le décide d'après l'hôte appelé, jamais d'après ce champ seul.
            put("souhaite_rejoindre_reserve", i.rejoindreLaReserve)
        }
        return appeler(HttpMethod.Post, "register/", corps, jeton = null).sansValeur()
    }

    /** Le serveur répond de la même façon que l'adresse existe ou non : on n'en déduit rien. */
    suspend fun demanderNouveauMotDePasse(email: String): Reponse<Unit> =
        appeler(HttpMethod.Post, "reset-password/request/", buildJsonObject { put("email", email.trim()) }, jeton = null)
            .sansValeur()

    /**
     * Soumet au serveur le jeton lu sur un QR code. **Fonctionne sans compte** : on vérifie
     * alors l'authenticité, sans apprendre ni le nom ni le lieu. Connecté, le verdict est complet.
     */
    suspend fun verifierMobilisation(jeton: String): Reponse<Verdict> {
        val chemin = "verifier-mobilisation/$jeton/donnees/"
        val r = if (session.jetonAcces != null) authentifie(HttpMethod.Get, chemin) else appeler(HttpMethod.Get, chemin, null, jeton = null)
        return r.transformer { json.decodeFromJsonElement(Verdict.serializer(), it) }
    }

    suspend fun mesMobilisations(): Reponse<List<Mobilisation>> = liste("mes-mobilisations/", Mobilisation.serializer())

    // --- Avec compte ---------------------------------------------------------------------

    suspend fun moi(): Reponse<Compte> = authentifie(HttpMethod.Get, "me/").transformer {
        json.decodeFromJsonElement(Compte.serializer(), it).also { compte -> session.mettreAJourLeCompte(compte) }
    }

    suspend fun missions(): Reponse<List<Mission>> = authentifie(HttpMethod.Get, "missions/").transformer {
        // Liste nue par défaut ; enveloppe {results: […]} si la pagination est un jour activée.
        val liste = if (it is JsonObject) it.getValue("results") else it
        json.decodeFromJsonElement(ListSerializer(Mission.serializer()), liste)
    }

    suspend fun changerStatutMission(id: String, statut: StatutMission): Reponse<Unit> =
        authentifie(HttpMethod.Patch, "missions/$id/", buildJsonObject { put("statut", statut.name) }).sansValeur()

    suspend fun mesEquipes(): Reponse<List<Equipe>> = authentifie(HttpMethod.Get, "teams/mes-equipes/").transformer {
        val liste = if (it is JsonObject) it.getValue("results") else it
        json.decodeFromJsonElement(ListSerializer(Equipe.serializer()), liste)
    }

    /** Le fil unique de l'équipe : salon Matrix et canaux radio, déjà fusionnés par le serveur. */
    suspend fun messagerie(idEquipe: String): Reponse<List<MessageEquipe>> =
        authentifie(HttpMethod.Get, "teams/$idEquipe/messagerie-unifiee/").transformer(::lireMessages)

    /** Le serveur diffuse sur toutes les voies de l'équipe à la fois, et rend le fil à jour. */
    suspend fun ecrireAEquipe(idEquipe: String, texte: String, dejaEmisParRadio: String? = null): Reponse<List<MessageEquipe>> =
        authentifie(HttpMethod.Post, "teams/$idEquipe/messagerie-unifiee/", buildJsonObject {
            put("texte", texte)
            // Le téléphone l'a déjà émis sur le canal radio de l'équipe pendant la coupure :
            // le serveur ne doit pas le rediffuser sur ce canal une seconde fois.
            // Il dit par quel protocole : l'autre réseau, lui, reste à servir par les ponts.
            if (dejaEmisParRadio != null) put("deja_emis_radio", dejaEmisParRadio)
        }).transformer(::lireMessages)

    suspend fun positionsEquipes(): Reponse<List<PositionMembre>> = authentifie(HttpMethod.Get, "positions-equipes/").transformer {
        val liste = if (it is JsonObject) it.getValue("results") else it
        json.decodeFromJsonElement(ListSerializer(PositionMembre.serializer()), liste)
    }

    /** Le serveur ne garde que ma dernière position, visible de mes équipes pendant trois heures. */
    suspend fun declarerMaPosition(latitude: Double, longitude: Double): Reponse<Unit> =
        authentifie(HttpMethod.Post, "ma-position/", buildJsonObject { put("latitude", latitude); put("longitude", longitude) })
            .sansValeur()

    /** Une liste du serveur, nue ou paginée, dans la forme demandée. */
    suspend fun <T> liste(chemin: String, forme: kotlinx.serialization.KSerializer<T>): Reponse<List<T>> =
        authentifie(HttpMethod.Get, chemin).transformer {
            val elements = if (it is JsonObject) it.getValue("results") else it
            json.decodeFromJsonElement(ListSerializer(forme), elements)
        }

    /** Dépose un corps JSON déjà formé (un dépôt citoyen sorti de la file). */
    suspend fun deposer(chemin: String, corps: String, photo: ByteArray? = null): Reponse<Unit> {
        val objet = runCatching { json.parseToJsonElement(corps).jsonObject }.getOrNull()
            ?: return Reponse.Refus(400, "Dépôt illisible.")
        // Les clés en « _ » sont des notes de la file (où attend la photo) : elles ne partent pas.
        val champs = JsonObject(objet.filterKeys { !it.startsWith("_") })
        if (photo == null) return authentifie(HttpMethod.Post, chemin, champs).sansValeur()
        // Avec une photo, le serveur attend un formulaire : les mêmes champs, en texte, et le fichier.
        return authentifie(HttpMethod.Post, chemin, formulaire = formData {
            champs.forEach { (cle, valeur) -> (valeur as? JsonPrimitive)?.takeIf { it !is kotlinx.serialization.json.JsonNull }?.let { append(cle, it.content) } }
            append("photo", photo, Headers.build {
                append(HttpHeaders.ContentType, "image/jpeg")
                append(HttpHeaders.ContentDisposition, "filename=\"photo.jpg\"")
            })
        }).sansValeur()
    }

    // --- Notifications ------------------------------------------------------------------

    /** Le téléphone se présente : c'est ce qui le rend joignable par une campagne. */
    suspend fun presenterAppareil(installation: String, plateforme: String, version: String, notificationsAutorisees: Boolean): Reponse<Unit> =
        authentifie(HttpMethod.Post, "mon-appareil/", buildJsonObject {
            put("installation", installation)
            put("plateforme", plateforme)
            put("version", version)
            put("notifications_autorisees", notificationsAutorisees)
        }).sansValeur()

    /** À la déconnexion : ce téléphone ne joint plus ce compte. */
    suspend fun oublierAppareil(installation: String): Reponse<Unit> =
        authentifie(HttpMethod.Delete, "mon-appareil/?installation=$installation").sansValeur()

    suspend fun notifications(): Reponse<List<Notification>> = liste("mes-notifications/", Notification.serializer())

    /** Dit au serveur où en sont ces notifications. Lire la liste, seul, n'accuse rien. */
    suspend fun accuser(etape: Etape, ids: Collection<String>): Reponse<Unit> =
        authentifie(HttpMethod.Post, "mes-notifications/accuser/", buildJsonObject {
            put("etape", etape.name)
            put("ids", buildJsonArray { ids.forEach { add(it) } })
        }).sansValeur()

    // --- Le bénévole : disponibilités, fiche, titres, dossiers --------------------------------

    /** Ma grille. Avec une campagne, elle porte SA période : c'est la question posée. */
    suspend fun grille(campagne: String? = null): Reponse<Grille> =
        authentifie(HttpMethod.Get, "mes-disponibilites/" + (campagne?.let { "?campagne=$it" } ?: "")).transformer {
            json.decodeFromJsonElement(Grille.serializer(), it)
        }

    /** `creneau == null` : toute la journée. Rattaché à une campagne, le geste lui vaut réponse. */
    suspend fun declarerCreneau(date: String, creneau: Creneau?, disponible: Boolean, campagne: String? = null): Reponse<Unit> =
        authentifie(HttpMethod.Post, "mes-disponibilites/", buildJsonObject {
            put("date", date)
            put("disponible", disponible)
            if (creneau != null) put("creneau", creneau.name)
            if (campagne != null) put("campagne", campagne)
        }).sansValeur()

    /** « Je ne suis pas disponible sur cette période » : une réponse, elle aussi. */
    suspend fun repondreIndisponible(campagne: String): Reponse<Unit> =
        authentifie(HttpMethod.Post, "mes-disponibilites/indisponible/", buildJsonObject { put("campagne", campagne) }).sansValeur()

    suspend fun maFiche(): Reponse<Fiche> = authentifie(HttpMethod.Get, "ma-fiche-benevole/").transformer {
        json.decodeFromJsonElement(Fiche.serializer(), it)
    }

    /** Le secteur n'est pas envoyé : le serveur le déduit de l'adresse, et lui seul. */
    suspend fun enregistrerFiche(f: Fiche): Reponse<Fiche> =
        authentifie(HttpMethod.Patch, "ma-fiche-benevole/", buildJsonObject {
            put("adresse", f.adresse.trim())
            put("code_postal", f.codePostal.trim())
            put("ville", f.ville.trim())
            // Une date ou rien : le serveur refuse une chaîne vide.
            put("date_naissance", f.dateNaissance?.takeIf { it.isNotBlank() })
            put("metier", f.metier.trim())
            put("situation", f.situation)
            put("frequence_engagement", f.frequence)
            put("message", f.message.trim())
            put("diplome_premier_secours", f.premiersSecours)
        }).transformer { json.decodeFromJsonElement(Fiche.serializer(), it) }

    // --- Mon compte ----------------------------------------------------------------------------

    suspend fun modifierProfil(p: Profil): Reponse<Compte> =
        authentifie(HttpMethod.Patch, "me/", buildJsonObject {
            put("first_name", p.prenom.trim()); put("last_name", p.nom.trim()); put("phone_number", p.telephone.trim())
        }).transformer { json.decodeFromJsonElement(Compte.serializer(), it).also { compte -> session.mettreAJourLeCompte(compte) } }

    /** `ancien == null` : le compte n'a pas encore de mot de passe (créé par import), il en choisit un. */
    suspend fun changerMotDePasse(ancien: String?, nouveau: String): Reponse<Unit> =
        if (ancien == null) authentifie(HttpMethod.Post, "definir-mon-mot-de-passe/", buildJsonObject { put("nouveau_mot_de_passe", nouveau) }).sansValeur()
        else authentifie(HttpMethod.Post, "change-password/", buildJsonObject { put("old_password", ancien); put("new_password", nouveau) }).sansValeur()

    suspend fun catalogueDesTitres(): Reponse<List<TitreDuCatalogue>> = liste("qualifications/", TitreDuCatalogue.serializer())

    /**
     * Dépose la pièce d'un titre. `idTitreDeclare` : la déclaration existe déjà (pièce refusée,
     * ou titre saisi par l'encadrement) et l'on remplace sa pièce ; sinon on déclare le titre.
     */
    suspend fun deposerJustificatif(
        idCatalogue: String, idTitreDeclare: String?, octets: ByteArray, nomFichier: String, typeMime: String, dateObtention: String?,
    ): Reponse<Unit> = authentifie(
        if (idTitreDeclare == null) HttpMethod.Post else HttpMethod.Patch,
        if (idTitreDeclare == null) "qualifications-membres/" else "qualifications-membres/$idTitreDeclare/",
        formulaire = formData {
            if (idTitreDeclare == null) append("qualification", idCatalogue)
            if (idTitreDeclare == null && !dateObtention.isNullOrBlank()) append("date_obtention", dateObtention)
            append("justificatif", octets, Headers.build {
                append(HttpHeaders.ContentType, typeMime)
                append(HttpHeaders.ContentDisposition, "filename=\"${nomFichier.replace('"', '_')}\"")
            })
        },
    ).sansValeur()

    suspend fun mesTitres(idCompte: String): Reponse<List<Titre>> = liste("qualifications-membres/?utilisateur=$idCompte", Titre.serializer())

    suspend fun dossiers(): Reponse<List<Dossier>> = liste("dossiers/", Dossier.serializer())

    suspend fun definirStatutDossier(id: String, statut: String): Reponse<Unit> =
        authentifie(HttpMethod.Post, "dossiers/$id/definir-statut/", buildJsonObject { put("statut", statut) }).sansValeur()

    // --- Dossiers : commentaires et photos ----------------------------------------------------

    suspend fun commentaires(idDossier: String): Reponse<List<Commentaire>> =
        liste("dossier-commentaires/?dossier=$idDossier", Commentaire.serializer())

    suspend fun commenter(idDossier: String, texte: String): Reponse<Unit> =
        authentifie(HttpMethod.Post, "dossier-commentaires/", buildJsonObject { put("dossier", idDossier); put("commentaire", texte) }).sansValeur()

    suspend fun photos(idDossier: String): Reponse<List<Photo>> = liste("documents/?dossier=$idDossier", Photo.serializer())

    /**
     * Verse une photo au dossier. Le serveur calcule l'empreinte des octets reçus, lit la
     * position inscrite dans la photo, et journalise le dépôt : la réponse porte les deux.
     */
    suspend fun deposerPhoto(idDossier: String, octets: ByteArray, commentaire: String): Reponse<Photo> =
        authentifie(HttpMethod.Post, "documents/", formulaire = formData {
            append("dossier", idDossier)
            append("commentaire", commentaire)
            append("fichier", octets, Headers.build {
                append(HttpHeaders.ContentType, "image/jpeg")
                append(HttpHeaders.ContentDisposition, "filename=\"photo.jpg\"")
            })
        }).transformer { json.decodeFromJsonElement(Photo.serializer(), it) }

    /** Les octets d'une photo du dossier. Chaque lecture est journalisée par le serveur. */
    suspend fun octetsDePhoto(idPhoto: String): Reponse<ByteArray> {
        suspend fun lire(jeton: String): Reponse<ByteArray> = try {
            val reponse = http.request("$urlApi/documents/$idPhoto/preview/") { header(HttpHeaders.Authorization, "Bearer $jeton") }
            val code = reponse.status.value
            when {
                code in 200..299 -> Reponse.Ok(reponse.readRawBytes())
                code >= 500 || code == 408 || code == 429 -> Reponse.Injoignable("Le serveur ne répond pas correctement pour le moment (erreur $code).")
                else -> Reponse.Refus(code, "Cette photo n'est pas accessible.")
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Reponse.Injoignable("Le serveur est injoignable. Vérifiez votre connexion.")
        }
        val jeton = session.jetonAcces ?: return Reponse.Refus(401, SESSION_EXPIREE)
        val premiere = lire(jeton)
        if (premiere !is Reponse.Refus || premiere.code != 401) return premiere
        return when (val r = rafraichir(jeton)) {
            is Reponse.Ok -> lire(r.valeur)
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    private fun lireMessages(e: JsonElement): List<MessageEquipe> =
        json.decodeFromJsonElement(ListSerializer(MessageEquipe.serializer()), e.jsonObject.getValue("messages"))

    /** Révoque le jeton côté serveur si on peut, et oublie la session dans tous les cas. */
    suspend fun deconnecter() {
        session.jetonRafraichissement?.let { jeton ->
            appeler(HttpMethod.Post, "token/blacklist/", buildJsonObject { put("refresh", jeton) }, jeton = null)
        }
        session.fermer()
    }

    // --- Mécanique -----------------------------------------------------------------------

    private suspend fun authentifie(
        methode: HttpMethod, chemin: String, corps: JsonObject? = null, formulaire: List<PartData>? = null,
    ): Reponse<JsonElement> {
        val jeton = session.jetonAcces ?: return Reponse.Refus(401, SESSION_EXPIREE)
        val premiere = appeler(methode, chemin, corps, jeton, formulaire)
        if (premiere !is Reponse.Refus || premiere.code != 401) return premiere
        // Jeton d'accès périmé (il vit une heure) : un rafraîchissement, puis un seul nouvel essai.
        return when (val r = rafraichir(jeton)) {
            is Reponse.Ok -> appeler(methode, chemin, corps, r.valeur, formulaire)
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    /**
     * Un seul rafraîchissement à la fois : le serveur fait tourner le jeton, donc deux
     * échanges simultanés du même jeton en tueraient un — et la session avec.
     */
    private suspend fun rafraichir(jetonPerime: String): Reponse<String> = verrouRafraichissement.withLock {
        session.jetonAcces?.let { actuel -> if (actuel != jetonPerime) return@withLock Reponse.Ok(actuel) }
        val rafraichissement = session.jetonRafraichissement ?: return@withLock Reponse.Refus(401, SESSION_EXPIREE)
        when (val r = appeler(HttpMethod.Post, "token/refresh/", buildJsonObject { put("refresh", rafraichissement) }, jeton = null)) {
            is Reponse.Ok -> {
                val o = r.valeur.jsonObject
                val acces = o.texte("access")
                session.renouveler(acces, (o["refresh"] as? JsonPrimitive)?.content)
                Reponse.Ok(acces)
            }
            is Reponse.Refus -> {
                // Le serveur ne veut plus de ce jeton (sept jours passés, ou révoqué) :
                // seule une nouvelle connexion en donnera un autre.
                session.fermer()
                Reponse.Refus(401, SESSION_EXPIREE)
            }
            is Reponse.Injoignable -> r
        }
    }

    private suspend fun appeler(
        methode: HttpMethod, chemin: String, corps: JsonObject?, jeton: String?, formulaire: List<PartData>? = null,
    ): Reponse<JsonElement> {
        val reponse: HttpResponse
        val texte: String
        try {
            reponse = http.request("$urlApi/$chemin") {
                method = methode
                header(HttpHeaders.Accept, "application/json")
                jeton?.let { header(HttpHeaders.Authorization, "Bearer $it") }
                corps?.let { poserCorps(it) }
                formulaire?.let { setBody(MultiPartFormDataContent(it)) }
            }
            texte = reponse.bodyAsText()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return Reponse.Injoignable("Le serveur est injoignable. Vérifiez votre connexion.")
        }
        val code = reponse.status.value
        val element = runCatching { json.parseToJsonElement(texte) }.getOrNull()
        return when {
            code in 200..299 -> Reponse.Ok(element ?: JsonObject(emptyMap()))
            // Une panne du serveur n'est pas un refus : la même demande passera plus tard.
            // « Trop d'essais » sur un compte est une réponse du serveur, pas une panne : il
            // dit combien attendre, et c'est ce message qu'il faut montrer.
            code == 429 && (element as? JsonObject)?.containsKey("detail") == true -> lireRefus(code, element)
            code >= 500 || code == 408 || code == 429 ->
                Reponse.Injoignable("Le serveur ne répond pas correctement pour le moment (erreur $code).")
            else -> lireRefus(code, element)
        }
    }

    private fun HttpRequestBuilder.poserCorps(corps: JsonObject) {
        contentType(ContentType.Application.Json)
        setBody(corps.toString())
    }

    /** DRF répond `{"champ": ["message"]}`, `{"detail": "…"}`, et nos vues parfois `{"error": "…"}`. */
    private fun lireRefus(code: Int, element: JsonElement?): Reponse.Refus {
        val champs = mutableMapOf<String, String>()
        var message: String? = null
        (element as? JsonObject)?.forEach { (cle, valeur) ->
            val texte = when (valeur) {
                is JsonPrimitive -> valeur.content
                is JsonArray -> valeur.firstOrNull()?.let { (it as? JsonPrimitive)?.content }
                else -> null
            } ?: return@forEach
            if (cle in CLES_GENERALES) message = message ?: texte else champs[cle] = texte
        }
        return Reponse.Refus(
            code,
            message ?: champs.values.firstOrNull() ?: when (code) {
                401 -> SESSION_EXPIREE
                403 -> "Votre compte n'a pas le droit de faire cela."
                404 -> "Cet élément n'existe plus."
                else -> "La demande a été refusée (erreur $code)."
            },
            champs,
        )
    }

    private fun JsonObject.texte(cle: String): String = getValue(cle).jsonPrimitive.content

    private fun Reponse<JsonElement>.sansValeur(): Reponse<Unit> = transformer { }

    private inline fun <T> Reponse<JsonElement>.transformer(f: (JsonElement) -> T): Reponse<T> = when (this) {
        is Reponse.Ok -> try {
            Reponse.Ok(f(valeur))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Réponse 200 que l'on ne sait pas lire : le serveur a changé de format. On ne
            // peut rien en faire, mais on ne plante pas l'application pour autant.
            Reponse.Injoignable("La réponse du serveur est illisible. L'application doit peut-être être mise à jour.")
        }
        is Reponse.Refus -> this
        is Reponse.Injoignable -> this
    }

    companion object {
        const val SESSION_EXPIREE = "Votre session a expiré. Reconnectez-vous."
        private val CLES_GENERALES = setOf("detail", "error", "non_field_errors", "message")
        const val SECOND_FACTEUR_A_ACTIVER = "SECOND_FACTEUR_A_ACTIVER"
    }
}
