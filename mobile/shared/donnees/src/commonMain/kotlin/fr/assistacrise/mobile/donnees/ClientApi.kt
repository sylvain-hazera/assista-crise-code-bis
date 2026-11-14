package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Champs
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.MessageEquipe
import fr.assistacrise.mobile.domaine.PositionMembre
import fr.assistacrise.mobile.domaine.Inscription
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.StatutMission
import io.ktor.client.HttpClient
import io.ktor.client.request.HttpRequestBuilder
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
import kotlinx.serialization.json.buildJsonObject
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

    suspend fun connecter(email: String, motDePasse: String): Reponse<Compte> {
        val corps = buildJsonObject { put("email", email.trim()); put("password", motDePasse) }
        return when (val r = appeler(HttpMethod.Post, "token/", corps, jeton = null)) {
            is Reponse.Ok -> {
                val o = r.valeur.jsonObject
                val compte = json.decodeFromJsonElement(Compte.serializer(), o.getValue("user"))
                session.ouvrir(o.texte("access"), o.texte("refresh"), compte)
                Reponse.Ok(compte)
            }
            // SimpleJWT répond 401 en anglais, sans distinguer mauvais mot de passe et compte
            // inactif. On le dit en français, en couvrant les deux cas.
            is Reponse.Refus -> if (r.code == 401) r.copy(
                message = "Adresse ou mot de passe incorrect. Si votre compte attend une " +
                    "validation, il ne peut pas encore se connecter.",
            ) else r
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
    suspend fun deposer(chemin: String, corps: String): Reponse<Unit> {
        val objet = runCatching { json.parseToJsonElement(corps).jsonObject }.getOrNull()
            ?: return Reponse.Refus(400, "Dépôt illisible.")
        return authentifie(HttpMethod.Post, chemin, objet).sansValeur()
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

    private suspend fun authentifie(methode: HttpMethod, chemin: String, corps: JsonObject? = null): Reponse<JsonElement> {
        val jeton = session.jetonAcces ?: return Reponse.Refus(401, SESSION_EXPIREE)
        val premiere = appeler(methode, chemin, corps, jeton)
        if (premiere !is Reponse.Refus || premiere.code != 401) return premiere
        // Jeton d'accès périmé (il vit une heure) : un rafraîchissement, puis un seul nouvel essai.
        return when (val r = rafraichir(jeton)) {
            is Reponse.Ok -> appeler(methode, chemin, corps, r.valeur)
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

    private suspend fun appeler(methode: HttpMethod, chemin: String, corps: JsonObject?, jeton: String?): Reponse<JsonElement> {
        val reponse: HttpResponse
        val texte: String
        try {
            reponse = http.request("$urlApi/$chemin") {
                method = methode
                header(HttpHeaders.Accept, "application/json")
                jeton?.let { header(HttpHeaders.Authorization, "Bearer $it") }
                corps?.let { poserCorps(it) }
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
    }
}
