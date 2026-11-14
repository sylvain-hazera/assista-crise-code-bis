package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Etape
import fr.assistacrise.mobile.domaine.Notification
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.SetSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * Mes notifications, et ce que ce téléphone doit encore en dire au serveur.
 *
 * Un accusé est une promesse faite à quelqu'un d'autre : l'encadrement décide de relancer
 * ou non d'après lui. Il est donc écrit sur disque AVANT tout envoi, comme le reste de la
 * file — lire un message dans un tunnel doit finir par se savoir.
 */
class DepotNotifications(
    private val api: ClientApi,
    private val magasin: Magasin,
    /** Tire un identifiant d'installation au hasard. Aucun identifiant du matériel. */
    private val nouvelIdentifiant: () -> String,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val verrou = Mutex()

    private val _notifications = MutableStateFlow<List<Notification>>(emptyList())
    val notifications: StateFlow<List<Notification>> = _notifications

    /** Par étape, les identifiants à accuser. Une étape plus avancée remplace les précédentes. */
    private var aAccuser: Map<String, Set<String>> = emptyMap()

    suspend fun restaurer() {
        _notifications.value = magasin.lire(FICHIER)?.let {
            runCatching { json.decodeFromString(ListSerializer(Notification.serializer()), it) }.getOrNull()
        } ?: emptyList()
        aAccuser = magasin.lire(FICHIER_ACCUSES)?.let {
            runCatching { json.decodeFromString(FORME_ACCUSES, it) }.getOrNull()
        } ?: emptyMap()
    }

    /** L'identifiant de cette installation, créé au premier besoin et gardé ensuite. */
    suspend fun installation(): String =
        magasin.lire(FICHIER_INSTALLATION) ?: nouvelIdentifiant().also { magasin.ecrire(FICHIER_INSTALLATION, it) }

    suspend fun presenter(plateforme: String, version: String, notificationsAutorisees: Boolean): Reponse<Unit> =
        api.presenterAppareil(installation(), plateforme, version, notificationsAutorisees)

    /** Envoie les accusés qui attendent, puis relit la liste. */
    suspend fun rafraichir(): Reponse<Unit> {
        envoyerLesAccuses()
        return when (val r = api.notifications()) {
            is Reponse.Ok -> {
                magasin.ecrire(FICHIER, json.encodeToString(ListSerializer(Notification.serializer()), r.valeur))
                _notifications.value = r.valeur
                Reponse.Ok(Unit)
            }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    /** Note une étape franchie. Rien n'est noté pour ce que le serveur sait déjà. */
    suspend fun noter(etape: Etape, ids: Collection<String>) {
        val utiles = ids.filter { id -> _notifications.value.firstOrNull { it.id == id }?.let { !dejaAccusee(it, etape) } ?: true }
        if (utiles.isEmpty()) return
        verrou.withLock {
            aAccuser = aAccuser + (etape.name to (aAccuser[etape.name].orEmpty() + utiles))
            magasin.ecrire(FICHIER_ACCUSES, json.encodeToString(FORME_ACCUSES, aAccuser))
        }
        envoyerLesAccuses()
    }

    /** @return vrai si plus rien n'attend. */
    suspend fun envoyerLesAccuses(): Boolean = verrou.withLock {
        // Du plus avancé au moins avancé : « lue » entraîne « vue » et « remise » côté serveur.
        for (etape in Etape.entries.reversed()) {
            val ids = aAccuser[etape.name].orEmpty()
            if (ids.isEmpty()) continue
            when (api.accuser(etape, ids)) {
                is Reponse.Injoignable -> return@withLock false
                // Ok, ou refusé pour de bon : dans les deux cas réessayer n'apporterait rien.
                else -> {
                    aAccuser = aAccuser - etape.name
                    magasin.ecrire(FICHIER_ACCUSES, json.encodeToString(FORME_ACCUSES, aAccuser))
                }
            }
        }
        true
    }

    /** Combien attendent encore d'être vues : le chiffre de la pastille. */
    fun nonVues(): Int = _notifications.value.count { it.dateVue == null && it.id !in aAccuser[Etape.VUE.name].orEmpty() && it.id !in aAccuser[Etape.LUE.name].orEmpty() }

    /** À la déconnexion. L'identifiant d'installation, lui, reste : c'est celui du téléphone. */
    suspend fun toutEffacer() {
        api.oublierAppareil(installation())
        magasin.effacer(FICHIER); magasin.effacer(FICHIER_ACCUSES)
        _notifications.value = emptyList()
        aAccuser = emptyMap()
    }

    private fun dejaAccusee(n: Notification, etape: Etape): Boolean = when (etape) {
        Etape.REMISE -> n.dateRemise != null
        Etape.VUE -> n.dateVue != null
        Etape.LUE -> n.dateLue != null
    }

    private companion object {
        const val FICHIER = "notifications"
        const val FICHIER_ACCUSES = "notifications-accuses"
        const val FICHIER_INSTALLATION = "installation"
        val FORME_ACCUSES = MapSerializer(String.serializer(), SetSerializer(String.serializer()))
    }
}
