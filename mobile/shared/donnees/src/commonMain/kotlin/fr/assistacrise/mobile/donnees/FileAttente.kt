package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.EtatAction
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlin.random.Random

/**
 * La file d'attente sortante (dossier § 5). Tout geste passe par elle, y compris en 4G.
 *
 * - **Persistée** : un redémarrage du téléphone ne perd rien.
 * - **Ordonnée** : les actions partent dans l'ordre où elles ont été déclarées.
 * - **Visible** : `actions` est ce que l'écran affiche.
 * - **Purgée sur accusé seulement** : une action ne sort que si le serveur a dit oui. « Envoi
 *   tenté » ne prouve rien.
 */
class FileAttente(
    private val magasin: Magasin,
    private val horloge: () -> Long,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val verrou = Mutex()

    private val _actions = MutableStateFlow<List<ActionEnAttente>>(emptyList())
    val actions: StateFlow<List<ActionEnAttente>> = _actions

    suspend fun restaurer() = verrou.withLock {
        val texte = magasin.lire(FICHIER) ?: return@withLock
        _actions.value = runCatching {
            json.decodeFromString(ListSerializer(ActionEnAttente.serializer()), texte)
        }.getOrDefault(emptyList())
    }

    suspend fun ajouter(genre: String, cible: String, charge: String, libelle: String): ActionEnAttente = verrou.withLock {
        val action = ActionEnAttente(
            id = "${horloge()}-${Random.nextLong().toULong().toString(16)}",
            genre = genre, cible = cible, charge = charge, libelle = libelle, creeLe = horloge(),
        )
        enregistrer(_actions.value + action)
        action
    }

    /**
     * Comme `ajouter`, mais en remplaçant ce qui attendait déjà pour ce genre. Pour ce dont
     * seule la dernière valeur compte — une position : inutile d'envoyer dix positions
     * périmées au retour du réseau.
     */
    suspend fun remplacer(genre: String, cible: String, charge: String, libelle: String): ActionEnAttente = verrou.withLock {
        val action = ActionEnAttente(
            id = "${horloge()}-${Random.nextLong().toULong().toString(16)}",
            genre = genre, cible = cible, charge = charge, libelle = libelle, creeLe = horloge(),
        )
        enregistrer(_actions.value.filterNot { it.genre == genre && it.cible == cible } + action)
        action
    }

    /**
     * Note qu'une action est partie par la radio. **À n'appeler que depuis le rappel de
     * `vider`** : le verrou est déjà tenu, celle-ci ne le reprend pas.
     */
    suspend fun noterParRadio(id: String, protocole: String) {
        enregistrer(_actions.value.map { if (it.id == id) it.copy(radio = protocole) else it })
    }

    suspend fun retirer(id: String) = verrou.withLock {
        enregistrer(_actions.value.filterNot { it.id == id })
    }

    suspend fun toutEffacer() = verrou.withLock { enregistrer(emptyList()) }

    /**
     * Tente d'envoyer ce qui attend. `force` ignore le recul progressif (geste de
     * l'utilisateur, retour du réseau).
     *
     * S'arrête au premier « injoignable » : si le serveur ne répond pas pour une action, il
     * ne répondra pas pour la suivante, et l'ordre doit être préservé — sauf pour une action
     * qui a déjà échoué `ESSAIS_BLOQUANTS` fois. Un refus, lui, ne bloque pas la suite : il
     * est noté et reste affiché.
     *
     * @return le nombre d'actions accusées.
     */
    suspend fun vider(force: Boolean = false, envoyer: suspend (ActionEnAttente) -> Reponse<Unit>): Int = verrou.withLock {
        var accusees = 0
        for (action in _actions.value) {
            if (action.etat != EtatAction.EN_ATTENTE) continue
            if (!force && horloge() < action.prochainEssai) break
            when (val r = envoyer(action)) {
                is Reponse.Ok -> {
                    enregistrer(_actions.value.filterNot { it.id == action.id })
                    accusees++
                }
                is Reponse.Refus -> remplacer(courante(action).copy(etat = EtatAction.REFUSEE, erreur = r.message))
                is Reponse.Injoignable -> {
                    val tentatives = action.tentatives + 1
                    remplacer(courante(action).copy(
                        tentatives = tentatives,
                        prochainEssai = horloge() + recul(tentatives),
                        erreur = r.message,
                    ))
                    // Les premiers échecs arrêtent tout : c'est sans doute le réseau, et
                    // l'ordre compte. Mais une action qui échoue encore et encore (le serveur
                    // plante sur elle) ne doit pas retenir toutes les autres derrière elle.
                    if (tentatives <= ESSAIS_BLOQUANTS) break
                }
            }
        }
        accusees
    }

    /** L'action telle qu'elle est maintenant : le rappel a pu la marquer entre-temps. */
    private fun courante(action: ActionEnAttente) = _actions.value.firstOrNull { it.id == action.id } ?: action

    private suspend fun remplacer(action: ActionEnAttente) =
        enregistrer(_actions.value.map { if (it.id == action.id) action else it })

    private suspend fun enregistrer(liste: List<ActionEnAttente>) {
        // Disque d'abord, mémoire ensuite : ce que l'écran montre est toujours déjà écrit.
        magasin.ecrire(FICHIER, json.encodeToString(ListSerializer(ActionEnAttente.serializer()), liste))
        _actions.value = liste
    }

    companion object {
        private const val FICHIER = "file-attente"
        const val RECUL_INITIAL_MS = 5_000L

        /** Nombre d'échecs pendant lesquels une action retient encore celles qui la suivent. */
        const val ESSAIS_BLOQUANTS = 3
        const val RECUL_MAX_MS = 5 * 60_000L

        /** 5 s, 10 s, 20 s… plafonné à 5 min. */
        fun recul(tentatives: Int): Long =
            (RECUL_INITIAL_MS shl (tentatives - 1).coerceIn(0, 10)).coerceAtMost(RECUL_MAX_MS)
    }
}
